#!/usr/bin/env python

import ConfigParser
import logging
import paho.mqtt.client as mqtt
import socket
import sys
from threading import Thread, Lock
import time

LOG_FORMAT = '%(levelname) -10s %(asctime)s %(name) -30s %(funcName) -35s %(lineno) -5d: %(message)s'
LOGGER = logging.getLogger(__name__)

class StreamInterface():
    def __init__(self, rx_port):
        self.__sock = None
        self.__message_counter = 0
        self.__bytes_counter = 0
        self.__last_time = time.time()
        self.__receive_time = time.time()
        self.__rx_port = rx_port
        self.on_message_callback = None

    def on_receive(self):
        (data, source_ip_port) = self.__sock.recvfrom(4096)
        self.__receive_time = time.time()

        self.__message_counter += 1
        self.__bytes_counter += sys.getsizeof(data) - 37
        if (self.__message_counter % 1000 == 0):
            LOGGER.warn('Received LTE data #{0}, rate: {1} kB/s'.format(self.__message_counter, self.__bytes_counter / (1000.0 * (time.time() - self.__last_time))))
            self.__last_time = time.time()
            self.__bytes_counter = 0
        else:
            LOGGER.info('Received LTE data #%d', self.__message_counter)

        self.on_message_callback(data)


    def open(self):
        LOGGER.warn('Opening UDP port %d', self.__rx_port)
        self.__sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.__sock.setblocking(True)
        self.__sock.bind(('', self.__rx_port)) # all available interfaces

    def close(self):
        LOGGER.warn('Closing UDP port')
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
        self.__last_message_received = time.time()

    def __connect(self):
        self.__client = mqtt.Client('stream_relay')
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

        elif rc == 3:
            LOGGER.warn('Connected failed, server unavailable, retrying in 1 second')
        else:
            self.bad_connection_flag = True
            LOGGER.error('Connected failed with result code ' + str(rc))

    def __on_disconnect(self, client, userdata, rc):
        self.__client_connected_flag = False
        LOGGER.warn('Client disconnecting, reason: ' + str(rc))

    def __publish_message(self, topic, data, retain):
        self.__client.publish(topic, data, retain=retain)
        self.__publish_counter += 1
        LOGGER.info('Published message # %i to ' + topic, self.__publish_counter - 1)

    def publish_stream_data(self, data):
        self.__publish_message('stream/data', data, False)

    def start(self):
        self.__connect()

    def stop(self):
        self.__client.loop_stop()
        self.__client.disconnect()
        self.__client = None
        LOGGER.warn('Stopped')


def main():
    config_file = 'stream_relay.cfg'
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
        rx_port = config.getint('stream', 'target_port')

    except ConfigParser.Error as e:
        print('Error reading configuration files ' + config_file + ' and ' + credentials_file + ':')
        print(e)
        quit()

    logging.basicConfig(filename='stream_relay.log', level=logging.WARN, format=LOG_FORMAT)
    console = logging.StreamHandler()
    console.setLevel(logging.WARN)
    formatter = logging.Formatter(LOG_FORMAT)
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)
    mi = MqttInterface(host, port, user, pwd)
    si = StreamInterface(rx_port)

    si.on_message_callback = mi.publish_stream_data

    si.open()
    mi.start()

    try:
        while(True):
            si.on_receive()
    except KeyboardInterrupt:
        # start the stopping in a separate thread so that is not
        # stopped by the KeyboardInterrupt
        a = Thread(target=mi.stop())
        a.start()
        a.join()
        a = Thread(target=si.close())
        a.start()
        a.join()


if __name__ == '__main__':
    main()
