from http.client import HTTPResponse
import json

class ServerResponse:
    """
        Object for parsing incomming HTTPResponse from Robot
    """
    def __init__(self, httObj: HTTPResponse):
        try:
            dat = httObj.read().decode('utf-8')
            response = json.loads(dat)
        except ValueError:
            raise Exception(f"Server did not respond in JSON; Something is wrong\n, {dat}")

        self.TIME = response["Time"]
        self.STATUS = response["Status"]
        self.LAST_ID = response["LastID"]
        self.ERROR_CODE = response["ErrorCode"]
        self.ERROR_MESSAGE = response["ErrorMessage"]
        self.RESULTS = response["Result"]

    def __str__(self):
        return f" TIME: {self.TIME}\n STATUS: {self.STATUS}\n LAST_ID: {self.LAST_ID}\n ERROR_CODE: {self.ERROR_CODE}\n ERROR_MESSAGE: {self.ERROR_MESSAGE}\n RESULTS: {self.RESULTS}\n"

