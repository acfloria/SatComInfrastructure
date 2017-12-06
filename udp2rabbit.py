#!/usr/bin/env python

import pika
import pika.adapters
import tornado.web
import tornado.ioloop
import tornado.httpclient
import tornado.httputil
import logging
import socket
import ConfigParser


LOG_FORMAT = '%(levelname) -10s %(asctime)s %(name) -30s %(funcName) -35s %(lineno) -5d: %(message)s'
LOGGER = logging.getLogger(__name__)


class UdpInterface():
    def __init__(self, rx_port, tx_port):
        self.sock = None
        self.on_message_callback = None
        self.rx_port = rx_port
        self.tx_port = tx_port

    def on_receive(self, fd, events):
        LOGGER.info('Received data on UDP')
        (data, source_ip_port) = self.sock.recvfrom(4096)
        self.on_message_callback(data)

    def send(self, data):
        LOGGER.info('Sending data on UDP')
        self.sock.sendto(data, ('localhost', self.tx_port))

    def open(self):
        LOGGER.info('Opening UDP port %d', self.rx_port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        tornado.ioloop.IOLoop.current().add_handler(self.sock.fileno(), self.on_receive, tornado.ioloop.IOLoop.READ)
        self.sock.bind(('localhost', self.rx_port))

    def close(self):
        LOGGER.info('Closing UDP port')
        tornado.ioloop.IOLoop.current().remove_handler(self.sock.fileno())
        self.sock.close()
        self.sock = None


class RabbitInterface(object):
    def __init__(self, ip, port, user, pwd):
        self.broker_ip = ip
        self.broker_port = port
        self.broker_user = user
        self.broker_pwd = pwd
        self.connection = None
        self.channel = None
        self.closing = False
        self.consumer_tag = None
        self.publish_counter = 1
        self.waiting_for_confirm = []
        self.on_message_callback = None
        self.tx_queue = 'MT'
        self.rx_queue = 'MO'

    def connect(self):
        creds = pika.PlainCredentials(self.broker_user, self.broker_pwd)
        params = pika.ConnectionParameters(host=self.broker_ip, port=self.broker_port, credentials=creds, heartbeat_interval=3)
        pika.adapters.TornadoConnection(params, self.on_connection_open, self.on_connection_fail)

    def close_connection(self):
        LOGGER.info('Closing connection')
        self.connection.close()

    def on_connection_open(self, connection):
        LOGGER.info('Connection opened')
        self.connection = connection
        self.connection.add_on_close_callback(self.on_connection_closed)
        self.open_channel()

    def on_connection_fail(self, connection, message):
        connection.add_timeout(3, self.connect)
        LOGGER.info('Retrying in 3 seconds')

    def on_connection_closed(self, connection, reply_code, reply_text):
        self.channel = None
        if not self.closing:
            LOGGER.warning('Connection lost, reopening in 3 seconds: (%s) %s', reply_code, reply_text)
            self.connection.add_timeout(3, self.connect)

    def open_channel(self):
        LOGGER.info('Opening the channel')
        self.connection.channel(on_open_callback=self.on_channel_open)

    def close_channel(self):
        LOGGER.info('Closing the channel')
        self.channel.close()

    def on_channel_open(self, channel):
        LOGGER.info('Channel opened')
        self.channel = channel
        self.channel.add_on_close_callback(self.on_channel_closed)
        self.channel.confirm_delivery(self.on_delivery_confirmation)
        self.set_qos()

    def on_channel_closed(self, channel, reply_code, reply_text):
        LOGGER.warning('Channel %i was closed: (%s) %s', channel, reply_code, reply_text)
        self.connection.close()

    def set_qos(self):
        LOGGER.info('Setting prefetch to 1')
        self.channel.basic_qos(self.on_qos_set, prefetch_count=1)

    def on_qos_set(self, unused):
        LOGGER.info('QoS set')
        self.start_consuming()

    def start_consuming(self):
        LOGGER.info('Starting %s consumer', self.rx_queue)
        self.channel.add_on_cancel_callback(self.on_consumer_cancelled)
        self.consumer_tag = self.channel.basic_consume(self.on_message, self.rx_queue)

    def stop_consuming(self):
        if self.channel:
            LOGGER.info('Stopping %s consumer', self.rx_queue)
            self.channel.basic_cancel(self.on_cancel_ok, self.consumer_tag)

    def on_cancel_ok(self, unused_frame):
        LOGGER.info('%s consumer stopped', self.rx_queue)
        self.close_channel()

    def on_consumer_cancelled(self, method_frame):
        LOGGER.info('%s consumer was cancelled remotely, shutting down: %r', self.rx_queue, method_frame)
        if self.channel:
            self.channel.close()

    def on_message(self, unused_channel, basic_deliver, properties, body):
        LOGGER.info('Received message # %s', basic_deliver.delivery_tag)
        self.on_message_callback(body)
        self.ack_message(basic_deliver.delivery_tag)

    def ack_message(self, delivery_tag):
        LOGGER.info('ACKing message # %i', delivery_tag)
        self.channel.basic_ack(delivery_tag)

    def publish_message(self, msg):
        self.channel.basic_publish(exchange=self.tx_queue, routing_key='', body=msg)
        self.waiting_for_confirm.append(self.publish_counter)
        self.publish_counter += 1
        LOGGER.info('Published message # %i', self.publish_counter - 1)

    def on_delivery_confirmation(self, method_frame):
        conf = method_frame.method.NAME.split('.')[1].lower()
        tag = method_frame.method.delivery_tag
        LOGGER.info('Received %s for message # %i', conf, tag)
        self.waiting_for_confirm.remove(tag)

    def redeliver_messages(self):
        tornado.ioloop.IOLoop.current().call_later(0.5, self.channel.basic_recover, requeue=True)

    def start(self):
        self.connect()

    def stop(self):
        LOGGER.info('Stopping')
        self.closing = True
        self.stop_consuming()
        LOGGER.info('Stopped')


def main():
    config_file = 'udp2rabbit.cfg'
    config = ConfigParser.RawConfigParser()
    try:
        config.read(config_file)
        host = config.get('relay', 'hostname')
        port = config.getint('relay', 'port')
        user = config.get('relay', 'user')
        pwd = config.get('relay', 'password')
        rx_port = config.getint('udp', 'qgc_target_port')
        tx_port = config.getint('udp', 'qgc_listening_port')
    except ConfigParser.Error as e:
        print 'Error reading configuration file %s:' % config_file
        print e
        quit()

    logging.basicConfig(filename='udp2rabbit.log', level=logging.INFO, format=LOG_FORMAT)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    formatter = logging.Formatter(LOG_FORMAT)
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)
    ri = RabbitInterface(host, port, user, pwd)
    ui = UdpInterface(rx_port, tx_port)

    ri.on_message_callback = ui.send
    ui.on_message_callback = ri.publish_message

    ri.start()
    ui.open()

    try:
        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt:
        ri.stop()

if __name__ == '__main__':
    main()
