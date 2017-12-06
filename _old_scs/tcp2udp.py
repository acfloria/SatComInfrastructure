#!/usr/bin/env python
from twisted.protocols.basic import LineReceiver
from twisted.internet.protocol import DatagramProtocol
from twisted.internet.endpoints import TCP4ClientEndpoint, connectProtocol
from twisted.internet import reactor

import sys

class Tcp2Udp():
	def __init__(self, ip):
		self.qgcUdp = QgcProtocol(self.fromQgc)
		reactor.listenUDP(1112, self.qgcUdp)

		relayTcpEndpoint = TCP4ClientEndpoint(reactor, ip, 34568)
		self.relayTcp = RelayProtocol(self.fromRelay)
		connectProtocol(relayTcpEndpoint, self.relayTcp)



	def fromRelay(self, data):
		print 'got data from relay'
		self.qgcUdp.send(data)


	def fromQgc(self, data):
		print 'sending data to relay'
		self.relayTcp.transport.write(data)



class RelayProtocol(LineReceiver):
	def __init__(self, msgRcvCallback):
		self.setRawMode()
		self.msgCallback = msgRcvCallback


	def connectionMade(self):
		print 'connected to relay'


	def connectionLost(self, reason):
		print 'connection lost!'
		print reason.getErrorMessage()


	def dataReceived(self, data):
		self.msgCallback(data)



class QgcProtocol(DatagramProtocol):
	def __init__(self, msgRcvCallback):
		self.msgCallback = msgRcvCallback


	def datagramReceived(self, datagram, addr):
		self.msgCallback(datagram)


	def send(self, data):
		self.transport.write(data, ('127.0.0.1', 1111))



if __name__ == '__main__':
	if len(sys.argv) > 1 and sys.argv[1] == 'r':
		t2d = Tcp2Udp('37.128.61.64')
	else:
		t2d = Tcp2Udp('127.0.0.1')

	reactor.run()