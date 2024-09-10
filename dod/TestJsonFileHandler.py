import json
import os
from dod.JsonFileHandler import JsonFileHandler


supported_json = "tests/test_supported.json"


class TestJsonFileHandler:
    '''
    TODO: Very basic test case, build out as we find file parsing edge casess
    TODO: can create test document subfolder within the testing directory
    '''

    def test_file_load(self, capsys):
        # create config parser handler
        json_handler = JsonFileHandler(supported_json)
        # load configs and launch web server 
        json_handler.reload_endpoints()
        expected_resp = {"Position": {
                            "X": 0,
                            "Y": 0,
                            "Z": 500
                        },
                        "LastProbe": "",
                        "Humidity": 10,
                        "Temperature": 228,
                        "BathTemp": -99
                        }

        assert json_handler.get_endpoint_data("/DoD/get/Status") == expected_resp

    def test_file_add_endpoint(self, capsys):
        new_file = "tests/blank_supported.json"

        json_handler = JsonFileHandler(new_file)
        json_handler.create_new_supported_file()

        assert json_handler.get_endpoint_data("/DoD/get/Status") == None
        json_handler.reload_endpoints()

        expected_resp = {"Position": {
                            "X": 0,
                            "Y": 0,
                            "Z": 500
                        },
                        "LastProbe": "",
                        "Humidity": 10,
                        "Temperature": 228,
                        "BathTemp": -99
                        }

        json_handler.add_endpoint("/DoD/get/Status", expected_resp)

        assert json_handler.get_endpoint_data("/DoD/get/Status") == expected_resp
        os.remove(new_file)

