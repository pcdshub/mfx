class Debug:
    def __init__(self):
        import os
        self.serverlist = os.popen(f"netconfig search ioc-mfx* --brief").read().splitlines()