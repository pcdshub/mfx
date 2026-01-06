import logging
import json

from http.client import HTTPConnection, HTTPResponse
from multiprocessing import Queue, Semaphore
from dod.HTTPTransceiver import HTTPTransceiver 
from dod.ServerResponse import ServerResponse

logger = logging.getLogger(__name__)


# TODO: all file io should go through JsonFileHandler, this class should only concern itself with 
# the logic of interacting with the actual to update our notion of what endpoints the machine supports and the arguments those take
# because the machine is the source of truth for what API is provided
class SupportedEndsHandler:
    """
        Class meant to handle supported endpoints Json file.
            Reloads endpoints, keeps track of API args, and possible 'do' actions

            TODO: Write updates to JSON file?
    """
    def __init__(self, file : str, conn : HTTPConnection):
        self.file = file
        self.__queue__ = Queue()
        self.__queue_ready__ = Semaphore(value=0)
        self.__conn__ = conn
        self.supported_ends = {
          'get' : [],
          'do' : {},
          'conn' : []
        }
        self.transceiver = HTTPTransceiver(self.__conn__, self.__queue__, self.__queue_ready__)

    def get_endpoints(self):
        return self.supported_ends

    def reload_endpoint(self, endpoint : str):
        """
            Reloads endpoints by asking server
        """
        if endpoint in self.supported_ends['do'].keys():
          # check this do endpoint takes an argument
          if '?' in endpoint:
            # Any float is acceptable for pure moves
            if 'MoveX' in endpoint or 'MoveY' in endpoint or "MoveZ" in endpoint:
              return
            cursed = f"/DoD/get/{endpoint.split('?')[1].split('=')[0]}s"
            self.transceiver.send(cursed)
            self.supported_ends['do'][endpoint] = self.transceiver.get_response().RESULTS

    def reload_all(self):
        """
            Reloads ALL endpoints by asking server
        """
        try:
          f = open(self.file)
        except FileNotFoundError:
          logger.error("File supported.json not found")

        with f:
          json_data = json.load(f)["endpoints"]
          self.supported_ends['get'] = [x['API'] for x in json_data if x['API'][5:8] == 'get']
          self.supported_ends['do'] = {x['API'] : None for x in json_data if x['API'][5:7] == 'do'}
          self.supported_ends['conn'] = [x['API'] for x in json_data if 'connect' in x['API'][5:].lower()]

        for ent in self.supported_ends['do'].keys():
          self.reload_endpoint(ent)
