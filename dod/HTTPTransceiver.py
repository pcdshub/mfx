import json
import logging
from http.client import HTTPConnection
from multiprocessing import Queue, Semaphore
from dod.ServerResponse import ServerResponse

logger = logging.getLogger(__name__)

'''
send transmits a formatted HTTP GET request
it will not check the validity of request
it will persist result in a place that can be read.
'''


class HTTPTransceiver():
    def __init__(self, conn : HTTPConnection, queue : Queue, q_ready : Semaphore):
        self.__conn__ = conn
        self.__queue__ = queue
        self.__queue_ready__ = q_ready

    def send(self, endpoint : str):
        logger.info(f"attempting to send: {endpoint}...")
        print(endpoint)
        self.__conn__.request("GET", endpoint)
        logger.info("issued request")
        reply = self.__conn__.getresponse()
        logger.info(f"got response {reply}")
        reply_obj = ServerResponse(reply)

        if (self.__queue__ is not None):
          self.__queue__.put(reply_obj)
          self.__queue_ready__.release()  # signal to other 'threads' that there is work to do
        return

    '''
    Pops most recent response from response queue
    '''
    def get_response(self):
      if not self.__queue_ready__.acquire(block=True, timeout=10):
        return None
      else:
        return self.__queue__.get()
