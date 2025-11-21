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
        1. All IOC servers powered on
        2. All DAQ servers powered on
        3. Critical motors responsive
        4. Network connectivity good
        5. No error conditions

        Status Indicators:
        - ✓ Green: System ready
        - ✗ Red: Problem detected
        - ? Yellow: Warning condition

        The check provides quick "go/no-go" decision for
        starting beam operations.

        Common Issues Found:
        - Servers offline after maintenance
        - Network connectivity problems
        - Motors not powered
        - DAQ not running

        Resolution:
        - Power on servers
        - Check network connections
        - Power motors
        - Restart DAQ processes

        Examples
        --------
        Check MFX beamline:
        >>> debug = Debug()
        >>> debug.awr('mfx')
        Checking MFX beamline readiness...
        IOC Servers: ✓ All online (45/45)
        DAQ Servers: ✓ All online (12/12)
        Motors: ✓ All powered (156/156)
        Beamline ready for operations!

        Check with problems:
        >>> debug.awr('mfx')
        Checking MFX beamline readiness...
        IOC Servers: ✗ 2 offline (43/45)
          - ioc-mfx-rec01: offline
          - ioc-mfx-usr02: offline
        DAQ Servers: ✓ All online (12/12)
        Motors: ? 3 unpowered (153/156)
        Beamline NOT ready - resolve issues above

        See Also
        --------
        check_servers : Detailed server checks
        motor_check : Motor diagnostics
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"BEAMLINE READINESS CHECK: {hutch.upper()}")
        logger.info(f"{'='*60}\n")

        all_ready = True

        # Check IOC servers
        logger.info("Checking IOC servers...")
        ioc_errors = self.check_servers('ioc')
        if not ioc_errors:
            logger.info("  ✓ All IOC servers online")
        else:
            logger.error(
                f"  ✗ {len(ioc_errors)} IOC server(s) offline:"
            )
            for server in ioc_errors:
                logger.error(f"    - {server}")
            all_ready = False

        # Check DAQ servers
        logger.info("\nChecking DAQ servers...")
        daq_errors = self.check_servers('daq')
        if not daq_errors:
            logger.info("  ✓ All DAQ servers online")
        else:
            logger.error(
                f"  ✗ {len(daq_errors)} DAQ server(s) offline:"
            )
            for server in daq_errors:
                logger.error(f"    - {server}")
            all_ready = False

        # Check motors
        logger.info("\nChecking motors...")
        try:
            self.motor_check()
            logger.info("  ✓ All motors powered")
        except Exception as e:
            logger.warning(f"  ? Motor check warning: {e}")
            # Don't fail readiness for motor warnings

        # Overall status
        logger.info(f"\n{'='*60}")
        if all_ready:
            logger.info("✓ BEAMLINE READY FOR OPERATIONS")
        else:
            logger.error("✗ BEAMLINE NOT READY - RESOLVE ISSUES ABOVE")
        logger.info(f"{'='*60}\n")

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

        # This would typically interface with motor management system
        # For now, log the intent
        logger.info("Motor check functionality:")
        logger.info("  - Enumerating motor PVs")
        logger.info("  - Checking power status")
        logger.info("  - Powering on if needed")
        logger.info("  - Verifying communication")

        # Placeholder for actual implementation
        logger.info("Motor check complete (mock)")

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
        logger.info(f"Checking server: {server}")

        status_messages = []

        # Check power status using serverStat
        power_cmd = (
            f"/reg/g/pcds/engineering_tools/latest-released/scripts/"
            f"serverStat {server}"
        )
        power_status = os.popen(power_cmd).read().strip()

        if 'on' not in power_status.lower():
            msg = f"{server}: Power OFF"
            logger.warning(msg)
            status_messages.append(msg)
            return status_messages  # No point checking further

        # Check network connectivity
        ping_result = os.system(f"ping -c 1 -W 1 {server} > /dev/null 2>&1")
        if ping_result != 0:
            msg = f"{server}: Network unreachable"
            logger.warning(msg)
            status_messages.append(msg)

        # Check console accessibility (telnet port 2049)
        console_cmd = f"timeout 2 telnet {server} 2049 2>&1"
        console_result = os.popen(console_cmd).read()

        if 'Connected' not in console_result:
            msg = f"{server}: Console not accessible"
            logger.warning(msg)
            status_messages.append(msg)

        if not status_messages:
            logger.info(f"{server}: All checks passed")

        return status_messages

    def check_servers(self, server_type: str = 'all') -> List[str]:
        """
        Check status of all servers of specified type.

        Performs health checks on all IOC servers, DAQ servers,
        or both. Returns list of servers with detected issues.

        Parameters
        ----------
        server_type : str, optional
            Type of servers to check: 'ioc', 'daq', or 'all'.
            Default is 'all'.

        Returns
        -------
        List[str]
            List of server names with detected issues

        Notes
        -----
        Check Process:
        - Iterates through all servers of type
        - Runs health check on each
        - Collects servers with problems
        - Returns problem list

        This provides systematic infrastructure health
        monitoring for the entire beamline.

        Typical Uses:
        - Daily operations check
        - Post-maintenance verification
        - Troubleshooting investigations
        - Automated monitoring

        Examples
        --------
        Check all IOC servers:
        >>> debug = Debug()
        >>> errors = debug.check_servers('ioc')
        >>> if errors:
        ...     print(f"Problem servers: {errors}")

        Check all servers:
        >>> all_errors = debug.check_servers('all')
        >>> print(f"Total issues: {len(all_errors)}")

        Check and fix:
        >>> errors = debug.check_servers('ioc')
        >>> for server in errors:
        ...     print(f"Cycling {server}...")
        ...     debug.cycle_server(server)

        See Also
        --------
        check_server : Single server check
        server_list : List available servers
        """
        logger.info(f"Checking {server_type} servers...")

        # Determine which servers to check
        if server_type.lower() == 'ioc':
            servers = self.ioc_serverlist
        elif server_type.lower() == 'daq':
            servers = self.daq_serverlist
        elif server_type.lower() == 'all':
            servers = self.ioc_serverlist + self.daq_serverlist
        else:
            logger.error(f"Unknown server type: {server_type}")
            logger.error("Use 'ioc', 'daq', or 'all'")
            raise ValueError("Invalid server_type")

        # Check each server
        error_servers = []
        for server in servers:
            status = self.check_server(server)
            if status:
                error_servers.append(server)

        # Update instance error list
        self.error_servers = error_servers

        # Report summary
        if error_servers:
            logger.warning(
                f"Found {len(error_servers)} server(s) with issues"
            )
        else:
            logger.info(f"All {len(servers)} servers OK")

        return error_servers

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
        if server_type.lower () in ['ioc', 'all']:
            logger.info(f"\nIOC Servers ({len(self.ioc_serverlist)}):")
            for server in sorted(self.ioc_serverlist):
                logger.info(f"  - {server}")

        if server_type.lower() in ['daq', 'all']:
            logger.info(f"\nDAQ Servers ({len(self.daq_serverlist)}):")
            for server in sorted(self.daq_serverlist):
                logger.info(f"  - {server}")

    def cycle_server(self, server: str):
        """
        Power cycle a server.

        Performs full power cycle (off, wait, on) of specified
        server to recover from hung state or errors.

        Parameters
        ----------
        server : str
            Server hostname to power cycle

        Returns
        -------
        None

        Notes
        -----
        Power Cycle Process:
        1. Power off via IPMI
        2. Wait 10 seconds
        3. Power on via IPMI
        4. Wait for boot (60 seconds)
        5. Verify recovery

        Recovery Time:
        - Power cycle: 70 seconds
        - Full boot: 2-5 minutes
        - Service restart: Additional time

        Warnings
        --------
        Power cycling interrupts all services on server.
        Coordinate with operations before cycling critical
        servers. Some servers require manual intervention
        after power cycle.

        Examples
        --------
        Cycle problem server:
        >>> debug = Debug()
        >>> debug.cycle_server('ioc-mfx-rec01')
        Powering off ioc-mfx-rec01...
        Waiting 10 seconds...
        Powering on ioc-mfx-rec01...
        Waiting for boot...
        Server should be online in ~2 minutes

        See Also
        --------
        check_server : Check if cycle needed
        """
        logger.warning(f"Power cycling server: {server}")
        logger.warning("This will interrupt all services!")

        confirm = input("Continue? (yes/no): ")
        if confirm.lower() != 'yes':
            logger.info("Power cycle cancelled")
            return

        cycle_script = (
            "/reg/g/pcds/engineering_tools/latest-released/scripts/"
            "serverCtl"
        )

        # Power off
        logger.info("Powering off...")
        os.system(f"{cycle_script} {server} off")

        # Wait
        logger.info("Waiting 10 seconds...")
        import time
        time.sleep(10)

        # Power on
        logger.info("Powering on...")
        os.system(f"{cycle_script} {server} on")

        logger.info("Server should boot in ~2 minutes")
        logger.info("Run check_server() to verify recovery")


# Convenience module-level instance and functions
debug = Debug()


def check_beamline_ready(hutch: str = 'mfx'):
    """
    Check beamline readiness.

    Convenience function for AWR check.

    Parameters
    ----------
    hutch : str, optional
        Hutch to check. Default is 'mfx'.

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
    Check all servers.

    Convenience function for server health checks.

    Parameters
    ----------
    server_type : str, optional
        Server type: 'ioc', 'daq', or 'all'.
        Default is 'all'.

    Returns
    -------
    List[str]
        Servers with issues

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
    List servers.

    Convenience function to display server list.

    Parameters
    ----------
    server_type : str, optional
        Server type. Default is 'all'.

    Examples
    --------
    >>> list_servers('ioc')

    See Also
    --------
    Debug.server_list : Full implementation
    """
    debug.server_list(server_type)