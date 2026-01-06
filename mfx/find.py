"""
Device and signal discovery utilities for MFX beamline.

Provides functions to locate and retrieve motor and signal objects by
PV name, enabling dynamic device access and scripting flexibility.
"""

import logging
from typing import Optional

import ophyd
from ophyd.signal import EpicsSignal
from pcdsdevices.epics_motor import EpicsMotorInterface as Motor
from pcdsdevices.pv_positioner import OnePVMotor

import mfx.db

logger = logging.getLogger(__name__)


class Find:
    """
    Device discovery and retrieval utilities.

    Provides methods to locate motors and signals by PV name,
    with intelligent caching and reuse of existing instances.

    Methods
    -------
    get_motor_by_pvname(pvname)
        Retrieve or create motor by PV name
    get_signal_by_pvname(pvname)
        Retrieve or create EPICS signal by PV name
    get_signal_motor_by_pvname(pvname)
        Retrieve or create OnePVMotor by PV name

    Attributes
    ----------
    _motor_cache : dict
        Cache of created motor objects
    _pv_cache : dict
        Cache of created signal objects
    _pv_motor_cache : dict
        Cache of created OnePVMotor objects

    Notes
    -----
    Device Discovery:

    Search Strategy:
    1. Check existing devices in mfx.db
    2. Check instance cache
    3. Create new instance if not found
    4. Cache for future requests

    Caching Benefits:
    - Reuses existing connections
    - Prevents duplicate objects
    - Maintains single source of truth
    - Improves performance

    PV Name Format:
    - Standard EPICS naming convention
    - Must be complete base PV
    - Examples:
      - Motor: 'MFX:USR:MMS:17'
      - Signal: 'MFX:USR:ai1'
      - Not relative or partial names

    Use Cases:
    - Scripting with dynamic PV names
    - User-specified motor control
    - Configuration file driven setups
    - Temporary device access
    - Interactive exploration

    Motor Types:
    - EpicsMotorInterface: Standard motors
    - OnePVMotor: Single-PV positioners
    - Cached separately by type

    Performance:
    - First access: Creates connection (~1 sec)
    - Subsequent access: Instant from cache
    - Network efficient

    Examples
    --------
    Create finder:
    >>> finder = Find()

    Find existing motor:
    >>> motor = finder.get_motor_by_pvname('MFX:USR:MMS:17')
    >>> print(motor.position)

    Get signal:
    >>> signal = finder.get_signal_by_pvname('MFX:USR:ai1')
    >>> value = signal.get()

    Get OnePVMotor:
    >>> motor = finder.get_signal_motor_by_pvname('MFX:DG2:MMS:06')
    >>> motor.move(10.0)

    Dynamic motor access:
    >>> pv_name = input("Enter motor PV: ")
    >>> motor = finder.get_motor_by_pvname(pv_name)
    >>> print(f"Motor at {motor.position}")

    See Also
    --------
    mfx.db : Database of beamline devices
    """

    def __init__(self):
        """
        Initialize Find utility.

        Sets up empty caches for discovered devices.
        """
        # Private caches for created objects
        self._motor_cache = {}
        self._pv_cache = {}
        self._pv_motor_cache = {}

        logger.info("Find utility initialized")

    def get_motor_by_pvname(self, pvname: str) -> Motor:
        """
        Get motor object by PV name.

        Searches existing motors in mfx.db, then cache, finally
        creates new instance if needed.

        Parameters
        ----------
        pvname : str
            Base PV name of motor (e.g., 'MFX:USR:MMS:17')

        Returns
        -------
        Motor
            EpicsMotorInterface object for the motor

        Notes
        -----
        Search Process:
        1. Strip whitespace from PV name
        2. Search all motors in mfx.db.motors
        3. If found, return existing instance
        4. Check _motor_cache
        5. If not cached, create new Motor instance
        6. Cache and return

        Motor Properties:
        - Full EPICS motor record
        - Position, velocity, limits
        - Status and alarms
        - Move commands

        Cache Key:
        - Stripped PV name
        - Case sensitive
        - Must match exactly

        New Instance Creation:
        - Creates EpicsMotorInterface
        - Name = PV name
        - Establishes EPICS connection
        - May take ~1 second first time

        Warnings
        --------
        PV must be valid EPICS motor record.
        Invalid PV will create object but operations will fail.
        Check motor.connected before using.

        Examples
        --------
        Get existing motor from beamline:
        >>> finder = Find()
        >>> motor = finder.get_motor_by_pvname('MFX:USR:MMS:17')
        >>> print(f"Position: {motor.position}")

        Get motor and move:
        >>> motor = finder.get_motor_by_pvname('MFX:DG1:MMS:01')
        >>> motor.move(10.0, wait=True)

        Check if motor exists:
        >>> motor = finder.get_motor_by_pvname('MFX:USR:MMS:99')
        >>> if motor.connected:
        ...     print("Motor online")
        ... else:
        ...     print("Motor not found or offline")

        Cached access (fast):
        >>> motor1 = finder.get_motor_by_pvname('MFX:USR:MMS:17')
        >>> motor2 = finder.get_motor_by_pvname('MFX:USR:MMS:17')
        >>> assert motor1 is motor2  # Same object

        See Also
        --------
        get_signal_motor_by_pvname : For single-PV motors
        mfx.db.motors : List of beamline motors
        """
        # Strip whitespace
        pvname = pvname.strip()

        # Search existing motors in beamline database
        for motor in mfx.db.motors:
            try:
                if motor.prefix == pvname:
                    logger.debug(f"Found existing motor: {pvname}")
                    return motor
            except AttributeError:
                # Motor doesn't have prefix attribute
                continue

        # Check cache
        if pvname in self._motor_cache:
            logger.debug(f"Found motor in cache: {pvname}")
            return self._motor_cache[pvname]

        # Create new motor instance
        logger.info(f"Creating new motor: {pvname}")
        new_motor = Motor(pvname, name=pvname)

        # Cache for future use
        self._motor_cache[pvname] = new_motor

        return new_motor

    def get_signal_by_pvname(self, pvname: str) -> ophyd.EpicsSignal:
        """
        Get EPICS signal object by PV name.

        Searches existing signals in mfx.db, then cache, finally
        creates new instance if needed.

        Parameters
        ----------
        pvname : str
            Complete EPICS PV name (e.g., 'MFX:USR:ai1')

        Returns
        -------
        ophyd.EpicsSignal
            EpicsSignal object for the PV

        Notes
        -----
        Search Process:
        1. Strip whitespace from PV name
        2. Search all signals in mfx.db.a (all ophyd objects)
        3. Check for matching setpoint_pvname attribute
        4. If found, return existing instance
        5. Check _pv_cache
        6. If not cached, create new EpicsSignal
        7. Cache and return

        Signal Types:
        - Analog inputs (ai)
        - Analog outputs (ao)
        - Binary inputs (bi)
        - Binary outputs (bo)
        - String records (stringin/stringout)
        - Waveform records
        - Any EPICS PV

        Signal Operations:
        - get(): Read current value
        - put(value): Write new value
        - subscribe(): Monitor for changes
        - Full Ophyd signal interface

        Cache Key:
        - Stripped PV name
        - Case sensitive
        - Full PV required

        New Instance Creation:
        - Creates EpicsSignal
        - Name = PV name
        - Establishes CA/PVA connection
        - Connection happens lazily

        Warnings
        --------
        PV must exist in EPICS.
        Invalid PV will create object but operations will timeout.
        Check signal.connected before using.

        Examples
        --------
        Get analog input:
        >>> finder = Find()
        >>> signal = finder.get_signal_by_pvname('MFX:DG1:BMMON:SUM')
        >>> intensity = signal.get()
        >>> print(f"Beam intensity: {intensity}")

        Write to output:
        >>> signal = finder.get_signal_by_pvname('MFX:USR:ao1')
        >>> signal.put(5.0)

        Subscribe to changes:
        >>> def callback(value, **kwargs):
        ...     print(f"New value: {value}")
        >>> signal = finder.get_signal_by_pvname('MFX:USR:ai1')
        >>> signal.subscribe(callback)

        Check connection:
        >>> signal = finder.get_signal_by_pvname('MFX:INVALID:PV')
        >>> if signal.connected:
        ...     value = signal.get()
        ... else:
        ...     print("PV not found")

        Cached access:
        >>> sig1 = finder.get_signal_by_pvname('MFX:USR:ai1')
        >>> sig2 = finder.get_signal_by_pvname('MFX:USR:ai1')
        >>> assert sig1 is sig2  # Same object

        See Also
        --------
        get_motor_by_pvname : For motor records
        EpicsSignal : Ophyd signal documentation
        """
        # Strip whitespace
        pvname = pvname.strip()

        # Search existing signals in beamline database
        # mfx.db.a contains all ophyd objects
        for sig in mfx.db.a:
            # Check if signal has setpoint_pvname attribute and it matches
            if getattr(sig, "setpoint_pvname", None) == pvname:
                logger.debug(f"Found existing signal: {pvname}")
                return sig

        # Check cache
        if pvname in self._pv_cache:
            logger.debug(f"Found signal in cache: {pvname}")
            return self._pv_cache[pvname]

        # Create new signal instance
        logger.info(f"Creating new signal: {pvname}")
        new_signal = EpicsSignal(pvname, name=pvname)

        # Cache for future use
        self._pv_cache[pvname] = new_signal

        return new_signal

    def get_signal_motor_by_pvname(self, pvname: str) -> OnePVMotor:
        """
        Get OnePVMotor object by PV name.

        Creates or retrieves single-PV motor object for simple
        positioners that use one PV for both setpoint and readback.

        Parameters
        ----------
        pvname : str
            PV name for motor control (e.g., 'MFX:DG2:MMS:06')

        Returns
        -------
        OnePVMotor
            OnePVMotor object for the PV

        Notes
        -----
        OnePVMotor vs. EpicsMotor:

        OnePVMotor:
        - Single PV for setpoint
        - No separate readback
        - Simpler hardware
        - Common for basic positioners
        - Uses .VAL field implicitly

        EpicsMotor:
        - Full motor record
        - Separate RBV field
        - Velocity, limits, status
        - Standard for precision motors

        Use OnePVMotor for:
        - Simple analog outputs used as motors
        - DAQ motor scans (bluesky)
        - Devices without full motor record
        - Quick position control

        Cache Management:
        - Separate cache from motors and signals
        - Keyed by PV name
        - Returns cached instance if exists
        - Creates new if not found

        Bluesky Integration:
        - OnePVMotor compatible with bluesky plans
        - Used for DAQ motor scans
        - Simpler than full motor objects

        Warnings
        --------
        PV should be writable (typically .ao or motor .VAL).
        No position verification - writes value and returns.
        No limits checking unless PV implements them.

        Examples
        --------
        Create OnePVMotor:
        >>> finder = Find()
        >>> motor = finder.get_signal_motor_by_pvname('MFX:DG2:MMS:06')

        Use in motion:
        >>> motor.move(10.0, wait=True)
        >>> print(f"Position: {motor.position}")

        Use in bluesky scan:
        >>> from bluesky.plans import scan
        >>> from bluesky import RunEngine
        >>> RE = RunEngine()
        >>> motor = finder.get_signal_motor_by_pvname('MFX:USR:ao1')
        >>> RE(scan([detector], motor, 0, 10, 11))

        Cached access:
        >>> m1 = finder.get_signal_motor_by_pvname('MFX:DG2:MMS:06')
        >>> m2 = finder.get_signal_motor_by_pvname('MFX:DG2:MMS:06')
        >>> assert m1 is m2  # Same object

        Check setpoint PV:
        >>> motor = finder.get_signal_motor_by_pvname('MFX:USR:ao1')
        >>> print(motor.setpoint.pvname)
        MFX:USR:ao1

        See Also
        --------
        get_motor_by_pvname : For full motor records
        OnePVMotor : Ophyd OnePVMotor documentation
        """
        # Strip whitespace
        pvname = pvname.strip()

        # Check cache
        if pvname in self._pv_motor_cache:
            logger.debug(f"Found OnePVMotor in cache: {pvname}")
            return self._pv_motor_cache[pvname]

        # Create new OnePVMotor instance
        logger.info(f"Creating new OnePVMotor: {pvname}")
        new_motor = OnePVMotor(pvname, name=pvname)

        # Cache for future use
        self._pv_motor_cache[pvname] = new_motor

        return new_motor


# Convenience module-level instance
find = Find()


def get_motor(pvname: str) -> Motor:
    """
    Get motor by PV name (convenience function).

    Parameters
    ----------
    pvname : str
        Motor PV name

    Returns
    -------
    Motor
        Motor object

    Examples
    --------
    >>> motor = get_motor('MFX:USR:MMS:17')
    >>> motor.move(10.0)

    See Also
    --------
    Find.get_motor_by_pvname : Full implementation
    """
    return find.get_motor_by_pvname(pvname)


def get_signal(pvname: str) -> EpicsSignal:
    """
    Get signal by PV name (convenience function).

    Parameters
    ----------
    pvname : str
        Signal PV name

    Returns
    -------
    EpicsSignal
        Signal object

    Examples
    --------
    >>> signal = get_signal('MFX:USR:ai1')
    >>> value = signal.get()

    See Also
    --------
    Find.get_signal_by_pvname : Full implementation
    """
    return find.get_signal_by_pvname(pvname)


def get_positioner(pvname: str) -> OnePVMotor:
    """
    Get OnePVMotor by PV name (convenience function).

    Parameters
    ----------
    pvname : str
        Positioner PV name

    Returns
    -------
    OnePVMotor
        OnePVMotor object

    Examples
    --------
    >>> motor = get_positioner('MFX:DG2:MMS:06')
    >>> motor.move(5.0)

    See Also
    --------
    Find.get_signal_motor_by_pvname : Full implementation
    """
    return find.get_signal_motor_by_pvname(pvname)


logger.info("Device discovery utilities loaded and ready")