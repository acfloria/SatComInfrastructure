#!/usr/bin/env python

import ConfigParser
import logging
import paho.mqtt.client as mqtt
import socket
import sys
from threading import Thread, Lock
import time
import tornado.web
import tornado.ioloop
import tornado.httpclient
import tornado.httputil

LOG_FORMAT = '%(levelname) -10s %(asctime)s %(name) -30s %(funcName) -35s %(lineno) -5d: %(message)s'
LOGGER = logging.getLogger(__name__)

class LteInterface():
    def __init__(self, rx_port):
        self.__sock = None
        self.__rx_port = rx_port
        self.__host_ip = None
        self.__message_counter = 0
        self.__bytes_counter = 0
        self.__last_time = time.clock()
        self.on_message_callback = None

    def on_receive(self, fd, events):
        (data, source_ip_port) = self.__sock.recvfrom(4096)

        self.__message_counter += 1
        self.__bytes_counter += sys.getsizeof(data)
        if (self.__message_counter % 1000 == 0):
            LOGGER.warn('Received LTE data #{0}, rate: {1} kB/s'.format(self.__message_counter, self.__bytes_counter / (1000.0 * (time.clock() - self.__last_time))))
            self.__last_time = time.clock()
            self.__bytes_counter = 0
        else:
            LOGGER.info('Received LTE data #%d', self.__message_counter)

        self.__host_ip = source_ip_port[0]
        self.__tx_port = source_ip_port[1]
        self.on_message_callback(data)

    def send(self, data):
        if (self.__host_ip != None):
            LOGGER.info('Sending LTE data to %s:%d', self.__host_ip, self.__tx_port)
            self.__sock.sendto(data, (self.__host_ip, self.__tx_port))
        else:
            LOGGER.warn('No IP port available, unable to send over UDP')

    def open(self):
        LOGGER.warn('Opening UDP port %d', self.__rx_port)
        self.__sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.__sock.setblocking(False)
        tornado.ioloop.IOLoop.current().add_handler(self.__sock.fileno(), self.on_receive, tornado.ioloop.IOLoop.READ)
        self.__sock.bind(('', self.__rx_port)) # all available interfaces

    def close(self):
        LOGGER.warn('Closing UDP port')
        tornado.ioloop.IOLoop.current().remove_handler(self.__sock.fileno())
        self.__sock.close()
        self.__sock = None


class IridiumInterface:
    def __init__(self, iridium_url, local_port, rock7_credentials):
        self.__http_server = None
        self.__http_client = tornado.httpclient.AsyncHTTPClient()
        self.__url = iridium_url
        self.__port = local_port
        self.__waiting_for_confirm = {}
        self.__post_data = rock7_credentials
        self.__threads = []
        self.__lock = Lock()
        self.on_message_callback = None

    def __on_message_sent(self, response):
        self.__lock.acquire()
        idx, data = self.__waiting_for_confirm.pop(response.request)

        # clean up threads
        for thr in self.__threads:
            if not thr.is_alive():
                self.__threads.remove(thr)

        if response.error:
            LOGGER.warn('Error sending: %s', response.error)
            thr_redeliver = Thread(target=self.__repost_message, args=(data, idx))
            thr_redeliver.daemon = True
            thr_redeliver.start()
            self.__threads.append(thr_redeliver)
        
        self.__lock.release()

    def __repost_message(self, data, idx):
        time.sleep(10.0)
        self.post_message(data, idx)

    class PostHandler(tornado.web.RequestHandler):
        def initialize(self, cb):
            self.on_msg_callback = cb

        @tornado.web.asynchronous
        def post(self):
            LOGGER.warn('Received MO message from Iridium')
            try:
                msg = self.request.arguments['data'][0].decode('hex')
            except:
                LOGGER.warn('Failed to decode the MO message')
                self.set_status(400)
                self.finish()
            else:
                self.on_msg_callback(msg)
                self.finish() #TODO check if the message was successfully published

    def post_message(self, data, idx):
        self.__lock.acquire()
        LOGGER.info('Sending MT message # %i to Iridium', idx)
        self.__post_data['data'] = data.encode('hex')
        body = tornado.httputil.urlencode(self.__post_data)
        request = tornado.httpclient.HTTPRequest(self.__url, method='POST', body=body)
        self.__waiting_for_confirm[request] = (idx, data)
        self.__lock.release()
        self.__http_client.fetch(request, self.__on_message_sent)
        

    def start(self):
        args = dict(cb=self.on_message_callback)
        self.__http_server = tornado.web.Application([(r"/", self.PostHandler, args)])
        self.__http_server.listen(self.__port)
        LOGGER.warn('Starting iridum interface on %s', self.__url)

class MqttInterface(object):
    def __init__(self, ip, port, user, pwd):
        self.__broker_ip = ip
        self.__broker_port = port
        self.__broker_user = user
        self.__broker_pwd = pwd
        self.__client = None
        self.__client_connected_flag = False
        self.__client_bad_connection_flag = False
        self.__publish_counter = 1
        self.__iridium_counter = 0
        self.lte_on_message_callback = None
        self.satcom_on_message_callback = None

    def __connect(self):
        self.__client = mqtt.Client('relay_server')
        self.__client.on_connect = self.__on_connect
        self.__client.on_message = self.__on_message
        self.__client.on_disconnect = self.__on_disconnect
        self.__client.username_pw_set(self.__broker_user, self.__broker_pwd)

        self.__client.enable_logger(LOGGER)

        self.__client.loop_start()
        self.__client.connect(self.__broker_ip, self.__broker_port)

        # wait in loop until connect is done
        while not self.__client_connected_flag and not self.__client_bad_connection_flag:
            time.sleep(1)

        if self.__client_bad_connection_flag:
            self.__client.loop_stop()
            sys.exit()

    def __on_message(self, client, userdata, message):
        LOGGER.warn('Received message from unknown topic: ' + message.topic)

    def __on_connect(self, client, userdata, flags, rc):
        if rc==0:
            self.__client_connected_flag = True
            LOGGER.warn('Connected with result code ' + str(rc))

            # Subscribing in on_connect() means that if we lose the connection and
            # reconnect then subscriptions will be renewed.
            client.subscribe('telem/LTE_to_plane', qos=2)
            client.subscribe('telem/SatCom_to_plane', qos=2)

            # add the callback to handle the respective queues
            client.message_callback_add('telem/LTE_to_plane', self.__callback_LTE)
            client.message_callback_add('telem/SatCom_to_plane', self.__callback_SatCom)
        elif rc == 3:
            LOGGER.warn('Connected failed, server unavailable, retrying in 1 second')
        else:
            self.bad_connection_flag = True
            LOGGER.error('Connected failed with result code ' + str(rc))

    def __on_disconnect(self, client, userdata, rc):
        self.__client_connected_flag = False
        LOGGER.warn('Client disconnecting, reason: ' + str(rc))

    def __callback_SatCom(self, client, userdata, msg):
        self.__iridium_counter += 1
        LOGGER.info('MQTT received message from ' + msg.topic)
        self.satcom_on_message_callback(msg.payload, self.__iridium_counter)

    def __callback_LTE(self, client, userdata, msg):
        LOGGER.info('MQTT received message from ' + msg.topic)
        self.lte_on_message_callback(msg.payload)

    def __publish_message(self, topic, data, retain):
        self.__client.publish(topic, data, qos=2, retain=retain)
        self.__publish_counter += 1
        LOGGER.info('Published message # %i to ' + topic, self.__publish_counter - 1)

    def publish_lte_message(self, data):
        self.__publish_message('telem/LTE_from_plane', data, False)

    def publish_satcom_message(self, data):
        self.__publish_message('telem/SatCom_from_plane', data, True)

    def start(self):
        self.__connect()

    def stop(self):
        self.__client.loop_stop()
        self.__client.disconnect()
        self.__client = None
        LOGGER.warn('Stopped')


def main():
    config_file = 'relay.cfg'
    config = ConfigParser.RawConfigParser()
    credentials_file = 'credentials.cfg'
    credentials = ConfigParser.RawConfigParser()
    rock7_credentials = {}
    try:
        config.read(config_file)
        credentials.read(credentials_file)
        host = config.get('mqtt', 'hostname')
        port = config.getint('mqtt', 'port')
        user = credentials.get('mqtt', 'user')
        pwd = credentials.get('mqtt', 'password')
        rx_port = config.getint('lte', 'target_port')
        iridium_url = config.get('iridium', 'url')
        iridium_local_port = config.getint('iridium', 'local_port')
        rock7_credentials['imei'] = credentials.get('rockblock', 'imei')
        rock7_credentials['username'] = credentials.get('rockblock', 'username')
        rock7_credentials['password'] = credentials.get('rockblock', 'password')

    except ConfigParser.Error as e:
        print('Error reading configuration files ' + config_file + ' and ' + credentials_file + ':')
        print(e)
        quit()

    logging.basicConfig(filename='relay.log', level=logging.WARN, format=LOG_FORMAT)
    console = logging.StreamHandler()
    console.setLevel(logging.WARN)
    formatter = logging.Formatter(LOG_FORMAT)
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)
    mi = MqttInterface(host, port, user, pwd)
    li = LteInterface(rx_port)
    ii = IridiumInterface(iridium_url, iridium_local_port, rock7_credentials)

    mi.lte_on_message_callback = li.send
    mi.satcom_on_message_callback = ii.post_message
    li.on_message_callback = mi.publish_lte_message
    ii.on_message_callback = mi.publish_satcom_message

    li.open()
    ii.start()
    mi.start()

    try:
        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt:
        # start the stopping in a separate thread so that is not
        # stopped by the KeyboardInterrupt
        a = Thread(target=mi.stop()) 
        a.start()
        a.join()
        

if __name__ == '__main__':
    main()
