import json
import pprint
import logging

logger = logging.getLogger(__name__)

class JsonFileHandler:
    """
        Handle supported.json file
    """

    def __init__(self, file_name : str):
        self.file_name = file_name
        self.data = dict() 
        self.endpoints = dict() # EndPoints
        self.endpoints_map= dict() #MAP

    def create_new_supported_file(self):
        """
            Create New supported enpoints file, will not create if file already
            exists
        """
        f = None
        try:
            f = open(self.file_name, "x")
        except:
            logging.info(f"{self.file_name} already exists")

        if f != None:
            self.data = {
                    "header": {
                        "Time": "",
                        "Status": {
                            "Status": "",
                            "StatusCode": 200
                            },
                        "LastID": 1,
                        "ErrorCode": 0,
                        "ErrorMessage": "NA",
                        "Result": {}
                        },
                    "endpoints": []
                    }

            f.write(json.dumps(self.data, indent=4))
            f.close()


    def reload_endpoints(self):
        file_fd = open(self.file_name, 'r')
        self.data = json.load(file_fd)
        self.endpoints = self.data["endpoints"]

        # map endpoint with index
        endpointIndex = 0
        for endpoint in self.endpoints:
            self.endpoints_map[endpoint["API"]] = endpointIndex
            endpointIndex = endpointIndex + 1

        file_fd.close()

    def get_endpoint_data(self, endpoint : str):
        logging.info(f"looking for {endpoint}")
        if endpoint not in self.endpoints_map.keys():
            logging.info(f"{endpoint} does not exist")
            return None
        else:
            logging.info(f"Found {endpoint}")
            return self.endpoints[self.endpoints_map[endpoint]]['payload']

    def add_endpoint(self, endpoint : str, payload : str, args = None, comment = None):
        """
            Add endpoint to Json file
        """
        if endpoint in self.endpoints_map.keys():
            logging.info("endpoint already exists")
            return 

        skel = { 
                "API": "", 
                "args": "",
                "payload" : "",
                "__comments__" : "",
                }

        skel["API"] = endpoint
        skel["args"] = args
        skel["payload"] = payload
        skel["__comments__"] = comment

        self.data["endpoints"].append(skel)

        f = open(self.file_name, "w")
        f.write(json.dumps(self.data, indent=4))
        f.close()

        self.reload_endpoints()

