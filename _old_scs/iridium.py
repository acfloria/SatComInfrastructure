from enum import Enum
import struct


class IridiumMessage:
    def __init__(self):
        self.protRevNumber = 0
        self.length = 0
        self.rawData = bytearray()
        self.receiveIdx = 0
        self.parsingIdx = 3
        self.ieList = []

    def parseByte(self, byte):
        self.rawData += byte
        self.receiveIdx += 1

        if self.receiveIdx == 1:
            self.protRevNumber = ord(byte)
            if self.protRevNumber != 1:
                raise Exception('IridiumMessage.addByte fail: protocol rev number != 1 ({0})'.format(hex(ord(byte))))

        elif self.receiveIdx == 3:
            self.length = struct.unpack('>H', bytes(self.rawData[1:3]))[0] + 3

        elif self.length != 0 and self.receiveIdx == self.length:
            self.parseIEs()
            return True

        return False

    def parseIEs(self):
        while self.parsingIdx < self.length:
            ie = self.parseNextIe()
            self.ieList.append(ie)

    def parseNextIe(self):
        pi = self.parsingIdx

        ieId = self.rawData[pi]
        pi += 1

        ieLen = struct.unpack('>H', bytes(self.rawData[pi:pi + 2]))[0]
        pi += 2
        if ieLen > self.length - pi:
            raise Exception(
                'IridiumMessage.parseNextIe fail: IE length bigger then remaining data count ({0} > {1})'.format(ieLen, self.length - pi))

        ieData = self.rawData[pi - 3:pi + ieLen]
        pi += ieLen

        if ieId == 0x01:
            ie = MoHeaderIe()
        elif ieId == 0x02:
            ie = MoPayloadIe()
        elif ieId == 0x03:
            ie = MoLocationIe()
        elif ieId == 0x05:
            ie = MoConfirmationIe()
        elif ieId == 0x41:
            ie = MtHeaderIe()
        elif ieId == 0x42:
            ie = MtPayloadIe()
        elif ieId == 0x44:
            ie = MtConfirmationIe()
        elif ieId == 0x46:
            ie = MtPriorityIe()
        else:
            raise Exception('IridiumMessage.parseNextIe fail: unknown IE ID ({0})'.format(id))

        if not ie.parse(ieData):
            raise Exception('IridiumMessage.parseNextIe fail: parse fail')

        self.parsingIdx = pi
        return ie

    def prepareRaw(self):
        totalLen = 0
        for ie in self.ieList:
            ie.prepareRaw()
            totalLen += ie.length
        totalLen += 3

        self.rawData = bytearray(totalLen)
        self.rawData[0] = 1
        self.rawData[1:3] = struct.pack('>H', totalLen - 3)
        index = 3
        for ie in self.ieList:
            self.rawData[index:index+ie.length] = ie.rawData
            index += ie.length


class InformationElement:
    def __init__(self):
        self.id = 0
        self.length = 0
        self.rawData = bytearray()


class MoHeaderIe(InformationElement):
    class SessionStatus(Enum):
        # tab. 6-5, p. 24
        SUCCESSFUL = 0
        MT_TO_BIG = 1
        LOW_QUALITY = 2
        SESSION_TIMEOUT = 10
        MO_TO_BIG = 12
        RF_LINK_LOSS = 13
        PROTOCOL_ERR = 14
        IMEI_PROHIBITED = 15

    def __init__(self):
        InformationElement.__init__(self)
        self.name = 'MO Header IE'
        self.id = 0x01
        self.autoId = 0
        self.imei = 0
        self.sessionStatus = MoHeaderIe.SessionStatus
        self.momsn = 0
        self.mtmsn = 0
        self.timeOfSession = 0

    def parse(self, rawData):
        self.rawData = rawData

        try:
            if self.id != rawData[0]:
                raise Exception('ID should be 0x{0:x} and is 0x{1:x}'.format(self.id, rawData[0]))

            self.length = struct.unpack('>H', bytes(rawData[1:3]))[0] + 3
            if self.length != 31:
                raise Exception('stated length should be {0} and is {1}'.format(31, self.length))

            if len(rawData) != self.length:
                raise Exception('actual length should be {0} and is {1}'.format(self.length, len(rawData)))

            self.autoId = struct.unpack('>I', bytes(rawData[3:7]))[0]
            self.imei = rawData[7:22]
            self.sessionStatus = MoHeaderIe.SessionStatus(rawData[22])
            self.momsn = struct.unpack('>H', bytes(rawData[23:25]))[0]
            self.mtmsn = struct.unpack('>H', bytes(rawData[25:27]))[0]
            self.timeOfSession = struct.unpack('>I', bytes(rawData[27:31]))[0]
            return True

        except Exception as e:
            print 'MoHeaderIe parse fail:'
            print e
            return False

    def prepareRaw(self):
        self.length = 31
        self.rawData = bytearray(self.length)
        d = self.rawData

        d[0] = self.id
        d[1:3] = struct.pack('>H', self.length - 3)
        d[3:7] = struct.pack('>I', self.autoId)
        d[7:22] = self.imei
        d[22] = self.sessionStatus.value
        d[23:25] = struct.pack('>H', self.momsn)
        d[25:27] = struct.pack('>H', self.mtmsn)
        d[27:31] = struct.pack('>I', self.timeOfSession)


class MoPayloadIe(InformationElement):
    def __init__(self):
        InformationElement.__init__(self)
        self.name = 'MO Payload IE'
        self.id = 0x02
        self.payload = bytearray()

    def parse(self, rawData):
        self.rawData = rawData

        try:
            if self.id != rawData[0]:
                raise Exception('ID should be 0x{0:x} and is 0x{1:h}'.format(self.id, rawData[0]))

            self.length = struct.unpack('>H', bytes(rawData[1:3]))[0] + 3

            if len(rawData) != self.length:
                raise Exception('actual length should be {0} and is {1}'.format(self.length, len(rawData)))

            self.payload = rawData[3:]
            return True

        except Exception as e:
            print 'MoPayloadIe parse fail:'
            print e
            return False

    def prepareRaw(self):
        self.length = len(self.payload) + 3
        self.rawData = bytearray(self.length)
        d = self.rawData

        d[0] = self.id
        d[1:3] = struct.pack('>H', self.length - 3)
        d[3:] = self.payload


class MoLocationIe(InformationElement):
    def __init__(self):
        InformationElement.__init__(self)
        self.name = 'MO Location IE'
        self.id = 0x03
        self.latitude = 0
        self.longitude = 0
        self.cep = 0

    def parse(self, rawData):
        self.rawData = rawData

        try:
            if self.id != rawData[0]:
                raise Exception('ID should be 0x{0:x} and is 0x{1:h}'.format(self.id, rawData[0]))

            self.length = struct.unpack('>H', bytes(rawData[1:3]))[0] + 3
            if self.length != 14:
                raise Exception('stated length should be {0} and is {1}'.format(14, self.length))

            if len(rawData) != self.length:
                raise Exception('actual length should be {0} and is {1}'.format(self.length, len(rawData)))

            latSign = (rawData[3] & 2) - 1
            latDeg = float(rawData[4])
            latMin = float(struct.unpack('>H', bytes(rawData[5:7]))[0]) / 1000
            self.latitude = latSign * (latDeg + latMin / 60)

            longSign = (rawData[3] & 1) * 2 - 1
            longDeg = float(rawData[7])
            longMin = float(struct.unpack('>H', bytes(rawData[8:10]))[0]) / 1000
            self.longitude = longSign * (longDeg + longMin / 60)

            self.cep = struct.unpack('>I', bytes(rawData[10:14]))[0]
            return True

        except Exception as e:
            print 'MoLocationIe parse fail:'
            print e
            return False

    def prepareRaw(self):
        raise NotImplementedError


class MoConfirmationIe(InformationElement):
    class ConfirmationStatus(Enum):
        FAILURE = 0
        SUCCESS = 1

    def __init__(self):
        InformationElement.__init__(self)
        self.name = 'MO Confirmation IE'
        self.id = 0x05
        self.confirmationStatus = 0

    def parse(self, rawData):
        self.rawData = rawData

        try:
            if self.id != rawData[0]:
                raise Exception('ID should be 0x{0:x} and is 0x{1:h}'.format(self.id, rawData[0]))

            self.length = struct.unpack('>H', bytes(rawData[1:3]))[0] + 3
            if self.length != 4:
                raise Exception('stated length should be {0} and is {1}'.format(4, self.length))

            if len(rawData) != self.length:
                raise Exception('actual length should be {0} and is {1}'.format(self.length, len(rawData)))

            self.confirmationStatus = MoConfirmationIe.ConfirmationStatus(rawData[3])
            return True

        except Exception as e:
            print 'MoConfirmationIe parse fail:'
            print e
            return False

    def prepareRaw(self):
        raise NotImplementedError


class MtHeaderIe(InformationElement):
    def __init__(self):
        InformationElement.__init__(self)
        self.name = 'MT Header IE'
        self.id = 0x41
        self.msgId = 0
        self.imei = 0
        self.dispositionFlags = 0

    def parse(self, rawData):
        self.rawData = rawData

        try:
            if self.id != rawData[0]:
                raise Exception('ID should be 0x{0:x} and is 0x{1:h}'.format(self.id, rawData[0]))

            self.length = struct.unpack('>H', bytes(rawData[1:3]))[0] + 3
            if self.length != 24:
                raise Exception('stated length should be {0} and is {1}'.format(24, self.length))

            if len(rawData) != self.length:
                raise Exception('actual length should be {0} and is {1}'.format(self.length, len(rawData)))

            self.msgId = struct.unpack('>I', bytes(rawData[3:7]))[0]
            self.imei = rawData[7:22]
            self.dispositionFlags = struct.unpack('>H', bytes(rawData[22:24]))[0]
            return True

        except Exception as e:
            print 'MtHeaderIe parse fail:'
            print e
            return False

    def prepareRaw(self):
        self.length = 24
        self.rawData = bytearray(self.length)
        d = self.rawData

        d[0] = self.id
        d[1:3] = struct.pack('>H', self.length - 3)
        d[3:7] = struct.pack('>I', self.msgId)
        d[7:22] = self.imei
        d[22:24] = struct.pack('>H', self.dispositionFlags)


class MtPayloadIe(InformationElement):
    def __init__(self):
        InformationElement.__init__(self)
        self.name = 'MT Payload IE'
        self.id = 0x42
        self.payload = bytearray()

    def parse(self, rawData):
        self.rawData = rawData

        try:
            if self.id != rawData[0]:
                raise Exception('ID should be 0x{0:x} and is 0x{1:h}'.format(self.id, rawData[0]))

            self.length = struct.unpack('>H', bytes(rawData[1:3]))[0] + 3

            if len(rawData) != self.length:
                raise Exception('actual length should be {0} and is {1}'.format(self.length, len(rawData)))

            self.payload = rawData[3:]
            return True

        except Exception as e:
            print 'MtPayloadIe parse fail:'
            print e
            return False

    def prepareRaw(self):
        self.length = len(self.payload) + 3
        self.rawData = bytearray(self.length)
        d = self.rawData

        d[0] = self.id
        d[1:3] = struct.pack('>H', self.length - 3)
        d[3:] = self.payload


class MtConfirmationIe(InformationElement):
    def __init__(self):
        InformationElement.__init__(self)
        self.name = 'MT Confirmation IE'
        self.id = 0x44
        self.msgId = 0
        self.imei = 0
        self.autoId = 0
        self.msgStatus = 0

    def parse(self, rawData):
        self.rawData = rawData

        try:
            if self.id != rawData[0]:
                raise Exception('ID should be 0x{0:x} and is 0x{1:h}'.format(self.id, rawData[0]))

            self.length = struct.unpack('>H', bytes(rawData[1:3]))[0] + 3
            if self.length != 28:
                raise Exception('stated length should be {0} and is {1}'.format(28, self.length))

            if len(rawData) != self.length:
                raise Exception('actual length should be {0} and is {1}'.format(self.length, len(rawData)))

            self.msgId = struct.unpack('>I', bytes(rawData[3:7]))[0]
            self.imei = rawData[7:22]
            self.autoId = struct.unpack('>I', bytes(rawData[22:26]))[0]
            self.msgStatus = struct.unpack('>H', bytes(rawData[26:28]))[0]
            return True

        except Exception as e:
            print 'MtConfirmationIe parse fail:'
            print e
            return False

    def prepareRaw(self):
        self.length = 28
        self.rawData = bytearray(self.length)
        d = self.rawData

        d[0] = self.id
        d[1:3] = struct.pack('>H', self.length - 3)
        d[3:7] = struct.pack('>I', self.msgId)
        d[7:22] = self.imei
        d[22:26] = struct.pack('>I', self.autoId)
        d[26:28] = struct.pack('>H', self.msgStatus)


class MtPriorityIe(InformationElement):
    def __init__(self):
        InformationElement.__init__(self)
        self.name = 'MT Priority IE'
        self.id = 0x46
        self.priority = 0

    def parse(self, rawData):
        self.rawData = rawData

        try:
            if self.id != rawData[0]:
                raise Exception('ID should be 0x{0:x} and is 0x{1:h}'.format(self.id, rawData[0]))

            self.length = struct.unpack('>H', bytes(rawData[1:3]))[0] + 3
            if self.length != 5:
                raise Exception('stated length should be {0} and is {1}'.format(5, self.length))

            if len(rawData) != self.length:
                raise Exception('actual length should be {0} and is {1}'.format(self.length, len(rawData)))

            self.priority = struct.unpack('>H', bytes(rawData[3:5]))[0]
            return True

        except Exception as e:
            print 'MtPriorityIe parse fail:'
            print e
            return False

    def prepareRaw(self):
        self.length = 5
        self.rawData = bytearray(self.length)
        d = self.rawData

        d[0] = self.id
        d[1:3] = struct.pack('>H', self.length - 3)
        d[3:5] = struct.pack('>H', self.priority)
