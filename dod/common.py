import time
import pytest

from dod.DropsDriver import myClient
from dod.JsonFileHandler import JsonFileHandler
from dod.ServerResponse import ServerResponse

# pytest encourages this pattern, apologies.
ip = "172.21.148.101"
port = 9999
supported_json = "drops/supported.json"
client = myClient(ip=ip, port=port, supported_json=supported_json, reload=False)

# create config parser handler
json_handler = JsonFileHandler(supported_json)
# load configs and launch web server
json_handler.reload_endpoints()

# Change function to "wait while busy"
def busy_wait(timeout: int):
  '''
        Busy wait untill timeout value is reached,
        timeout : sec
        returns true if timeout occured
  '''
  start = time.time()
  r = client.get_status()
  delta = 0

  while(r.STATUS['Status'] == "Busy"):
    if delta > timeout:
      return True

    time.sleep(0.1) #Wait a ms to stop spamming robot
    r = client.get_status()
    delta = time.time() - start

  return False

