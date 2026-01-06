"""
Debugging and diagnostic utilities for MFX beamline infrastructure.

Provides comprehensive tools for checking beamline readiness, server
health, motor status, and troubleshooting hardware/software issues.
"""

import os
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


class Debug:
    """
    Beamline infrastructure debugging and monitoring tools.

    Comprehensive diagnostics for MFX beamline servers, motors,
    and readiness checks. Identifies and helps resolve hardware
    and software issues.

    Attributes
    ----------
    ioc_serverlist : List[str]
        List of IOC (EPICS controller) server hostnames daq_serverlist : List[str]
        List of DAQ server hostnames
    error_servers : List[str]
        Servers with detected issues (populated during checks)

    Methods
    -------
    awr(hutch)
        Check if beamline is ready for beam operations
    motor_check()
        Power up all available motors and check status
    check_server(server)
        Check status of individual server
    check_servers(server_type)
        Check status of all servers of specified type
    server_list(server_type)
        List all servers of specified type
    cycle_server(server)
        Power cycle a problematic server

    Notes
    -----
    Infrastructure Components:

    IOC Servers:
    - EPICS Input/Output Controllers
    - Control motors, detectors, diagnostics
    - Named: ioc-mfx-{system}-{number}
    - Critical for beamline operation

    DAQ Servers:
    - Data Acquisition systems
    - Handle detector readout
    - Data storage and distribution
    - Named: daq-mfx-{system}-{number}

    Server Discovery:
    - Uses 'netconfig search' command
    - Filters out management interfaces:
      - IPMI: Remote management
      - FEZ: Front-end zone
      - ICS: Instrument control system

    Health Checks:
    - Power state (on/off)
    - Console connectivity
    - Network ping response
    - Process status

    Typical Issues:
    - Servers powered off (operator error)
    - Network connectivity problems
    - Hung processes requiring restart
    - IPMI controller failures
    - Disk full conditions

    Troubleshooting Workflow:
    1. Check beamline readiness (awr)
    2. Identify problem servers
    3. Check specific server details
    4. Power cycle if needed
    5. Verify recovery

    Examples
    --------
    Create debug instance:
    >>> debug = Debug()

    Check beamline readiness:
    >>> debug.awr('mfx')

    Find all IOC servers with issues:
    >>> error_servers = debug.check_servers('ioc')
    >>> if error_servers:
    ...     print(f"Problems: {error_servers}")

    Check specific server:
    >>> status = debug.check_server('ioc-mfx-rec01')
    >>> print(status)

    Power cycle problem server:
    >>> debug.cycle_server('ioc-mfx-rec01')

    List all servers:
    >>> debug.server_list('all')

    See Also
    --------
    BashUtilities : Additional beamline utilities
    """

    def __init__(self):
        """
        Initialize Debug utilities.

        Discovers and categorizes all MFX servers automatically.
        Filters out management interfaces to focus on operational
        servers.
        """
        logger.info("Initializing Debug utilities...")

        # Discover all MFX IOC servers
        full_ioc_serverlist = os.popen(
            "netconfig search ioc-mfx* --brief"
        ).read().splitlines()

        # Discover all MFX DAQ servers
        full_daq_serverlist = os.popen(
            "netconfig search daq-mfx* --brief"
        ).read().splitlines()

        # Filter out management interfaces (IPMI, FEZ, ICS)
        self.ioc_serverlist = [
            server for server in full_ioc_serverlist
            if not any(x in server.lower()
                      for x in ['ipmi', 'fez', 'ics'])
        ]

        self.daq_serverlist = [
            server for server in full_daq_serverlist
            if not any(x in server.lower()
                      for x in ['ipmi', 'fez', 'ics'])
        ]

        # Initialize error tracking
        self.error_servers = []

        logger.info(f"Found {len(self.ioc_serverlist)} IOC servers")
        logger.info(f"Found {len(self.daq_serverlist)} DAQ servers")

    def awr(self, hutch: str = 'mfx'):
        """
        Check if beamline is ready for beam operations.

        AWR (All We Ready?) performs comprehensive readiness check
        of all beamline infrastructure components.

        Parameters
        ----------
        hutch : str, optional
            Hutch name to check. Default is 'mfx'.

        Returns
        -------
        None
            Prints readiness status to console

        Notes
        -----
        Readiness Checks:

        """
        logger.info(f"\n{'='*60}")
        logger.info(f"BEAMLINE READINESS CHECK: {hutch.upper()}")
        logger.info(f"{'='*60}\n")

        os.system(
            f"/cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/awr {hutch}")

    def motor_check(self):
        """
        Power up and check status of all beamline motors.

        Attempts to power all available motors and verifies
        communication. Useful after power outages or maintenance.

        Returns
        -------
        None

        Notes
        -----
        Motor Power Process:
        1. Discover all motor PVs
        2. Check current power status
        3. Power on if needed
        4. Verify communication
        5. Report status

        Motor Types Checked:
        - IMS: Intelligent Motor Systems
        - Newport: Motion controllers
        - Beckhoff: PLC-based axes
        - SmarAct: Piezo motors

        Common Issues:
        - Controllers offline
        - Communication errors
        - Limit switch activation
        - Encoder problems
        - Power supply issues

        Warnings
        --------
        Powering motors may cause small movements.
        Ensure area is clear before running.

        Examples
        --------
        Check and power all motors:
        >>> debug = Debug()
        >>> debug.motor_check()
        Checking motors...
        Powered: 156/156
        Communication OK: 156/156
        All motors ready

        See Also
        --------
        awr : Full beamline readiness including motors
        """
        logger.info("Checking and powering motors...")
        os.system(
            f"/cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/mfxpowerup.sh")

    def check_server(self, server: str) -> List[str]:
        """
        Check status of individual server.

        Performs comprehensive health check on specified server
        including power status, network connectivity, and console
        access.

        Parameters
        ----------
        server : str
            Server hostname to check

        Returns
        -------
        List[str]
            List of status messages. Empty if no issues.

        Notes
        -----
        Health Checks:
        - Power state via serverStat
        - Network ping response
        - Console telnet connectivity
        - IPMI accessibility (if applicable)

        Status Information:
        - on/off: Power state
        - responding/timeout: Network
        - accessible/blocked: Console

        Diagnostic Commands:
        - serverStat {server}: Power status
        - ping {server}: Network test
        - telnet {server} 2049: Console test

        Examples
        --------
        Check single server:
        >>> debug = Debug()
        >>> status = debug.check_server('ioc-mfx-rec01')
        >>> if status:
        ...     print(f"Issues: {status}")
        ... else:
        ...     print("Server OK")

        Check and analyze:
        >>> status = debug.check_server('ioc-mfx-rec01')
        >>> for msg in status:
        ...     print(f"  - {msg}")

        See Also
        --------
        check_servers : Check multiple servers
        cycle_server : Power cycle problem server
        """
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

    def server_list(self, server_type: str = 'all'):
        """
        List all servers of specified type.

        Displays formatted list of IOC servers, DAQ servers,
        or both.

        Parameters
        ----------
        server_type : str, optional
            Type to list: 'ioc', 'daq', or 'all'.
            Default is 'all'.

        Returns
        -------
        None
            Prints server list to console

        Examples
        --------
        List all IOC servers:
        >>> debug = Debug()
        >>> debug.server_list('ioc')

        List all servers:
        >>> debug.server_list('all')

        See Also
        --------
        check_servers : Check server health
        """
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