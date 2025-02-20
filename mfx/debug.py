class Debug:
    def __init__(self):
        import os
        full_ioc_serverlist = os.popen(f"netconfig search ioc-mfx* --brief").read().splitlines()
        full_daq_serverlist = os.popen(f"netconfig search daq-mfx* --brief").read().splitlines()
        self.ioc_serverlist = [ioc for ioc in full_ioc_serverlist if not ioc.endswith(
            "-ipmi") and not ioc.endswith("-fez") and not ioc.endswith("-ics")]
        self.daq_serverlist = [ioc for ioc in full_daq_serverlist if not ioc.endswith(
            "-ipmi") and not ioc.endswith("-fez") and not ioc.endswith("-ana")]


    def awr(self, hutch='mfx'):
        """
        Checks if the beamline is ready to take beam

        Parameters
        ----------
        hutch: str, optional
            Specify the hutch you want to check. Default is MFX because it is the best
        """
        import os
        import logging
        logging.info(f"{hutch} Beamline Check")
        os.system(f"/cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/awr {hutch}")


    def motor_check(self):
        import os
        import logging
        logging.info(f"Powering up all available motors")
        os.system(f"/cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/mfxpowerup.sh")


    def check_server(self, server):
        """
        Checks the status of an individual server

        Parameters
        ----------
        server: str, required
            Specify the server name to check. Use debug.server_list('all') to see all servers
        """
        import os
        import logging
        status = None
        if str(server) in self.ioc_serverlist or str(server) in self.daq_serverlist:
            logging.info(f"Checking the status of: {server}")
            status = os.popen(f"/reg/g/pcds/engineering_tools/latest-released/scripts/serverStat {server} status").read().splitlines()
        else:
            logging.info(f"The server you are looking for does not exist please select one of the following")
            self.server_list('ioc')
            self.server_list('daq')
        return status


    def cycle_server(self, server):
        """
        Cycles an individual server

        Parameters
        ----------
        server: str, required
            Specify the server name to cycle. Use debug.server_list('all') to see all servers
        """
        import os
        import logging
        if str(server) in self.ioc_serverlist or str(server) in self.daq_serverlist:
            logging.info(f"Power cycling: {server}")
            os.system(f"/reg/g/pcds/engineering_tools/latest-released/scripts/serverStat {server} cycle")
        else:
            logging.info(f"The server you are looking for does not exist please select one of the following")
            self.server_list('ioc')
            self.server_list('daq')

    
    def check_all_servers(self, server_type):
        """
        Checks the status of all servers local to MFX

        Parameters
        ----------
        server_type: str, required
            Specify the server type input either 'all', 'ioc', or 'daq
        """
        import logging
        self.error_servers = []
        if str(server_type) == 'all':
            logging.info(f"You've decided to check all {len(self.ioc_serverlist) + len(self.daq_serverlist)} servers.")
            for server in self.ioc_serverlist:
                status = self.check_server(str(server))
                if status[0].endswith('on') and status[1].split(", ")[0].endswith('1)') and status[2].endswith('up'):
                    logging.info(f"Server {server} has passed all tests")
                else:
                    logging.error(f"Server {server} has failed one or more tests and is added to the broken list")
                    logging.error(status)
                    self.error_servers.append(server)

            for server in self.daq_serverlist:
                status = self.check_server(str(server))
                if status[0].endswith('on') and status[1].split(", ")[0].endswith('1)') and status[2].endswith('up'):
                    logging.info(f"Server {server} has passed all tests")
                else:
                    logging.error(f"Server {server} has failed one or more tests and is added to the broken list")
                    logging.error(status)
                    self.error_servers.append(server)

        elif str(server_type) == 'ioc':
            logging.info(f"You've decided to check all {len(self.ioc_serverlist)} ioc servers.")
            for server in self.ioc_serverlist:
                status = self.check_server(str(server))
                if status[0].endswith('on') and status[1].endswith('1)') and status[2].endswith('up'):
                    logging.info(f"Server {server} has passed all tests")
                else:
                    logging.error(f"Server {server} has failed one or more tests and is added to the broken list")
                    self.error_servers.append(server)

        elif str(server_type) == 'daq':
            logging.info(f"You've decided to check all {len(self.daq_serverlist)} daq servers.")
            for server in self.daq_serverlist:
                status = self.check_server(str(server))
                if status[0].endswith('on') and status[1].endswith('1)') and status[2].endswith('up'):
                    logging.info(f"Server {server} has passed all tests")
                else:
                    logging.error(f"Server {server} has failed one or more tests and is added to the broken list")
                    self.error_servers.append(server)
        else:
            logging.warning(f"There is no server of the type you requested. Please use either ioc or daq or all.")

        if len(self.error_servers) != 0:
            logging.warning(f"There is something wrong with the following servers.")
            for server in self.error_servers:
                print(f'{server}')
            cycle = input("\nWould you like to power cycle all error servers? (y/n)? ")

            if cycle.lower() == "y":
                logging.info(f"You've decided to cycle all {len(self.error_servers)} broken servers.")
                for server in self.error_servers:
                    self.cycle_server(str(server))
            else:
                logging.info(f"You've decided not to cycle {len(self.error_servers)} broken servers.")
        else:
            logging.info(f"All {len(self.error_servers)} servers are ready to rock.")

        return self.error_servers


    def server_list(self, server_type):
        """
        Lists servers local to MFX

        Parameters
        ----------
        server_type: str, required
            Specify the server type input either 'all', 'ioc', or 'daq
        """
        import logging
        if str(server_type) == 'all':
            print('IOC SERVERS\n#########################')
            for server in self.ioc_serverlist:
                print(f'{server}')
            print('\nDAQ SERVERS\n#########################')
            for server in self.daq_serverlist:
                print(f'{server}')
        elif str(server_type) == 'ioc':
            print('IOC SERVERS\n#########################')
            for server in self.ioc_serverlist:
                print(f'{server}')
        elif str(server_type) == 'daq':
            print('DAQ SERVERS\n#########################')
            for server in self.daq_serverlist:
                print(f'{server}')
        else:
            logging.warning(f"There is no server of the type you requested. Please use either ioc or daq.")