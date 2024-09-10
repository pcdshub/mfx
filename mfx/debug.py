class Debug:
    def __init__(self):
        import os
        self.ioc_serverlist = os.popen(f"netconfig search ioc-mfx* --brief").read().splitlines()
        self.daq_serverlist = os.popen(f"netconfig search daq-mfx* --brief").read().splitlines()
        