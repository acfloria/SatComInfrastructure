#!/usr/bin/env python

import socket
import sys

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

server_address = ('localhost', 10001)
message = 'TEST MSG'

try:
    print >>sys.stderr, 'sending "%s"' % message
    sent = sock.sendto(message, server_address)
finally:
    sock.close()
