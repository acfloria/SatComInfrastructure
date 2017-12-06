#!/usr/bin/env python
from twisted.protocols.basic import LineReceiver
from twisted.internet.protocol import Protocol, Factory, DatagramProtocol
from twisted.internet.endpoints import TCP4ClientEndpoint, TCP4ServerEndpoint, connectProtocol
from twisted.internet import reactor
from pymavlink import mavlink
import iridium


class IridiumRelay:
	def __init__(self):
		# endpoint sending MT messages to the Iridium gateway
		self.mtIridiumEndpoint = TCP4ClientEndpoint(reactor, 'localhost', 10800)

		# enpoint receiving MO messages coming from the Iridium network
		iridiumServerEndpoint = TCP4ServerEndpoint(reactor, 34567)
		iridiumServerEndpoint.listen(IridiumMoReceiverFactory(self.moMsgCallback))

		# interface to QGC
		#self.qgcInterface = reactor.listenUDP(0, QgcUdpProtocol(self.mtMsgCallback))
		qgcInterfaceEndpoint = TCP4ServerEndpoint(reactor, 34568)
		self.qgcInterface = QgcTcpFactory(self.mtMsgCallback)
		qgcInterfaceEndpoint.listen(self.qgcInterface)

		self.mav = mavlink.MAVLink(0)


	def moMsgCallback(self, msg):
		print '\nMO MSG'
		for ie in msg.ieList:
			print 'MO MSG: IE: {0}: {1}'.format(ie.id, ie.name)
			if ie.name == 'MO Payload IE':
				if ie.payload[2] == 0x01:
					print 'MO MSG: image packet'

				elif ie.payload[2] == 0x02:
					print 'MO MSG: data packet'
					data = bytes(ie.payload[8:])
					m = None
					try:
						m = self.mav.decode(data)
					except Exception as e:
						print 'MO MSG: error decoding packet as mavlink msg'
						print 'MO MSG: {0}'.format(e)
					if m is not None:
						print 'MO MSG: mavlink msg ID {0}'.format(m.get_msgId())
					self.qgcInterface.write(bytes(ie.payload))

				else:
					print 'MO MSG: unknown packet'


	def mtMsgCallback(self, data):
		# print 'MT MSG CALLBACK'
		# m = self.mav.decode(bytes(data))
		# if m != None:
		# 	print '>>> MT mavlink msg ID {0}'.format(m.get_msgId())
		mtMsgData = self.prepareMtMessage(data)
		prot = IridiumMtSender(mtMsgData)
		connectProtocol(self.mtIridiumEndpoint, prot)


	def prepareMtMessage(self, mavlinkMsg):
		msg = iridium.IridiumMessage()

		header = iridium.MtHeaderIe()
		header.msgId = 1234
		header.imei = bytearray([0x33, 0x30, 0x30, 0x32, 0x33, 0x34, 0x30, 0x36, 0x30, 0x33, 0x39, 0x32, 0x36, 0x33, 0x30])
		header.prepareRaw()
		msg.ieList.append(header)

		payload = iridium.MtPayloadIe()
		payload.payload = mavlinkMsg
		payload.prepareRaw()
		msg.ieList.append(payload)

		msg.prepareRaw()

		return msg.rawData



class IridiumMoSender(Protocol):
	def __init__(self, msg):
		self.msg = bytes(msg)


	def connectionMade(self):
		# print 'MoSender: connected'
		self.sendMessage()
		self.transport.loseConnection()


	def sendMessage(self):
		# print 'MoSender: sending MO data'
		self.transport.write(bytes(self.msg))



class IridiumMoReceiver(Protocol):
	def __init__(self, msgRcvCallback):
		self.msgCallback = msgRcvCallback
		self.rxMsg = iridium.IridiumMessage()
		self.rxData = bytearray()


	def connectionMade(self):
		# print 'MoReceiver: connected'
		self.rxMsg = iridium.IridiumMessage()
		self.rxData = bytearray()
		pass


	def connectionLost(self, reason):
		# print 'MoReceiver: connection closed ({0})'.format(reason.getErrorMessage())

		msgDecoded = False

		for byte in self.rxData:
			b = chr(byte)
			try:
				msgDecoded = self.rxMsg.parseByte(b)
			except Exception as e:
				print 'MoReceiver: addByte fail:'
				print e
				self.rxMsg = iridium.IridiumMessage()
			if msgDecoded:
				# print 'MoReceiver: msg parsed'
				self.msgCallback(self.rxMsg)
				break


	def dataReceived(self, data):
		# print 'MoReceiver: data received'
		self.rxData += bytes(data)



class IridiumMoReceiverFactory(Factory):
	def __init__(self, msgRcvCallback):
		self.msgCallback = msgRcvCallback


	def buildProtocol(self, addr):
		return IridiumMoReceiver(self.msgCallback)



class IridiumMtSender(Protocol):
	def __init__(self, msg):
		self.msg = msg
		self.rxData = bytearray()


	def connectionMade(self):
		print 'MtSender: connected'
		self.rxData = bytearray()
		self.sendMessage()


	def connectionLost(self, reason):
		print 'MtSender: connection closed ({0})'.format(reason.getErrorMessage())
		print self.rxData
		for b in self.rxData:
			print hex(b)


	def sendMessage(self):
		print 'MtSender: sending MT data'
		self.transport.write(bytes(self.msg))


	def dataReceived(self, data):
		print 'MtSender: data received'
		self.rxData += bytes(data)



class IridiumMtReceiver(Protocol):
	def __init__(self, msgRcvCallback):
		self.rxMsg = iridium.IridiumMessage()
		self.msgCallback = msgRcvCallback


	def connectionMade(self):
		self.rxMsg = iridium.IridiumMessage()
		# print 'MtReceiver: connected'
		pass


	def connectionLost(self, reason):
		# print 'MtReceiver: connection closed ({0})'.format(reason.getErrorMessage())
		pass


	def dataReceived(self, data):
		# print 'MtReceiver: got data'
		msgDecoded = False
		for byte in data:
			try:
				msgDecoded = self.rxMsg.parseByte(byte)
			except Exception as e:
				print 'MtReceiver: addByte fail:'
				print e
			if msgDecoded:
				# print 'MtReceiver: msg parsed'
				self.msgCallback(self.rxMsg)
				break

		# send confirmation
		self.transport.loseConnection()



class IridiumMtReceiverFactory(Factory):
	def __init__(self, msgRcvCallback):
		self.msgCallback = msgRcvCallback


	def buildProtocol(self, addr):
		return IridiumMtReceiver(self.msgCallback)



class QgcTcpProtocol(LineReceiver):
	def __init__(self, msgRcvCallback, factory):
		self.setRawMode()
		self.msgCallback = msgRcvCallback
		self.factory = factory

	def connectionMade(self):
		print 'QCG TCP: connected'
		self.factory.prot = self


	def connectionLost(self, reason):
		print 'QGC TCP: disconnected'
		self.factory.port = None


	def dataReceived(self, data):
		print 'QGC TCP: got data'
		self.msgCallback(data)


	def write(self, data):
		print 'QGC TCP: sending data'
		self.transport.write(data)



class QgcTcpFactory(Factory):
	def __init__(self, msgRcvCallback):
		self.msgCallback = msgRcvCallback
		self.prot = None


	def buildProtocol(self, addr):
		proto = QgcTcpProtocol(self.msgCallback, self)
		return proto


	def write(self, data):
		try:
			self.prot.write(bytes(data))
		except:
			pass


class QgcUdpProtocol(DatagramProtocol):
	def __init__(self, msgRcvCallback):
		self.msgCallback = msgRcvCallback


	def startProtocol(self):
		host = '127.0.0.1'
		port = 5760
		self.transport.connect(host, port)


	def datagramReceived(self, datagram, addr):
		self.msgCallback(datagram)


if __name__ == '__main__':
	iridiumRelay = IridiumRelay()

	reactor.run()