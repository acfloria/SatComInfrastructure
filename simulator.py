#!/usr/bin/env python

import tornado.web
import tornado.ioloop
import tornado.httpclient
import tornado.httputil
import serial
from enum import Enum
from pymavlink import mavlink
import ConfigParser
import time
import random

ideal_sim = True
fraction_good_signal = 0.25

MAV = mavlink.MAVLink(0)


def printmsg(direction, data):
    m = None
    try:
        m = MAV.parse_buffer(data)
    except:
        pass
    if m is not None:
        for msg in m:
            print 'MAV MSG %3d %s' % (msg.get_msgId(), msg.get_type())
            if (msg.get_msgId() == 76):
                print msg


class IridiumInterface:
    def __init__(self, relay_url, local_port):
        self.http_server = None
        self.http_client = tornado.httpclient.AsyncHTTPClient()
        self.url = relay_url
        self.port = local_port
        self.on_message_callback = None

    class PostHandler(tornado.web.RequestHandler):
        def initialize(self, cb):
            self.on_msg_callback = cb

        @tornado.web.asynchronous
        def post(self):
            # print 'Received MT message from Iridium'
            try:
                msg = self.request.arguments['data'][0].decode('hex')
            except:
                print 'Failed to decode the MT message'
                self.set_status(400)
            else:
                self.on_msg_callback(msg)
            self.finish()

    def post_message(self, data):
        # print 'Sending MO messsage to relay'
        data_hex = {'data': data.encode('hex')}
        body = tornado.httputil.urlencode(data_hex)
        request = tornado.httpclient.HTTPRequest(self.url, method='POST', body=body)
        self.http_client.fetch(request, self.on_message_sent)

    def on_message_sent(self, response):
        if response.error:
            print 'Error sending MO message: %s' % response.error

    def start(self):
        args = dict(cb=self.on_message_callback)
        self.http_server = tornado.web.Application([(r"/", self.PostHandler, args)])
        self.http_server.listen(self.port)


class SerialInterface:
    def __init__(self, port, baud):
        self.port = port
        self.baud = baud
        self.serial = None
        self.on_receive_callback = None

    def on_receive(self, fd, events):
        try:
            data = self.serial.read(4096)
        except:
            print 'Failed to read from serial. Device disconnected?'
            self.close()
            tornado.ioloop.IOLoop.current().call_later(1, self.open)
        else:
            self.on_receive_callback(data)

    def send(self, data):
        self.serial.write(data)

    def open(self):
        print 'Opening serial port %s @ %d...' % (self.port, self.baud)
        try:
            self.serial = serial.Serial(port=self.port, baudrate=self.baud)
            self.serial.timeout = 0
            tornado.ioloop.IOLoop.current().add_handler(self.serial.fileno(), self.on_receive, tornado.ioloop.IOLoop.READ)
        except:
            print 'Cannot open port, retrying...'
            tornado.ioloop.IOLoop.current().call_later(1, self.open)
        else:
            print 'Port opened'

    def close(self):
        print 'Closing serial port'
        tornado.ioloop.IOLoop.current().remove_handler(self.serial.fileno())
        self.serial.close()
        self.serial = None


class ATstate(Enum):
    idle = 0
    command = 1
    writing_mo = 2
    session = 3


class IridiumSimulator:
    def __init__(self, iridium_url, iridium_local_port, serial_port, serial_baudrate):
        self.webInterface = IridiumInterface(iridium_url, iridium_local_port)
        self.webInterface.on_message_callback = self.on_web_receive
        self.webInterface.start()
        self.serialInterface = SerialInterface(serial_port, serial_baudrate)
        self.serialInterface.on_receive_callback = self.on_serial_receive
        self.serialInterface.open()

        self.command_buffer = ''
        self.mt_buffer = ''
        self.mo_buffer = ''
        self.mo_length = 0
        self.ring_pending = False
        self.ring_timeout_handle = None
        self.ring_message_pending = False
        self.mt_queue = []
        self.state = ATstate.idle

    def on_web_receive(self, data):
        printmsg('<--', data)
        self.mt_queue.append(data)
        self.ring_on()

    def on_serial_receive(self, data):
        for c in data:
            if self.state == ATstate.writing_mo:
                self.mo_buffer += c
                if len(self.mo_buffer) == self.mo_length+2:
                    cs = 0
                    for x in self.mo_buffer[:-2]:
                        cs += ord(x)
                    if cs/256 == ord(self.mo_buffer[-2]) and cs%256 == ord(self.mo_buffer[-1]):
                        self.mo_buffer = self.mo_buffer[:-2]
                        self.sendSerial('0')
                        self.sendOK()
                    else:
                        self.sendSerial('2')
                        self.sendOK()
                        print 'CHECKSUM ERROR!'
                        print 'len', len(self.mo_buffer)
                        # tornado.ioloop.IOLoop.current().stop()
                    self.changeState(ATstate.idle)
            else:
                if c == '\r':
                    self.on_command(self.command_buffer)
                    self.command_buffer = ''
                else:
                    self.command_buffer += c

    def ring_on(self):
        self.ring_pending = True
        self.ring()

    def ring_off(self):
        self.ring_pending = False
        if self.ring_timeout_handle is not None:
            tornado.ioloop.IOLoop.current().remove_timeout(self.ring_timeout_handle)

    def ring(self):
        self.send_ring()
        if self.ring_timeout_handle is not None:
            tornado.ioloop.IOLoop.current().remove_timeout(self.ring_timeout_handle)
        self.ring_timeout_handle = tornado.ioloop.IOLoop.current().call_later(1, self.ring)

    def send_ring(self):
        self.ring_message_pending = True
        if self.state != ATstate.idle:
            return
        self.sendSerial('SBDRING')
        self.ring_message_pending = False

    def at_csq(self):
        if ideal_sim:
            self.sendSerial('+CSQ:5')
        else:
            time.sleep(4)
            if (random.random() < fraction_good_signal):
                self.sendSerial('+CSQ:5')
            else:
                self.sendSerial('+CSQ:0')

        self.sendOK()

    def at_sbdd0(self):
        #self.mt_buffer = ''
        self.mo_buffer = ''
        self.sendSerial('0')
        self.sendOK()

    def at_sbdix(self):
        if self.mo_buffer:
            printmsg('-->', self.mo_buffer)
            self.webInterface.post_message(self.mo_buffer)
        if self.mt_queue:
            self.mt_buffer = self.mt_queue.pop(0)
        else:
            self.mt_buffer = ''

        if not ideal_sim:
            time.sleep(20)

        self.sendSerial('+SBDIX:0,0,{0},0,{1},{2}'.format(1 if self.mt_buffer else 0, len(self.mt_buffer), len(self.mt_queue)))
        self.sendOK()

    def at_sbdixa(self):
        self.ring_off()
        self.at_sbdix()

    def at_sbdwb(self, length):
        try:
            self.mo_length = int(length)
        except:
            print 'SBDWB FAIL'
            self.sendSerial('3')
        else:
            self.mo_buffer = ''
            self.changeState(ATstate.writing_mo)
            self.sendSerial('READY')

    def at_sbdrb(self):
        msg = ''
        msg += chr(len(self.mt_buffer) / 256)
        msg += chr(len(self.mt_buffer) % 256)
        cs = 0
        for x in self.mt_buffer:
            msg += x
            cs += ord(x)
        msg += chr(cs / 256)
        msg += chr(cs % 256)
        msg += '\r\n'
        self.serialInterface.send(msg)
        self.sendOK()

    def on_command(self, command):
        # print '> ' + command
        self.changeState(ATstate.command)
        if command == 'AT':
            self.sendOK()
        if command == 'AT&K0':
            self.sendOK()
        elif command == 'ATE0':
            self.sendOK()
        elif command == 'AT+CSQ':
            self.at_csq()
        elif command == 'AT+SBDD0':
            self.at_sbdd0()
        elif command == 'AT+SBDIX':
            self.at_sbdix()
        elif command == 'AT+SBDIXA':
            self.at_sbdixa()
        elif command[:9] == 'AT+SBDWB=':
            self.at_sbdwb(command[9:])
        elif command == 'AT+SBDRB':
            self.at_sbdrb()
        else:
            self.changeState(ATstate.idle)

    def sendSerial(self, data):
        self.serialInterface.send(data + '\r\n')

    def sendOK(self):
        self.serialInterface.send('OK\r\n')
        self.changeState(ATstate.idle)

    def changeState(self, new_state):
        self.state = new_state
        if new_state == ATstate.idle:
            if self.ring_message_pending:
                self.send_ring()


def main():
    config_file = 'simulator.cfg'
    config = ConfigParser.RawConfigParser()
    try:
        config.read(config_file)
        iridium_url = config.get('iridium', 'url')
        iridium_local_port = config.getint('iridium', 'local_port')
        serial_port = config.get('serial', 'port')
        serial_baudrate = config.getint('serial', 'baudrate')
    except ConfigParser.Error as e:
        print 'Error reading configuration file %s:' % config_file
        print e
        quit()

    IridiumSimulator(iridium_url, iridium_local_port, serial_port, serial_baudrate)

    try:
        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt:
        tornado.ioloop.IOLoop.current().stop()

if __name__ == '__main__':
    main()
