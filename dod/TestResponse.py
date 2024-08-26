import json

from drops.DropsDriver import myClient
from testServerSpawner import ServerSpawner
from dod.JsonFileHandler import JsonFileHandler

ip = "127.0.0.1"
port = 8081
supported_json = "drops/supported.json"

# pytest encourages this pattern, apologies.
# instantiate HTTP client
client = myClient(ip=ip, port=port, supported_json=supported_json, reload=False)
# spawn test backend
web_server = ServerSpawner(ip, port, supported_json)
# create config parser handler
json_handler = JsonFileHandler(supported_json)
# load configs and launch web server 
json_handler.reload_endpoints()

class TestResponse:
    def test_get_status(self, capsys):
        web_server.launch_web_server()
        # TEST Status
        resp = client.get_status()
        web_server.kill_web_server()
        assert resp.RESULTS == json_handler.get_endpoint_data("/DoD/get/Status")
