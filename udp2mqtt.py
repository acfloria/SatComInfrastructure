#!/usr/bin/env python

import ConfigParser
import logging
import paho.mqtt.client as mqtt
import socket
from threading import Thread
import time
import tornado.web
import tornado.ioloop
import tornado.httpclient
import tornado.httputil

LOG_FORMAT = '%(levelname) -10s %(asctime)s %(name) -30s %(funcName) -35s %(lineno) -5d: %(message)s'
LOGGER = logging.getLogger(__name__)


class UdpInterface():
    def __init__(self, rx_port, tx_port, type):
        self.__sock = None
        self.__rx_port = rx_port
        self.__tx_port = tx_port
        self.__type = type
        self.on_message_callback = None

    def on_receive(self, fd, events):
        LOGGER.info('Received' + self.__type + ' data on UDP')
        (data, source_ip_port) = self.__sock.recvfrom(4096)
        self.on_message_callback(data)

    def send(self, data):
        LOGGER.info('Sending' + self.__type + ' data on UDP')
        self.__sock.sendto(data, ('localhost', self.__tx_port))

    def open(self):
        LOGGER.warn('Opening UDP port %d', self.__rx_port)
        self.__sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.__sock.setblocking(False)
        tornado.ioloop.IOLoop.current().add_handler(self.__sock.fileno(), self.on_receive, tornado.ioloop.IOLoop.READ)
        self.__sock.bind(('localhost', self.__rx_port))

    def close(self):
        LOGGER.warn('Closing UDP port')
        tornado.ioloop.IOLoop.current().remove_handler(self.__sock.fileno())
        self.__sock.close()
        self.__sock = None


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
        self.lte_on_message_callback = None
        self.satcom_on_message_callback = None

    def __connect(self):
        self.__client = mqtt.Client()
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
            client.subscribe('telem/LTE_from_plane', qos=2)
            client.subscribe('telem/SatCom_from_plane', qos=2)

            # add the callback to handle the respective queues
            client.message_callback_add('telem/LTE_from_plane', self.__callback_LTE)
            client.message_callback_add('telem/SatCom_from_plane', self.__callback_SatCom)
        elif rc == 3:
            LOGGER.warn('Connected failed, server unavailable, retrying in 1 second')
        else:
            self.bad_connection_flag = True
            LOGGER.error('Connected failed with result code ' + str(rc))

    def __on_disconnect(self, client, userdata, rc):
        self.__client_connected_flag = False
        LOGGER.warn('Client disconnecting, reason: ' + str(rc))

    def __callback_SatCom(self, client, userdata, msg):
        LOGGER.info('MQTT received message from ' + msg.topic)
        self.satcom_on_message_callback(msg.payload)

    def __callback_LTE(self, client, userdata, msg):
        LOGGER.info('MQTT received message from ' + msg.topic)
        self.lte_on_message_callback(msg.payload)

    def __publish_message(self, topic, data):
        self.__client.publish(topic, data, qos=2, retain=False)
        self.__publish_counter += 1
        LOGGER.info('Published message # %i to ' + topic, self.__publish_counter - 1)

    def publish_lte_message(self, data):
        self.__publish_message('telem/LTE_to_plane', data)

    def publish_satcom_message(self, data):
        self.__publish_message('telem/SatCom_to_plane', data)

    def start(self):
        self.__connect()

    def stop(self):
        self.__client.loop_stop()
        self.__client.disconnect()
        self.__client = None
        LOGGER.warn('Stopped')


def main():
    config_file = 'udp2mqtt.cfg'
    config = ConfigParser.RawConfigParser()
    credentials_file = 'credentials.cfg'
    credentials = ConfigParser.RawConfigParser()
    try:
        config.read(config_file)
        credentials.read(credentials_file)
        host = config.get('mqtt', 'hostname')
        port = config.getint('mqtt', 'port')
        user = credentials.get('mqtt', 'user')
        pwd = credentials.get('mqtt', 'password')
        lte_rx_port = config.getint('lte', 'target_port')
        lte_tx_port = config.getint('lte', 'listening_port')
        satcom_rx_port = config.getint('satcom', 'target_port')
        satcom_tx_port = config.getint('satcom', 'listening_port')
    except ConfigParser.Error as e:
        print('Error reading configuration files ' + config_file + ' and ' + credentials_file + ':')
        print(e)
        quit()

    logging.basicConfig(filename='udp2mqtt.log', level=logging.INFO, format=LOG_FORMAT)
    console = logging.StreamHandler()
    console.setLevel(logging.WARN)
    formatter = logging.Formatter(LOG_FORMAT)
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)
    mi = MqttInterface(host, port, user, pwd)
    li = UdpInterface(lte_rx_port, lte_tx_port, 'LTE')
    si = UdpInterface(satcom_rx_port, satcom_tx_port, 'SatCom')

    mi.lte_on_message_callback = li.send
    mi.satcom_on_message_callback = si.send
    li.on_message_callback = mi.publish_lte_message
    si.on_message_callback = mi.publish_satcom_message

    li.open()
    si.open()
    mi.start() # needs to be called last because the mqtt loop is started in here

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
