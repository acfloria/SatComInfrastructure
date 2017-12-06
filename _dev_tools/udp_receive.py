#!/usr/bin/env python
import tornado.ioloop
import socket

class UdpInterface():
    def __init__(self, rx_port, tx_port):
        self.sock = None
        self.on_msg_callback = None
        self.rx_port = rx_port
        self.tx_port = tx_port

    def rx_callback(self, fd, events):
        (data, source_ip_port) = self.sock.recvfrom(4096)
        self.on_msg_callback(data)

    def send(self, data):
        self.sock.sendto(data, ('localhost', self.tx_port))

    def open(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        tornado.ioloop.IOLoop.current().add_handler(self.sock.fileno(), self.rx_callback, tornado.ioloop.IOLoop.READ)
        self.sock.bind(('localhost', self.rx_port))

    def close(self):
        tornado.ioloop.IOLoop.current().remove_handler(self.sock.fileno())
        self.sock.close()
        self.sock = None

def printuj(s):
    print s

udp = UdpInterface(10001, 0)
udp.open()
udp.on_msg_callback = printuj

try:
    tornado.ioloop.IOLoop.current().start()
except KeyboardInterrupt:
    print 'exit'
    udp.close()
    tornado.ioloop.IOLoop.current().stop()