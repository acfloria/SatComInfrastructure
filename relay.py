#!/usr/bin/env python

import pika
import pika.adapters
import tornado.web
import tornado.ioloop
import tornado.httpclient
import tornado.httputil
import logging
import ConfigParser


LOG_FORMAT = '%(levelname) -10s %(asctime)s %(name) -30s %(funcName) -35s %(lineno) -5d: %(message)s'
LOGGER = logging.getLogger(__name__)


class IridiumInterface:
    def __init__(self, iridium_url, local_port, rock7_credentials):
        self.rabbit_interface = None
        self.http_server = None
        self.http_client = tornado.httpclient.AsyncHTTPClient()
        self.url = iridium_url
        self.port = local_port
        self.waiting_for_confirm = {}
        self.post_data = rock7_credentials

    class PostHandler(tornado.web.RequestHandler):
        def initialize(self, cb):
            self.on_msg_callback = cb

        @tornado.web.asynchronous
        def post(self):
            LOGGER.info('Received MO message from Iridium')
            try:
                msg = self.request.arguments['data'][0].decode('hex')
            except:
                LOGGER.warning('Failed to decode the MO message')
                self.set_status(400)
                self.finish()
            else:
                self.on_msg_callback(msg, self)

    def post_message(self, delivery_tag, data):
        LOGGER.info('Sending MT message # %i to Iridium', delivery_tag)
        self.post_data['data'] = data.encode('hex')
        body = tornado.httputil.urlencode(self.post_data)
        request = tornado.httpclient.HTTPRequest(self.url, method='POST', body=body)
        self.waiting_for_confirm[request] = delivery_tag
        self.http_client.fetch(request, self.on_message_sent)

    def on_message_sent(self, response):
        if response.error:
            LOGGER.warning('Error sending: %s', response.error)
            self.waiting_for_confirm.pop(response.request)
            self.rabbit_interface.redeliver_messages()
        else:
            delivery_tag = self.waiting_for_confirm.pop(response.request)
            self.rabbit_interface.ack_message(delivery_tag)

    def start(self):
        args = dict(cb=self.rabbit_interface.publish_message)
        self.http_server = tornado.web.Application([(r"/", self.PostHandler, args)])
        self.http_server.listen(self.port)


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
        self.waiting_for_confirm = {}
        self.iridium_interface = None
        self.tx_queue = 'MO'
        self.rx_queue = 'MT'

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
        self.iridium_interface.post_message(basic_deliver.delivery_tag, body)

    def ack_message(self, delivery_tag):
        LOGGER.info('ACKing MT message # %i', delivery_tag)
        self.channel.basic_ack(delivery_tag)

    def publish_message(self, msg, request):
        self.channel.basic_publish(exchange=self.tx_queue, routing_key='', body=msg)
        self.waiting_for_confirm[self.publish_counter] = request
        self.publish_counter += 1
        LOGGER.info('Published message # %i', self.publish_counter - 1)

    def on_delivery_confirmation(self, method_frame):
        conf = method_frame.method.NAME.split('.')[1].lower()
        tag = method_frame.method.delivery_tag
        LOGGER.info('Received %s for message # %i', conf, tag)
        request = self.waiting_for_confirm.pop(tag)
        if conf == 'nack':
            request.set_status(400)
        request.finish()

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
    config_file = 'relay.cfg'
    config = ConfigParser.RawConfigParser()
    rock7_credentials = {}
    try:
        config.read(config_file)
        host = config.get('rabbitmq', 'hostname')
        port = config.getint('rabbitmq', 'port')
        user = config.get('rabbitmq', 'user')
        pwd = config.get('rabbitmq', 'password')
        iridium_url = config.get('iridium', 'url')
        iridium_local_port = config.getint('iridium', 'local_port')
        rock7_credentials['imei'] = config.get('iridium', 'imei')
        rock7_credentials['username'] = config.get('iridium', 'username')
        rock7_credentials['password'] = config.get('iridium', 'password')
    except ConfigParser.Error as e:
        print 'Error reading configuration file %s:' % config_file
        print e
        quit()

    logging.basicConfig(filename='relay.log', level=logging.INFO, format=LOG_FORMAT)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    formatter = logging.Formatter(LOG_FORMAT)
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)

    ri = RabbitInterface(host, port, user, pwd)
    ii = IridiumInterface(iridium_url, iridium_local_port, rock7_credentials)

    ri.iridium_interface = ii
    ii.rabbit_interface = ri

    ri.start()
    ii.start()

    try:
        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt:
        ri.stop()

if __name__ == '__main__':
    main()
