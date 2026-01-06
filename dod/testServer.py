# Python 3 server example
from http.server import BaseHTTPRequestHandler, HTTPServer
import json


hostName = "localhost"
serverPort = 8081
supportedJson = 'supported.json'


class MyServer(BaseHTTPRequestHandler):
    def do_GET(self):

        # Parse command
        parsePath = self.path.split('?')
        command = parsePath.pop(0)
        args = parsePath

        print(command, args)

        # Check if command exists
        fd = open(supportedJson, "r")
        data = json.load(fd)
        endpoints = data["endpoints"]
        capabilities = dict()

        endpointIndex = 0
        for endpoint in endpoints:
            capabilities[endpoint["API"]] = endpointIndex
            endpointIndex = endpointIndex + 1

        if command not in capabilities.keys():
            fd.close()
            self.send_response(404)
            self.end_headers()
            return

        fd.close()

        # Udate JSON File IF we have Inputs
        currentCommandJson = endpoints[capabilities[command]]
        if "args" in currentCommandJson.keys():
            for arg in args:
                (var, value) = arg.split("=")
                currentCommandJson['args'][var] = value

            endpoints[capabilities[command]] = currentCommandJson
            data["endpoints"] = endpoints

            fd = open(supportedJson, "w")
            toFile = json.dumps(data, indent=4)
            fd.write(toFile)
            fd.close()

        # Respond to Client
        payLoad = endpoints[capabilities[command]]["payload"]
        header = data['header']
        header["Result"] = payLoad

        payLoad = json.dumps(header, ensure_ascii=False)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(bytes(payLoad, "utf-8"))

        print(payLoad)


if __name__ == "__main__":
    webServer = HTTPServer((hostName, serverPort), MyServer)
    print("Server started http://%s:%s" % (hostName, serverPort))

    try:
        webServer.serve_forever()
    except KeyboardInterrupt:
        pass

    webServer.server_close()
    print("Server stopped.")
