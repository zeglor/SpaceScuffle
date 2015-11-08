__author__ = 'zeglor'

"""
Transport message examples
"""

# Service messages - these are for low-level communication
handshakeRequest = {
    "type": "handshake",
    "data": "this should be empty",
    "response": False,
}
handshakeResponse = {
    "type": "handshake",
    "id": 1,
    "response": True,
}

heartbeatRequest = {
    "type": "heartbeat",
    "id": 1,
    "response": True,
}

# Not implemented yet
rttRequest = {
    "type": "rtt",
    "id": 1,
    "response": False,
    "...": "..."
}
rttResponse = {
    "type": "rtt",
    "id": 1,
    "response": True,
    "...": "..."
}

# Communication messages - those are returned to caller
unreliableRequest = {
    "id": 1,
    "type": "general",
    "response": False,
    "reliable": False,
    "data": "some data"
}

reliableRequest = {
    "id": 1,
    "type": "general",
    "response": False,
    "reliable": True,
    "messageId": 1,
    "data": "some data"
}
reliableResponse = {
    "id": 1,
    "type": "general",
    "messageId": 1,
    "response": True,
}


from time import time, sleep
from math import sqrt
from enum import Enum
from collections import deque
from time import time
import socket
import json

class TransportMessage:
    @staticmethod
    def createResponse(message, id=None, **kwargs):
        type = message.type
        address = message.address
        clientId = id
        if clientId is None and hasattr(message, "id"):
            clientId = message.id
        if type == "handshake":
            return TransportHandshakeResponseMessage(address, "", clientId, **kwargs)
        elif type == "general":
            return TransportGeneralResponse(address, "", clientId, message.messageId)

    def createMessage(address, clientId=None, type=""):
        if type == "disconnectNotice":
            return TransportDisconnectNotice(address, "", clientId)

    @staticmethod
    def fromBytes(msg):
        data = json.loads(msg[0].decode('UTF8'))
        print(data)
        address = msg[1]
        if data["type"] == "handshake":
            if data.get("id") is None:
                return TransportHandshakeMessage(address, data)
            else:
                return TransportHandshakeResponseMessage(address, data)
        elif data["type"] == "heartbeat":
            return TransportHeartbeatMessage(address, data, data["id"])
        elif data["type"] == "ttl":
            raise NotImplementedError("Message of type TTL is not implemented yet")
        elif data["type"] == "general":
            return TransportGeneralMessage(address, data["data"], data["id"], data["reliable"], data.get("messageId"))

    def __init__(self, address, data):
        self.address = address
        self.type = ""
        self.response = False

    def toDict(self):
        # Address does not get returned
        return {"type": self.type, "response": self.response}

class TransportHandshakeMessage(TransportMessage):
    def __init__(self, address, data):
        super().__init__(address, data)
        self.type = "handshake"

    def toDict(self):
        d = super().toDict()
        return d

class TransportHandshakeResponseMessage(TransportHandshakeMessage):
    def __init__(self, address, data, id, settings={}):
        super().__init__(address, data)
        self.type = "handshake"
        self.id = id
        self.settings = settings
        self.response = True

    def toDict(self):
        d = super().toDict()
        d.update({"id": self.id, "settings": self.settings})
        return d

class TransportDisconnectNotice(TransportMessage):
    """
    This message is sent to client whenever server cleans him up
    """
    def __init__(self, address, data, id):
        super().__init__(address, data)
        self.id = id
        self.type = "disconnectNotice"

    def toDict(self):
        d = super().toDict()
        d.update({"id": self.id})
        return d

class TransportHeartbeatMessage(TransportMessage):
    """
    Heartbeat is a message sent periodically by client to indicate it's still connected
    """
    def __init__(self, address, data, id):
        super().__init__(address, data)
        self.id = id
        self.type = "heartbeat"

class TransportGeneralMessage(TransportMessage):
    """
    general is message that actually contains some useful payload. It is the only type of message returned outside
    """
    def __init__(self, address, data, id, reliable, messageId):
        super().__init__(address, data)
        self.id = id
        self.reliable = reliable
        self.data = data
        self.messageId = messageId
        self.type = "general"

    def toDict(self):
        d = super().toDict()
        d.update({"id": self.id, "reliable": self.reliable, "messageId": self.messageId, "data": self.data})
        return d

class TransportGeneralResponse(TransportMessage):
    def __init__(self, address, data, id, messageId):
        super().__init__(address, data)
        self.id = id
        self.messageId = messageId
        # Response is sent on reliable messages only
        self.reliable = True
        self.data = ""
        self.type = "general"
        self.response = True

    def toDict(self):
        d = super().toDict()
        d.update({"id": self.id, "reliable": self.reliable, "messageId": self.messageId, "data": self.data})
        return d

class Server:
    """
    Types of messages: handshake, heartbeat, rtt, general
    * Handshake is the first message that client should send. It is a request for server to generate client id and
        send it back to client. This id is used in all consequent communication between client and server.
    * Heartbeat is a message sent periodically by client to indicate it's still connected
    !! Not implemented yet
    * RTT is a sequence of messages sent either by client or server to determine round-trip time between server and client
    !! Not implemented yet
    * general is message that actually contains some useful payload. It is the only type of message returned outside


    Messages can be of two types: reliable and unreliable
    * Unreliable messages are fired and forgotten.
    * Reliable messages are stored in self._toConfirm list. Each message of this type after being sent should
        be confirmed by the client it is sent to. If it has not been confirmed in confirm timeout, it is sent again
    """

    class Client:
        id = 0
        @staticmethod
        def genId():
            Server.Client.id += 1
            return Server.Client.id

        def __init__(self, address):
            self.id = Server.Client.genId()
            self.address = address
            self.lastSeen = time()

    class Message:
        def __init__(self, clientId, messageId):
            self.clientId = clientId
            self.messageId = messageId
            self.received = time()

        def __eq__(self, other):
            return other is not None and other.clientId == self.clientId and other.messageId == self.messageId

        def __hash__(self):
            return hash((self.clientId, self.messageId))

    def __init__(self, host, port):
        # Determines maximum time for the client to be valid since his last request
        self.timeout = 5
        # Determines how long message are to be stored in cache to prevent message duplication
        self.messageTimeout = 10
        # Determines minimum period (in seconds) between cleanups
        self.cleanupPeriod = 5
        self._lastCleanup = time()
        self._host = socket.gethostbyname(host)
        self._port = port
        self._sock = None
        self._active = False
        self._bufsize = 1024

        self._sendQueue = deque()

        # _clients stores active clients to manage disconnected clients
        # Function cleanup() iterates over them and removes clients whose last seen time exceeds timeout
        self._clients = {}

        # Reliable messages received from clients are stored in cache for some time to ensure that their duplicates
        #   will be discarded
        self._messageCache = {}

    def start(self):
        self._sock = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        self._sock.setblocking(0)
        self._sock.bind((self._host, self._port))
        self._active = True

    def stop(self):
        self._active = False

    def sendMessage(self, reliable=False):
        pass

    def sendResponse(self, tMessage, immediate=False):
        address = tMessage.address
        data = json.dumps(tMessage.toDict()).encode('UTF8')
        if immediate == False:
            self._sendQueue.append((data, address))
        else:
            self._sock.sendto((data, address))

    def getAll(self):
        messages = []
        rawMessages = self._dispatchMessages()
        for rawMessage in rawMessages:
            tMessage = TransportMessage.fromBytes(rawMessage)
            # !! Should validate message here
            if tMessage.type == "handshake":
                # Handshake message. We should generate unique id and send it back to client
                clientId = self._createClient(tMessage.address)
                response = TransportMessage.createResponse(tMessage, clientId, settings=self.getSettings())
                self.sendResponse(response)
                continue

            if self._clients.get(tMessage.id) is None:
                # We already have disconnected this client. Do nothing
                continue

            self._updateClient(tMessage)
            if tMessage.type == "heartbeat":
                continue

            if tMessage.reliable == True:
                # We got reliable message. Now we must send response back to client
                self.sendResponse(TransportMessage.createResponse(tMessage))
                # Check if this message is not duplicate of previously received reliable message
                if self._isInCache(tMessage):
                    # This is a duplicate of previously received message. It should be discarded
                    continue
                # Store this message for some time to make sure we don't get its duplicate
                # Note that only first message gets cached
                self._cacheMessage(tMessage)

            # Extract message data and store it in list to be returned
            messages.append(tMessage.data)
        return messages


    def sendAll(self):
        try:
            while(True):
                msg = self._sendQueue.popleft()
                self._sock.sendto(msg[0], msg[1])
        except IndexError:
            # This error means send queue is empty. Do nothing
            pass

    def getSettings(self):
        return {"timeout": self.timeout}

    def cleanup(self):
        if self._lastCleanup > time() - self.cleanupPeriod:
            return 0
        self._lastCleanup = time()

        # Cleanup clients
        timeoutLimit = time() - self.timeout
        numCleaned = 0
        keys = list(self._clients)
        for key in keys:
            client = self._clients[key]
            if client.lastSeen < timeoutLimit:
                del self._clients[key]
                self.sendResponse(TransportMessage.createMessage(client.address, client.id, "disconnectNotice"))
                numCleaned += 1

        # Cleanup messages
        timeoutLimit = time() - self.messageTimeout
        keys = list(self._messageCache)
        for key in keys:
            if self._messageCache[key].received < timeoutLimit:
                del self._messageCache[key]
        return numCleaned

    def _dispatchMessages(self):
        data = '0'
        messages = []
        try:
            while len(data) > 0:
                data = self._sock.recvfrom(self._bufsize)
                messages.append(data)
                print("New message from {}".format(data[1]))
        except BlockingIOError:
            pass
        return messages

    def _createClient(self, address):
        client = Server.Client(address)
        #self._clients.append(client)
        self._clients[client.id] = client
        return client.id

    def _updateClient(self, message):
        client = self._clients.get(message.id)
        if client is not None:
            self._clients[message.id].address = message.address

    def _cacheMessage(self, message):
        cMessage = Server.Message(message.id, message.messageId)
        self._messageCache[cMessage] = cMessage

    def _isInCache(self, message):
        cMessage = Server.Message(message.id, message.messageId)
        return cMessage in self._messageCache


class MessageType(Enum):
    # client messages
    connect = 0
    disconnect = 1
    heartbeat = 2
    action = 3
    # server messages
    connectAns = 10
    disconnectAns = 11
    gameState = 13

class Message:
    @staticmethod
    def unpackMessage(str):
        pass

    def __init__(self, type):
        self._type = None

class Vector2:
    def __init__(self, x, y=None):
        if isinstance(x, Vector2):
            self._x = x._x
            self._y = x._y
        else:
            self._x = x
            self._y = y

    def __add__(self, other):
        return Vector2(self._x + other.x, self._y + other.y)

    def __sub__(self, other):
        return Vector2(self._x - other.x, self._y - other.y)

    def __mul__(self, other):
        if isinstance(other, int) or isinstance(other, float):
            self._x *= other
            self._y *= other

    def length(self):
        return sqrt(self._x * self._x + self._y * self._y)

    def normalize(self):
        return Vector2(self * (1/self.length))

class GameObject:
    def __init__(self, startPoint):
        self._pos = startPoint
        self._speed = Vector2(0, 0)

    def move(self, deltaTime):
        self.pos += self.speed * deltaTime

class SpaceBody(GameObject):
    def __init__(self, startPoint):
        super().__init__(self, startPoint)
        self._id = 1
        self._speedAbs = 5

    def startMove(self, direction):
        """
        commands SpaceBody to move in custom direction
        :param direction: instance of Vector2
        """
        self._speed = Vector2(direction).normalize() * self._speedAbs


class GameController:
    def __init__(self):
        self._gameObjects = []

    def move(self, deltaTime):
        for gameObject in self._gameObjects:
            gameObject.move(deltaTime)

def main():
    server = Server(host='127.0.0.1', port='5555')

    lastTime = time()
    while(True):
        # check ingoing messages
        #   dispatch ingoing messages
        #   pass those messages to their adressees
        # process players input
        # process AI
        #   for each ship controlled by AI call update()
        # count delta time between this call and previous
        timeNow = time()
        deltaTime = timeNow - lastTime
        lastTime = timeNow
        # update world
        #   move objects
        gameController.move(deltaTime)
        #   check collisions
        #   update game objects
        # send updated world state to players

def serve():
    # Setup server
    server = Server(host='127.0.0.1', port=5555)
    server.start()
    while(True):
        # Check ingoing messages
        # Dispatch ingoing messages
        numCleaned = server.cleanup()
        if numCleaned > 0:
            print("Cleaned up {} clients".format(numCleaned))
        messages = server.getAll()
        server.sendAll()
        for message in messages:
            print(message)
        print('sleeping...')
        sleep(0.5)

if __name__ == '__main__':
    serve()