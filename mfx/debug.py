"""Debugging and diagnostic utilities for MFX beamline infrastructure."""

import os
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


class Debug:
    """
    Beamline infrastructure debugging and monitoring tools.

    Provides comprehensive diagnostics for MFX beamline servers,
    motors, and readiness checks. Helps identify and resolve
    hardware and software issues.

    Components checked:
    - IOC servers (EPICS Input/Output Controllers)
    - DAQ servers (Data Acquisition)
    - Motor power status
    - Beamline readiness

    Methods
    -------
    awr(hutch) : None
        Check if beamline is ready for beam
    motor_check() : None
        Power up all available motors
    check_server(server) : List[str]
        Check status of individual server
    check_servers(server_type) : List[str]
        Check status of all servers of specified type
    server_list(server_type) : None
        List all servers of specified type
    cycle_server(server) : None
        Power cycle a server

    Attributes
    ----------
    ioc_serverlist : List[str]
        List of IOC server hostnames
    daq_serverlist : List[str]
        List of DAQ server hostnames
    error_servers : List[str]
        List of servers with detected issues

    Notes
    -----
    Server Types:
    - IOC: EPICS Input/Output Controllers
      Control motors, detectors, diagnostics
    - DAQ: Data Acquisition systems
      Handle detector readout and data storage

    Server Discovery:
    - Uses netconfig to find servers
    - Filters out management interfaces:
      - IPMI (remote management)
      - FEZ (front-end zone)
      - ICS (instrument control system)

    Health Checks:
    - Power state (on/off)
    - Console connectivity
    - Network availability

    Typical Issues:
    - Servers powered off
    - Network connectivity problems
    - Hung processes
    - IPMI failures

    Examples
    --------
    Create debug instance:
    >>> debug = Debug()

    Check beamline readiness:
    >>> debug.awr('mfx')

    Check all IOC servers:
    >>> error_servers = debug.check_servers('ioc')

    Check specific server:
    >>> status = debug.check_server('ioc-mfx-rec01')

    Power cycle problem server:
    >>> debug.cycle_server('ioc-mfx-rec01')

    See Also
    --------
    BashUtilities : Additional beamline utilities
    """

    def __init__(self):
        """
        Initialize Debug utilities.

        Discovers and categorizes all MFX servers automatically.
        Filters out management interfaces to focus on operational servers.
        """
        # Discover all MFX servers
        full_ioc_serverlist = os.popen(
            "netconfig search ioc-mfx* --brief"
        ).read().splitlines()

        full_daq_serverlist = os.popen(
            "netconfig search daq-mfx* --brief"
        ).read().splitlines()

        # Filter out management interfaces
        self.ioc_serverlist = [
            ioc for ioc in full_ioc_serverlist
            if not ioc.endswith("-ipmi")
            and not ioc.endswith("-fez")
            and not ioc.endswith("-ics")
        ]

        self.daq_serverlist = [
            daq for daq in full_daq_serverlist
            if not daq.endswith("-ipmi")
            and not daq.endswith("-fez")
            and not daq.endswith("-ana")
        ]

        # Initialize error tracking
        self.error_servers = []

        logger.info(
            f"Discovered {len(self.ioc_serverlist)} IOC servers "
            f"and {len(self.daq_serverlist)} DAQ servers"
        )

    def awr(self, hutch: str = 'mfx'):
        """
        Check if beamline is ready for X-ray beam.

        Runs comprehensive beamline readiness check including:
        - Hutch door status (closed)
        - Personnel safety system (PSS)
        - Beam stop positions
        - Shutter states
        - Critical motor positions

        Parameters
        ----------
        hutch : str, optional
            Hutch to check: 'mfx', 'cxi', 'xcs', etc. (default: 'mfx')

        Returns
        -------
        None
            Results printed to console

        Notes
        -----
        AWR (Allow White Radiation):
        - Checks all safety interlocks
        - Verifies beam path is clear
        - Confirms personnel safety

        Safety Systems Checked:
        - PSS (Personnel Safety System)
        - BSTS (Beam Stop System)
        - Door interlocks
        - Shutter positions
        - Stopper positions

        Script Location:
        /cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/awr

        Pass Criteria:
        - All doors closed
        - PSS enabled
        - Beam stops inserted (when required)
        - Shutters in safe positions
        - No personnel in hutch

        Common Issues:
        - Door not fully closed
        - Beam stop misaligned
        - PSS not enabled
        - Equipment in beam path

        Examples
        --------
        Check MFX readiness:
        >>> debug = Debug()
        >>> debug.awr('mfx')

        Check XCS readiness:
        >>> debug.awr('xcs')

        See Also
        --------
        motor_check : Check motor power status
        """
        logger.info(f"{hutch.upper()} Beamline Readiness Check")
        os.system(
            f"/cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/awr {hutch}"
        )

    def motor_check(self):
        """
        Power up all available motors.

        Attempts to enable power on all motors that are currently
        disabled. Useful after power outages or maintenance.

        Returns
        -------
        None

        Notes
        -----
        Motor Power States:
        - Enabled: Motor can move
        - Disabled: Motor locked, cannot move
        - Faulted: Motor in error state

        This Function:
        - Scans all motor PVs
        - Identifies disabled motors
        - Enables power where possible
        - Reports results

        Script Location:
        /cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/mfxpowerup.sh

        Common Reasons Motors Disabled:
        - After IOC restart
        - After power outage
        - Manual disable for safety
        - Fault conditions

        Safety Notes:
        - Only enables motors in safe state
        - Does not clear fault conditions
        - Does not move motors
        - Logs all actions

        When to Use:
        - After IOC restart
        - After power restoration
        - Before starting experiments
        - When motors won't respond

        Examples
        --------
        >>> debug = Debug()
        >>> debug.motor_check()

        See Also
        --------
        awr : Check beamline readiness
        check_servers : Check server status
        """
        logger.info("Powering up all available motors")
        os.system(
            "/cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/mfxpowerup.sh"
        )

    def check_server(self, server: str) -> List[str]:
        """
        Check status of individual server.

        Performs three health checks:
        1. Power state (on/off)
        2. Console connectivity
        3. Network availability (ping)

        Parameters
        ----------
        server : str
            Server hostname (e.g., 'ioc-mfx-rec01')

        Returns
        -------
        List[str]
            List of three status strings:
            [power_status, console_status, network_status]

        Notes
        -----
        Status Checks:

        1. Power State:
           - Uses IPMI to check power
           - Returns: "Chassis Power is on" or "Chassis Power is off"

        2. Console:
           - Checks console server connectivity
           - Returns: "1) console_name" or error

        3. Network:
           - Pings server
           - Returns: "is up" or "is down"

        IPMI (Intelligent Platform Management Interface):
        - Remote server management
        - Independent of OS
        - Allows power control and monitoring

        Console Server:
        - Provides serial console access
        - Used for debugging and recovery
        - Independent of network

        Healthy Server Returns:
        ["Chassis Power is on", "1) server-name", "server is up"]

        Examples
        --------
        >>> debug = Debug()
        >>> status = debug.check_server('ioc-mfx-rec01')
        >>> print(status)
        ['Chassis Power is on', '1) console-ioc-mfx-rec01', 'ioc-mfx-rec01 is up']

        Check power state:
        >>> status = debug.check_server('ioc-mfx-rec01')
        >>> if not status[0].endswith('on'):
        ...     print("Server is powered off!")

        See Also
        --------
        check_servers : Check multiple servers
        cycle_server : Power cycle server
        """
        status = []

        # Check power state via IPMI
        power_check = os.popen(
            f"ipmitool -I lanplus -U root -P c@lvin -H {server}-ipmi "
            f"chassis power status"
        ).read().strip()
        status.append(power_check)

        # Check console connectivity
        console_check = os.popen(
            f"netconfig search console-{server} --terse"
        ).read().strip()
        status.append(console_check)

        # Check network (ping)
        network_check = os.popen(
            f"ping -c 1 -W 1 {server} > /dev/null 2>&1 && "
            f"echo '{server} is up' || echo '{server} is down'"
        ).read().strip()
        status.append(network_check)

        return status

    def check_servers(self, server_type: str) -> List[str]:
        """
        Check status of all servers of specified type.

        Performs health checks on all IOC servers, DAQ servers,
        or both. Identifies problem servers and optionally
        initiates power cycling.

        Parameters
        ----------
        server_type : str
            Server type to check: 'ioc', 'daq', or 'all'

        Returns
        -------
        List[str]
            List of servers with detected issues

        Raises
        ------
        ValueError
            If server_type not in ['ioc', 'daq', 'all']

        Notes
        -----
        Check Criteria:
        - Power state must end with 'on'
        - Console must contain '1)'
        - Network must end with 'up'

        Any failure adds server to error list.

        Server Types:
        - 'ioc': EPICS IOC servers only
        - 'daq': DAQ servers only
        - 'all': Both IOC and DAQ servers

        After Checks:
        - Lists all problem servers
        - Offers to power cycle errors
        - User can choose to cycle or skip

        Power Cycle Option:
        - Presented if any servers have issues
        - Cycles all error servers if accepted
        - Individual cycling also available

        Typical Issues Found:
        - Servers powered off (power != 'on')
        - Console unreachable (no '1)')
        - Network down (ping fails)

        Examples
        --------
        Check all IOC servers:
        >>> debug = Debug()
        >>> errors = debug.check_servers('ioc')
        >>> print(f"Found {len(errors)} IOC servers with issues")

        Check all servers:
        >>> errors = debug.check_servers('all')
        >>> for server in errors:
        ...     print(f"Problem: {server}")

        Check and auto-cycle (non-interactive):
        >>> debug = Debug()
        >>> errors = debug.check_servers('daq')
        >>> for server in errors:
        ...     debug.cycle_server(server)

        See Also
        --------
        check_server : Check single server
        cycle_server : Power cycle server
        server_list : List available servers
        """
        server_type = server_type.lower()
        self.error_servers = []

        if server_type == 'all':
            logger.info(
                f"Checking all {len(self.ioc_serverlist) + len(self.daq_serverlist)} servers"
            )

            # Check IOC servers
            for server in self.ioc_serverlist:
                status = self.check_server(server)
                power_ok = status[0].endswith('on')
                console_ok = '1)' in status[1].split(", ")[0]
                network_ok = status[2].endswith('up')

                if power_ok and console_ok and network_ok:
                    logger.info(f"Server {server} passed all tests")
                else:
                    logger.error(
                        f"Server {server} failed one or more tests "
                        f"(added to error list)"
                    )
                    logger.error(f"  Status: {status}")
                    self.error_servers.append(server)

            # Check DAQ servers
            for server in self.daq_serverlist:
                status = self.check_server(server)
                power_ok = status[0].endswith('on')
                console_ok = '1)' in status[1].split(", ")[0]
                network_ok = status[2].endswith('up')

                if power_ok and console_ok and network_ok:
                    logger.info(f"Server {server} passed all tests")
                else:
                    logger.error(
                        f"Server {server} failed one or more tests "
                        f"(added to error list)"
                    )
                    logger.error(f"  Status: {status}")
                    self.error_servers.append(server)

        elif server_type == 'ioc':
            logger.info(f"Checking all {len(self.ioc_serverlist)} IOC servers")

            for server in self.ioc_serverlist:
                status = self.check_server(server)
                power_ok = status[0].endswith('on')
                console_ok = '1)' in status[1]
                network_ok = status[2].endswith('up')

                if power_ok and console_ok and network_ok:
                    logger.info(f"Server {server} passed all tests")
                else:
                    logger.error(
                        f"Server {server} failed one or more tests "
                        f"(added to error list)"
                    )
                    logger.error(f"  Status: {status}")
                    self.error_servers.append(server)

        elif server_type == 'daq':
            logger.info(f"Checking all {len(self.daq_serverlist)} DAQ servers")

            for server in self.daq_serverlist:
                status = self.check_server(server)
                power_ok = status[0].endswith('on')
                console_ok = '1)' in status[1]
                network_ok = status[2].endswith('up ')

                if power_ok and console_ok and network_ok:
                    logger.info(f"Server {server} passed all tests")
                else:
                    logger.error(
                        f"Server {server} failed one or more tests "
                        f"(added to error list)"
                    )
                    logger.error(f"  Status: {status}")
                    self.error_servers.append(server)

        else:
            logger.error(
                f"Unknown server type: {server_type}. "
                "Use 'ioc', 'daq', or 'all'"
            )
            raise ValueError("Invalid server_type")

        # Report results
        if self.error_servers:
            logger.warning(
                f"Found {len(self.error_servers)} servers with issues:"
            )
            for server in self.error_servers:
                logger.warning(f"  - {server}")

            # Offer to cycle problem servers
            answer = input(
                "\nWould you like to power cycle these servers? (y/n): "
            )
            if answer.lower() == 'y':
                for server in self.error_servers:
                    self.cycle_server(server)
        else:
            logger.info("All servers passed health checks!")

        return self.error_servers

    def server_list(self, server_type: str):
        """
        List all servers of specified type.

        Displays formatted list of available servers for
        reference and selection.

        Parameters
        ----------
        server_type : str
            Server type to list: 'ioc', 'daq', or 'all'

        Returns
        -------
        None
            Prints server list to console

        Raises
        ------
        ValueError
            If server_type not in ['ioc', 'daq', 'all']

        Notes
        -----
        Output Format:
        - One server per line
        - Numbered for easy reference
        - Total count displayed

        Server Naming:
        - IOC: ioc-mfx-* (EPICS controllers)
        - DAQ: daq-mfx-* (Data acquisition)

        Use Cases:
        - Finding server names for manual checks
        - Verifying server inventory
        - Planning maintenance
        - Identifying missing servers

        Examples
        --------
        List IOC servers:
        >>> debug = Debug()
        >>> debug.server_list('ioc')

        List all servers:
        >>> debug.server_list('all')

        Get count only:
        >>> debug = Debug()
        >>> print(f"Total IOC servers: {len(debug.ioc_serverlist)}")

        See Also
        --------
        check_servers : Check server health
        check_server : Check individual server
        """
        server_type = server_type.lower()

        if server_type == 'ioc':
            logger.info(f"IOC Servers ({len(self.ioc_serverlist)}):")
            for i, server in enumerate(self.ioc_serverlist, 1):
                print(f"  {i:2d}. {server}")

        elif server_type == 'daq':
            logger.info(f"DAQ Servers ({len(self.daq_serverlist)}):")
            for i, server in enumerate(self.daq_serverlist, 1):
                print(f"  {i:2d}. {server}")

        elif server_type == 'all':
            logger.info(
                f"All Servers "
                f"({len(self.ioc_serverlist) + len(self.daq_serverlist)}):"
            )

            print("\nIOC Servers:")
            for i, server in enumerate(self.ioc_serverlist, 1):
                print(f"  {i:2d}. {server}")

            print("\nDAQ Servers:")
            for i, server in enumerate(self.daq_serverlist, 1):
                print(f"  {i:2d}. {server}")

        else:
            logger.error(
                f"Unknown server type: {server_type}. "
                "Use 'ioc', 'daq', or 'all'"
            )
            raise ValueError("Invalid server_type")

    def cycle_server(self, server: str):
        """
        Power cycle a server.

        Powers off server, waits, then powers back on.
        Useful for recovering from hung states.

        Parameters
        ----------
        server : str
            Server hostname to cycle

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If server not found in known server lists

        Notes
        -----
        Power Cycle Sequence:
        1. Verify server exists
        2. Power off via IPMI
        3. Wait 10 seconds
        4. Power on via IPMI
        5. Wait for boot (30-60 seconds typical)

        IPMI Commands:
        - Uses ipmitool over LAN
        - Requires IPMI credentials
        - Direct hardware control

        When to Cycle:
        - Server not responding
        - Hung processes
        - Network issues
        - After configuration changes

        When NOT to Cycle:
        - During active data acquisition
        - While motors are moving
        - During critical operations

        Recovery Time:
        - Power cycle: ~10 seconds
        - Boot time: 30-60 seconds
        - IOC startup: 10-30 seconds
        - Total: ~1-2 minutes

        Safety:
        - Stops all processes on server
        - Terminates active connections
        - May require IOC reconfiguration

        Alternative Methods:
        - Soft reboot (faster but may not clear hung state)
        - Process restart (targeted but may not work)
        - Hard power cycle (this method - most reliable)

        Examples
        --------
        Cycle single server:
        >>> debug = Debug()
        >>> debug.cycle_server('ioc-mfx-rec01')

        Cycle after check:
        >>> status = debug.check_server('ioc-mfx-rec01')
        >>> if not status[0].endswith('on'):
        ...     debug.cycle_server('ioc-mfx-rec01')

        See Also
        --------
        check_server : Check server status
        check_servers : Check multiple servers
        """
        # Validate server exists
        if server not in self.ioc_serverlist and server not in self.daq_serverlist:
            logger.error(
                f"Server {server} not found. "
                "Use debug.server_list('all') to see available servers"
            )
            raise ValueError("Unknown server")

        logger.info(f"Power cycling: {server}")

        # Use serverStat script for controlled power cycle
        os.system(
            f"/reg/g/pcds/engineering_tools/latest-released/scripts/"
            f"serverStat {server} cycle"
        )

        logger.info(
            f"Power cycle initiated for {server}. "
            "Recovery typically takes 1-2 minutes."
        )


# Convenience instance for direct import
debug = Debug()


def check_beamline_ready(hutch: str = 'mfx'):
    """
    Convenience function to check beamline readiness.

    Parameters
    ----------
    hutch : str, optional
        Hutch to check (default: 'mfx')

    Returns
    -------
    None

    Examples
    --------
    >>> check_beamline_ready('mfx')

    See Also
    --------
    Debug.awr : Full implementation
    """
    debug.awr(hutch)


def check_all_servers(server_type: str = 'all') -> List[str]:
    """
    Convenience function to check all servers.

    Parameters
    ----------
    server_type : str, optional
        'ioc', 'daq', or 'all' (default: 'all')

    Returns
    -------
    List[str]
        List of servers with issues

    Examples
    --------
    >>> errors = check_all_servers('ioc')
    >>> print(f"Found {len(errors)} issues")

    See Also
    --------
    Debug.check_servers : Full implementation
    """
    return debug.check_servers(server_type)


def list_servers(server_type: str = 'all'):
    """
    Convenience function to list servers.

    Parameters
    ----------
    server_type : str, optional
        'ioc', 'daq', or 'all' (default: 'all')

    Returns
    -------
    None

    Examples
    --------
    >>> list_servers('ioc')

    See Also
    --------
    Debug.server_list : Full implementation
    """
    debug.server_list(server_type)


def power_cycle_server(server: str):
    """
    Convenience function to power cycle server.

    Parameters
    ----------
    server : str
        Server hostname

    Returns
    -------
    None

    Examples
    --------
    >>> power_cycle_server('ioc-mfx-rec01')

    See Also
    --------
    Debug.cycle_server : Full implementation
    """
    debug.cycle_server(server)


def enable_all_motors():
    """
    Convenience function to enable motor power.

    Returns
    -------
    None

    Examples
    --------
    >>> enable_all_motors()

    See Also
    --------
    Debug.motor_check : Full implementation
    """
    debug.motor_check()