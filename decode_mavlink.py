#!/usr/bin/env python

import tornado.web
import tornado.ioloop
import tornado.httpclient
import tornado.httputil
import serial
from enum import Enum
from pymavlink import mavlink
import ConfigParser


MAV = mavlink.MAVLink(0)


def printmsg(data):
    m = None
    try:
        m = MAV.parse_buffer(data)
    except:
        pass
    if m is not None:
        for msg in m:
            print 'MAV MSG %3d %s' % (msg.get_msgId(), msg.get_type())
            print msg

def main():
    message = 'fe030363014d280a033fe8fe2a046301ebe3a1030086952c19fde833ce0403050100000000ffff0001160c7f000000000100000d138003648080803207'
    printmsg(message.decode('hex'))

if __name__ == '__main__':
    main()
