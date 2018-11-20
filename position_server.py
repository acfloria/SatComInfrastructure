#!/usr/bin/env python

import logging
import ConfigParser
import paho.mqtt.client as mqtt
from pymavlink import mavlink
import socket
from threading import Thread
import time
from datetime import datetime
import tornado.web
import tornado.ioloop
import tornado.httpclient
import tornado.httputil
from BaseHTTPServer import BaseHTTPRequestHandler,HTTPServer
import json
import argparse

LOG_FORMAT = '%(levelname) -10s %(asctime)s %(name) -30s %(funcName) -35s %(lineno) -5d: %(message)s'
LOGGER = logging.getLogger(__name__)
MAV = mavlink.MAVLink(0)

class InvoliPositionMessage(object):
    # posdata = mavlink.MAVLink_global_position_int_message(0,0,0,0,0,0,0,0,0)
    position_data = {'latDD': 0,
            'lonDD': 0,
            'GPSaltitudeMM': 0,
            'headingDE': 0,
            'horVelocityCMS': 0,
            'verVelocityCMS': 0,
            'callsign': 'ASLSS2A',
            'timeStamp': ''}

    def print_message(self, data):
        m = MAV.parse_buffer(data)
        for msg in m:
            # print 'MAV MSG %3d %s' % (msg.get_msgId(), msg.get_type())
            if (msg.get_msgId() == 24):
                self.set_message(msg)
                LOGGER.debug(msg)

    def set_message(self, msg):
        self.position_data['latDD'] = msg.lat / 1e7
        self.position_data['lonDD'] = msg.lon / 1e7
        self.position_data['GPSaltitudeMM'] = msg.alt
        self.position_data['groundspeed'] = msg.vel
        self.position_data['timeStamp'] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")
        # self.position_data['climbrate'] = msg.vz
        # self.position_data['heading'] = msg.hdg


class myHandler(BaseHTTPRequestHandler):

    # def __init__(self, *args, **kwargs):
    #     self.position_message = InvoliPositionMessage()
    #     # BaseHTTPRequestHandler calls do_GET **inside** __init__ !!!
    #     # So we have to call super().__init__ after setting attributes.
    #     super().__init__(*args, **kwargs)

    #Handler for the GET requests
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type','text/json')
        self.end_headers()
        # Send the html message
        json.dump(pos_message.position_data, self.wfile, indent=4, separators=(',', ': '))
        LOGGER.info('GET request received')
        #self.wfile.write(posdata)
        return


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
            LOGGER.error('Bad connection flag')
            raise RuntimeError('Bad client connection flag on connect')

    def __on_message(self, client, userdata, message):
        LOGGER.warning('Received message from unknown topic: ' + message.topic)

    def __on_connect(self, client, userdata, flags, rc):
        if rc==0:
            self.__client_connected_flag = True
            LOGGER.warning('Connected with result code ' + str(rc))

            # Subscribing in on_connect() means that if we lose the connection and
            # reconnect then subscriptions will be renewed.
            client.subscribe('telem/LTE_from_plane', qos=2)
            client.subscribe('telem/SatCom_from_plane', qos=2)

            # add the callback to handle the respective queues
            client.message_callback_add('telem/LTE_from_plane', self.__callback_LTE)
            client.message_callback_add('telem/SatCom_from_plane', self.__callback_SatCom)
        elif rc == 3:
            LOGGER.warning('Connected failed, server unavailable, retrying in 1 second')
        else:
            self.bad_connection_flag = True
            LOGGER.error('Connected failed with result code ' + str(rc))

    def __on_disconnect(self, client, userdata, rc):
        self.__client_connected_flag = False
        LOGGER.warning('Client disconnecting, reason: ' + str(rc))

    def __callback_SatCom(self, client, userdata, msg):
        LOGGER.info('MQTT received message from ' + msg.topic)
        self.mavlink_message_callback(msg.payload)

    def __callback_LTE(self, client, userdata, msg):
        LOGGER.info('MQTT received message from ' + msg.topic)
        self.mavlink_message_callback(msg.payload)

    def start(self):
        self.__connect()

    def stop(self):
        self.__client.loop_stop()
        self.__client.disconnect()
        self.__client = None
        LOGGER.warning('Stopped')


class PositionServer(object):
    def __init__(self, config_file, credentials_file, log_level=logging.WARN):
        # Create config readers
        config = ConfigParser.RawConfigParser()
        credentials = ConfigParser.RawConfigParser()
        try:
            config.read(config_file)
            credentials.read(credentials_file)
            self.mqtt_host = config.get('mqtt', 'hostname')
            self.mqtt_port = config.getint('mqtt', 'port')
            self.mqtt_user = credentials.get('mqtt', 'user')
            self.mqtt_pwd = credentials.get('mqtt', 'password')
            self.http_host = config.get('http', 'hostname')
            self.http_port = config.getint('http', 'port')
        except ConfigParser.Error as e:
            LOGGER.error('Error reading configuration files ' + config_file + ' and ' + credentials_file + ':')
            raise e

        logging.basicConfig(filename='position_server.log', level=logging.INFO, format=LOG_FORMAT)
        console = logging.StreamHandler()
        console.setLevel(log_level)
        formatter = logging.Formatter(LOG_FORMAT)
        console.setFormatter(formatter)
        logging.getLogger('').addHandler(console)

    def start_server(self):
        server = HTTPServer((self.http_host, self.http_port), myHandler)
        mi = MqttInterface(self.mqtt_host, self.mqtt_port, self.mqtt_user, self.mqtt_pwd)

        mi.mavlink_message_callback = pos_message.print_message
        mi.satcom_on_message_callback = pos_message.print_message

        mi.start()  # Just let this raise an error if it doesn't start?

        try:
            # Create a web server and define the handler to manage the
            # incoming request
            LOGGER.info('Starting HTTP server on port {0}'.format(self.mqtt_port))
            # Wait forever for incoming http requests
            server.serve_forever()

        except KeyboardInterrupt:
            LOGGER.warning('^C received, shutting down the web server')
            server.socket.close()
            mi.stop()
            # try:
            #     tornado.ioloop.IOLoop.current().start()
            # except KeyboardInterrupt:

                # start the stopping in a separate thread so that is not
                # stopped by the KeyboardInterrupt
                # a = Thread(target=mi.stop())
                # a.start()
                # a.join()
                # b = Thread(target=server.socket.close())
                # b.start()
                # b.join()

pos_message = InvoliPositionMessage()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Start the position server that reads mavlink messages and publishes to JSON for INVOLI')
    parser.add_argument('-pc', '--ps-cfg', default='ps_default.cfg', required=False,
                        help='Position server configuration file (MQTT broker and HTTP server details)')
    parser.add_argument('-cc', '--credentials-cfg', default='credentials.cfg', required=False,
                        help='Credentials configuration file')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output (set logger level to DEBUG, default is WARNING')
    args = parser.parse_args()

    log_level = logging.WARN
    if args.verbose:
        log_level = logging.DEBUG

    pos_server = PositionServer(config_file=args.ps_cfg, credentials_file=args.credentials_cfg, log_level=log_level)
    pos_server.start_server()
