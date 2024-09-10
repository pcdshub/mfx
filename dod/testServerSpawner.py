
from testServer import MyServer
from multiprocessing import Process, Event
from http.server import HTTPServer
import time


class ServerSpawner():
    """
    Class To start and kill local web server
    """
    def __init__(self, hostName : str, serverPort : int, supportedJson : str):
      self.hostName = hostName
      self.serverPort = serverPort
      self.supportedJson = supportedJson
      self.event = Event()

    def launch_web_server(self):
        def server_launch():
            """
            Function for server starting server process
            """
            print("Server started http://%s:%s" % (self.hostName, self.serverPort))
            webServer = HTTPServer((self.hostName, self.serverPort), MyServer)

            while not self.event.is_set():
                webServer.handle_request()
                # Time needed for one request to be recived and event flag to be set
                time.sleep(0.1)

            print("Server stopped.")
            webServer.server_close()

        self.proc = Process(target=server_launch)
        self.proc.start()
        time.sleep(0.1)

    def kill_web_server(self):
        # send kill signal to test server
        self.event.set()
        self.proc.join()
