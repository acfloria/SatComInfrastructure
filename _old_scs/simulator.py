#!/usr/bin/env python
from twisted.protocols.basic import LineReceiver
from twisted.internet.serialport import SerialPort
from twisted.internet.endpoints import TCP4ServerEndpoint, TCP4ClientEndpoint, connectProtocol
from twisted.internet import reactor
from pymavlink import mavlink
from enum import Enum
from threading import Thread, Lock
from time import time, sleep
import signal, sys

import iridium, relay



class ParseState(Enum):
	start = 1
	id = 2
	lenh = 3
	lenl = 4
	data = 5



class SatcomMessage:
	def __init__(self):
		self.id = 0
		self.len = 0
		self.data = bytearray()



class PX4UartInterface(LineReceiver):
	def __init__(self, msgRcvCallback):
		self.setRawMode()
		self.parseState = ParseState.start
		self.satcomMsg = SatcomMessage()
		self.msgCallback = msgRcvCallback
		self.mav = mavlink.MAVLink(0)


	def dataReceived(self, data):
		for char in data:
			if self.parseState == ParseState.start:
				if ord(char) == 0xA5:
					self.parseState = ParseState.id
				else:
					self.receiveFailed()

			elif self.parseState == ParseState.id:
				self.satcomMsg.id = ord(char)
				self.parseState = ParseState.lenh

			elif self.parseState == ParseState.lenh:
				self.satcomMsg.len = ord(char) * 256
				self.parseState = ParseState.lenl

			elif self.parseState == ParseState.lenl:
				self.satcomMsg.len += ord(char)
				self.parseState = ParseState.data
				if self.satcomMsg.len == 0:
					self.handleMessage()

			elif self.parseState == ParseState.data:
				self.satcomMsg.data += char
				if len(self.satcomMsg.data) == self.satcomMsg.len:
					self.handleMessage()


	def receiveFailed(self):
		print 'serial: msg parse fail'
		self.parseState = ParseState.start
		self.satcomMsg = SatcomMessage()


	def handleMessage(self):
		self.msgCallback(self.satcomMsg)
		self.parseState = ParseState.start
		self.satcomMsg = SatcomMessage()



class SatcomStatus(Enum):
	idle = 1
	sending = 2
	receiving = 3



class IridiumSimulator(Thread):
	def __init__(self, comPort, moIP, moPort, mtPort, delay):
		Thread.__init__(self)
		self.udpMavlink = mavlink.MAVLink(0)
		self.serialMavlink = mavlink.MAVLink(0)
		self.udpRx = []
		self.serialRx = None
		self.ipLock = Lock()
		self.serialLock = Lock()
		self.ipTransport = None
		self.status = SatcomStatus.idle
		self.serialTime = 0
		self.delay = delay
		self.terminate = False
		# serial interface to PX4
		self.serialInterface = SerialPort(PX4UartInterface(self.receivedPX4), comPort, reactor, baudrate = 115200)
		self.serialInterface.flushInput()
		self.serialInterface.flushOutput()
		# enpoint for sending MO messages from PX to the relay
		self.relayMoEndpoint = TCP4ClientEndpoint(reactor, moIP, moPort)
		# enpoint receiving MT messages coming from the relay
		self.relayMtEndpoint = TCP4ServerEndpoint(reactor, mtPort)
		self.relayMtEndpoint.listen(relay.IridiumMtReceiverFactory(self.receivedRelay))


	def run(self):
		while not self.terminate:
			self.serialLock.acquire()

			if self.serialTime + self.delay <= time():
				if self.status == SatcomStatus.sending:
					self.sendMsgToPX4(0x01, chr(0x00))
					self.ipLock.acquire()
					# prepare and send an iridium message
					try:
						m = self.udpMavlink.decode(self.serialRx[8:])
						if m is not None:
							msgId = m.get_msgId()
							print '<-- PX4 {0} ({1})'.format(mavlink.mavlink_map[msgId].name, msgId)
					except Exception as e:
						print '<-- PX4 ' + str(e)
					moMsgData = self.prepareMoMessage(self.serialRx)
					prot = relay.IridiumMoSender(moMsgData)
					connectProtocol(self.relayMoEndpoint, prot)
					self.ipLock.release()
					#print 'SEND RQ: complete'
					self.status = SatcomStatus.idle

				elif self.status == SatcomStatus.receiving:
					if len(self.udpRx) != 0:
						self.ipLock.acquire()
						msg = self.udpRx.pop(0)

						try:
							m = self.udpMavlink.decode(msg)
						except Exception as e:
							print e
							m = None

						if m is not None:
							msgId = m.get_msgId()
							print 'QGC --> {0} ({1})'.format(mavlink.mavlink_map[msgId].name, msgId)
							self.sendMsgToPX4(0x02, chr(0x00) + msg)
						else:
							self.sendMsgToPX4(0x02, chr(0x2F))  # no msg

						self.ipLock.release()
						#print 'RCV RQ: complete'
					else:
						self.sendMsgToPX4(0x02, chr(0x2F))  # no msg
						#print 'RCV RQ: no msg'

					self.status = SatcomStatus.idle

			self.serialLock.release()

			sleep(0.1)


	def receivedPX4(self, msg):
		# send msg
		if msg.id == 0x01:
			self.satcomSendRequest(msg.data)

		# retrieve msg
		if msg.id == 0x02:
			self.satcomReceiveRequest()

		# check network status
		if msg.id == 0x05:
			self.satcomGetNetworkStatus()

		# check signal strength
		if msg.id == 0x06:
			self.satcomGetSignalStrength()


	def receivedRelay(self, msg):
		# print 'MT MSG CALLBACK'
		for ie in msg.ieList:
			# print 'IE: {0}: {1}'.format(ie.id, ie.name)
			if ie.name == 'MT Payload IE':
				# print ie.payload
				try:
					#m = self.udpMavlink.decode(ie.payload)
					#if m is not None:
						# print 'MT mavlink msg ID {0}'.format(m.get_msgId())
						self.ipLock.acquire()
						self.udpRx.append(ie.payload)
						self.ipLock.release()
				except:
					pass



	def prepareMoMessage(self, mavlinkMsg):
		msg = iridium.IridiumMessage()

		header = iridium.MoHeaderIe()
		header.autoId = 123
		header.imei = bytearray([0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x99, 0xAA, 0xBB, 0xCC, 0xDD, 0xEE])
		header.sessionStatus = iridium.MoHeaderIe.SessionStatus.SUCCESSFUL
		header.momsn = 1
		header.mtmsn = 2
		header.timeOfSession = 100000
		header.prepareRaw()
		msg.ieList.append(header)

		payload = iridium.MoPayloadIe()
		payload.payload = mavlinkMsg
		payload.prepareRaw()
		msg.ieList.append(payload)

		msg.prepareRaw()

		return msg.rawData



	def satcomSendRequest(self, msgData):
		self.serialLock.acquire()

		if self.status == SatcomStatus.idle:
			#print 'SEND RQ: pending'
			self.status = SatcomStatus.sending
			self.serialTime = time()

			scsHeader = bytearray()
			packetLen = len(msgData) + 8
			scsHeader.append(packetLen / 256)
			scsHeader.append(packetLen % 256)
			scsHeader.append(2) # PX4 packet
			scsHeader += bytearray(5) # 5 empty bytes - only used when sending images

			self.serialRx = scsHeader + msgData

		else:
			print 'SEND RQ: busy <<<<<<<<<<<<<<<<<<<<<<<'   # THIS SHOULD NOT HAPPEN - PX4 SATCOM DRIVER SHOULD WAIT FOR PREVIOUS COMMAND REPLY
			self.sendMsgToPX4(0x01, chr(0x01))

		self.serialLock.release()


	def satcomReceiveRequest(self):
		self.serialLock.acquire()

		if self.status == SatcomStatus.idle:
			#print 'RCV RQ: pending'
			self.status = SatcomStatus.receiving
			self.serialTime = time()

		else:
			print 'RCV RQ: busy <<<<<<<<<<<<<<<<<<<<<<<'    # THIS SHOULD NOT HAPPEN - PX4 SATCOM DRIVER SHOULD WAIT FOR PREVIOUS COMMAND REPLY
			self.sendMsgToPX4(0x02, chr(0x01))

		self.serialLock.release()


	def satcomGetNetworkStatus(self):
		self.serialLock.acquire()

		self.sendMsgToPX4(0x05, chr(0x00) + chr(0x01))

		self.serialLock.release()


	def satcomGetSignalStrength(self):
		self.serialLock.acquire()

		self.sendMsgToPX4(0x06, chr(0x00) + chr(0x05))

		self.serialLock.release()


	def sendMsgToPX4(self, id, data):
		msg = [0x5B, 0, 0, 0]
		msg[1] = (id)
		msg[2] = (len(data)/256)
		msg[3] = (len(data)%256)
		msg += data
		data = bytes(bytearray(msg))
		self.serialInterface.write(data)

#simulator = None

def sigint_handler(signal, frame):
	global simulator
	simulator.terminate = True
	reactor.stop()

if __name__ == '__main__':
	global simulator
	simulator = IridiumSimulator('/dev/COM11', 'localhost', 34567, 10800, delay=0.0)
	simulator.start()

	signal.signal(signal.SIGINT, sigint_handler)

	reactor.run()

	print "\ndone\n"
