"""Laser-X-ray delay scanning utilities for pump-probe experiments at MFX beamline."""

import logging
from typing import Optional, List, Callable, Dict
from collections import defaultdict
import time

import numpy as np
import bluesky.plan_stubs as bps
import bluesky.preprocessors as bpp
from ophyd.device import Device, Component as Cpt
from ophyd.signal import EpicsSignal
from ophyd.pseudopos import PseudoPositioner, PseudoSingle
from ophyd.positioner import SoftPositioner
from scipy.constants import speed_of_light

from pcdsdaq.preprocessors import daq_during_wrapper
from pcdsdevices.interface import BaseInterface

logger = logging.getLogger(__name__)


def delay_scan(
        daq,
        time_motor,
        time_points: List[float],
        sweep_time: float,
        duration: Optional[float] = None,
        record: Optional[bool] = None,
        use_l3t: bool = False,
        controls: Optional[Dict] = None):
    """
    Bluesky plan for continuous laser-X-ray delay scans.

    Performs pump-probe delay scan by continuously sweeping timing
    motor between specified time points while collecting data with DAQ.
    Motor moves at constant velocity for smooth, artifact-free scans.

    Parameters
    ----------
    daq : Daq
        DAQ object for data collection
    time_motor : DelayNewport or similar
        Timing motor in time units (seconds)
        Must support velocity control
    time_points : List[float]
        Time points to sweep between (seconds)
        Typically two values: [start, end]
        Example: [-1e-12, 5e-12] for -1 to +5 ps
    sweep_time : float
        Duration for one complete sweep (seconds)
        Motor velocity calculated from this
    duration : float or None, optional
        Total scan duration (seconds)
        If None, runs indefinitely until stopped
    record : bool or None, optional
        Enable data recording in DAQ
        If None, uses DAQ default
    use_l3t : bool, optional
        Use level 3 trigger for event counting (default: False)
        If True, only L3T-passed events counted
    controls : dict or list, optional
        Control variables to record in DAQ data stream
        Ophyd devices whose values saved with data

    Returns
    -------
    generator
        Bluesky plan generator

    Yields
    ------
    Msg
        Bluesky messages for plan execution

    Notes
    -----
    Delay Scan Principle:

    Traditional Step Scan:
    - Move to position, wait, collect, repeat
    - Dead time between points
    - Motor settling artifacts
    - Slower overall

    Continuous Delay Scan:
    - Motor sweeps continuously
    - Constant velocity motion
    - No settling time
    - Data collected throughout
    - Faster and smoother

    Velocity Calculation:
    - Distance = |time_points[1] - time_points[0]|
    - Velocity = Distance / sweep_time
    - Applied to motor before scanning
    - Motor maintains velocity during sweep

    Time Motor Types:

    DelayNewport:
    - PseudoPositioner in time units
    - Converts time to spatial position
    - Handles real motor underneath
    - Typical: 1 mm = 6.67 ps

    Direct Stage:
    - Newport linear stage
    - Raw mm positions
    - Manual time conversion needed

    Infinite Scan Pattern:
    - Sweeps back and forth continuously
    - time_points[0] → time_points[1] → time_points[0] → ...
    - Until duration expires or interrupted
    - DAQ records throughout

    Data Collection:
    - DAQ runs in parallel with motion
    - Events timestamped
    - Time motor position in metadata
    - Post-processing bins by delay

    Timing Precision:
    - Limited by motor velocity stability
    - Position encoder resolution
    - Typical jitter: <100 fs
    - Good for ps-scale dynamics

    Use Cases:
    - Pump-probe spectroscopy
    - Time-resolved diffraction
    - Transient absorption
    - Photo-induced dynamics
    - Solution scattering

    Advantages:
    - Fast data collection
    - No settling artifacts
    - Smooth delay coverage
    - Efficient use of beam time

    Disadvantages:
    - Position uncertainty during motion
    - Requires velocity control
    - Post-processing more complex
    - Less precise than step scan

    DAQ Integration:
    - daq_during_wrapper ensures synchronization
    - DAQ starts before motion
    - Data collection parallel to scan
    - Automatic cleanup on completion

    L3T (Level 3 Trigger):
    - Additional event filtering
    - Can count only accepted events
    - Useful for specific conditions
    - May affect count rates

    Controls Recording:
    - Additional PVs to record
    - Example: temperature, pressure
    - Values stored with each event
    - Useful for correlations

    Examples
    --------
    Basic delay scan from -1 to +5 ps:
    >>> from mfx.db import daq
    >>> from mfx.devices import lxt_fast
    >>> from mfx.delay_scan import delay_scan
    >>>
    >>> # Scan parameters
    >>> time_points = [-1e-12, 5e-12]  # -1 to +5 ps
    >>> sweep_time = 2.0  # 2 seconds per sweep
    >>>
    >>> # Run scan for 60 seconds
    >>> from bluesky import RunEngine
    >>> RE = RunEngine()
    >>> RE(delay_scan(
    ...     daq,
    ...     lxt_fast,
    ...     time_points,
    ...     sweep_time,
    ...     duration=60,
    ...     record=True
    ... ))

    Infinite scan (manual stop):
    >>> RE(delay_scan(
    ...     daq,
    ...     lxt_fast,
    ...     [-2e-12, 10e-12],
    ...     sweep_time=3.0,
    ...     record=True
    ... ))
    # Press Ctrl+C to stop

    With control variables:
    >>> from mfx.db import temp_sensor, pressure_gauge
    >>> RE(delay_scan(
    ...     daq,
    ...     lxt_fast,
    ...     time_points,
    ...     sweep_time,
    ...     duration=120,
    ...     record=True,
    ...     controls={'temp': temp_sensor, 'pressure': pressure_gauge}
    ... ))

    See Also
    --------
    infinite_scan : Underlying infinite scan implementation
    DelayNewport : Time motor pseudo-positioner
    daq_during_wrapper : DAQ integration wrapper
    """
    # Convert time points to spatial positions
    # Assumes time_motor is a PseudoPositioner with time->space conversion
    spatial_pts = []
    for time_pt in time_points:
        # Get pseudo position tuple
        pseudo_tuple = time_motor.PseudoPosition(delay=time_pt)

        # Forward kinematics: time -> space
        real_tuple = time_motor.forward(pseudo_tuple)

        # Extract spatial motor position
        spatial_pts.append(real_tuple.motor)

    # Calculate required velocity
    space_delta = abs(spatial_pts[0] - spatial_pts[1])
    velo = space_delta / sweep_time

    logger.info(
        f"Delay scan setup:\n"
        f"  Time range: {time_points[0]*1e12:.3f} to {time_points[1]*1e12:.3f} ps\n"
        f"  Spatial range: {spatial_pts[0]:.6f} to {spatial_pts[1]:.6f} mm\n"
        f"  Sweep time: {sweep_time:.3f} s\n"
        f"  Velocity: {velo:.6f} mm/s"
    )

    # Set motor velocity
    yield from bps.abs_set(time_motor.motor.velocity, velo)

    # Create infinite scan plan
    scan = infinite_scan(
        [],
        time_motor,
        time_points,
        duration=duration
    )

    # Wrap with DAQ control if provided
    if daq is not None:
        logger.info("Starting delay scan with DAQ")
        yield from daq_during_wrapper(
            scan,
            record=record,
            use_l3t=use_l3t,
            controls=controls
        )
    else:
        logger.info("Starting delay scan without DAQ")
        yield from scan


def infinite_scan(
        detectors: List,
        motor,
        points: List[float],
        duration: Optional[float] = None,
        per_step: Optional[Callable] = None,
        md: Optional[Dict] = None):
    """
    Bluesky plan for infinite bidirectional scanning.

    Continuously moves motor between points in alternating directions
    until duration expires or manually stopped. Designed for continuous
    data collection during motion.

    Parameters
    ----------
    detectors : List
        List of detector objects to read
        Can be empty list if only motor motion needed
    motor
        Motor to scan
        Any Ophyd positioner
    points : List[float]
        Position points to move between
        Motor cycles through: points[0] → points[1] → points[0] → ...
    duration : float or None, optional
        Scan duration in seconds
        If None, runs indefinitely until Ctrl+C
    per_step : Callable or None, optional
        Custom function called at each step
        Signature: per_step(detectors, step, pos_cache)
        If None, uses default one_nd_step
    md : dict or None, optional
        Metadata dictionary for run
        Merged with default metadata

    Returns
    -------
    generator
        Bluesky plan generator

    Yields
    ------
    Msg
        Bluesky messages for plan execution

    Notes
    -----
    Scan Pattern:
    - Continuous bidirectional motion
    - No stops at endpoints
    - Velocity-limited motion
    - Minimal dead time

    Duration Control:
    - duration=None: Infinite until Ctrl+C
    - duration=X: Stops after X seconds
    - Clean shutdown in both cases

    Per-Step Function:
    - Called at each position
    - Can trigger readings
    - Can modify behavior
    - Default: standard step

    Metadata:
    - Motor names recorded
    - Scan type identified
    - User metadata merged
    - Available in data

    Position Cache:
    - Tracks last motor positions
    - Avoids redundant moves
    - Improves efficiency

    Decorators:
    - reset_positions: Return motors to start
    - run: Create run document
    - (stage not used: continuous motion)

    Use Cases:
    - Continuous delay scans
    - Oscillating motion patterns
    - Background-free scanning
    - Long-duration monitoring

    Examples
    --------
    Simple infinite scan:
    >>> from mfx.delay_scan import infinite_scan
    >>> from bluesky import RunEngine
    >>> from mfx.db import lxt_fast, daq
    >>>
    >>> RE = RunEngine()
    >>> RE(infinite_scan(
    ...     [daq],
    ...     lxt_fast,
    ...     [0, 100],  # mm
    ...     duration=60
    ... ))

    Infinite until stopped:
    >>> RE(infinite_scan([daq], lxt_fast, [-10, 10]))
    # Press Ctrl+C when done

    With metadata:
    >>> RE(infinite_scan(
    ...     [daq],
    ...     lxt_fast,
    ...     points=[0, 50],
    ...     duration=120,
    ...     md={'sample': 'lysozyme', 'temp': 300}
    ... ))

    See Also
    --------
    delay_scan : High-level delay scan interface
    bps.one_nd_step : Default per-step function
    """
    # Setup per-step function
    if per_step is None:
        per_step = bps.one_nd_step

    # Setup metadata
    if md is None:
        md = {}

    # Add motor names to metadata
    md.update(motors=[motor.name])

    # Record start time
    start = time.time()

    logger.info(
        f"Starting infinite scan:\n"
        f"  Motor: {motor.name}\n"
        f"  Points: {points}\n"
        f"  Duration: {duration if duration else 'infinite'} s"
    )

    # Scan decorators
    @bpp.reset_positions_decorator()
    @bpp.run_decorator(md=md)
    def inner():
        """Inner scan implementation with decorators."""
        # Position cache for efficiency
        pos_cache = defaultdict(lambda: None)

        # Continue until duration expires (or forever)
        while duration is None or time.time() - start < duration:
            # Cycle through points
            for pt in points:
                # Create step dictionary
                step = {motor: pt}

                # Execute step
                yield from per_step(detectors, step, pos_cache)

                # Check duration mid-cycle
                if duration is not None and time.time() - start >= duration:
                    logger.info("Duration expired, completing scan")
                    return

    # Execute decorated scan
    return (yield from inner())


class USBEncoder(BaseInterface, Device):
    """
    US Digital USB encoder interface.

    Provides interface to US Digital USB encoders used for
    high-resolution position feedback on timing stages.

    Components
    ----------
    zero : EpicsSignal
        Zero count command (write 1 to zero)
    pos : EpicsSignal
        Current encoder count (readback)
    scale : EpicsSignal
        Scale factor (counts to user units)
    offset : EpicsSignal
        Offset value (user units)

    Attributes
    ----------
    tab_component_names : bool
        Enable tab completion for components

    Notes
    -----
    USB Encoders:
    - High-resolution position feedback
    - Direct USB connection
    - Sub-micron resolution
    - Low latency readback

    Typical Applications:
    - Laser timing stages
    - Precision linear stages
    - Feedback for closed-loop control
    - Position verification

    Position Calculation:
    - Raw counts from encoder
    - Scaled to user units: pos * scale
    - Offset applied: (pos * scale) + offset
    - Configurable for any units

    Zeroing:
    - Sets current position as zero
    - Writes 1 to zero signal
    - Immediate effect
    - Useful for homing

    Resolution:
    - Depends on encoder model
    - Typical: 1 µm or better
    - Limited by scale factor
    - Can be sub-nanometer

    Examples
    --------
    Create encoder:
    >>> enc = USBEncoder('MFX:USDUSB4:01:CH0', name='lxt_encoder')

    Read position:
    >>> pos = enc.pos.get()
    >>> print(f"Position: {pos} counts")

    Zero encoder:
    >>> enc.set_zero()

    Read scaled position:
    >>> scale = enc.scale.get()
    >>> offset = enc.offset.get()
    >>> counts = enc.pos.get()
    >>> position = counts * scale + offset

    See Also
    --------
    DelayNewport : Motor using encoder feedback
    """

    tab_component_names = True

    zero = Cpt(
        EpicsSignal,
        ':ZEROCNT',
        kind='omitted',
        doc='Zero count command (write 1)'
    )
    pos = Cpt( EpicsSignal,
        ':POSITION',
        kind='hinted',
        doc='Encoder position (counts)'
    )
    scale = Cpt(
        EpicsSignal,
        ':SCALE',
        kind='config',
        doc='Scale factor (counts to units)'
    )
    offset = Cpt(
        EpicsSignal,
        ':OFFSET',
        kind='config',
        doc='Offset (user units)'
    )

    def set_zero(self):
        """
        Zero the encoder at current position.

        Sets the current encoder count to zero reference.
        All subsequent positions relative to this point.

        Returns
        -------
        None

        Notes
        -----
        Zeroing Process:
        - Writes 1 to ZEROCNT PV
        - Current position becomes zero
        - Immediate effect
        - Does not move motor

        Use Cases:
        - Homing procedure
        - Establishing reference
        - After manual positioning
        - Coordinate system setup

        Examples
        --------
        >>> enc = USBEncoder('MFX:USDUSB4:01:CH0', name='enc')
        >>> enc.set_zero()
        >>> pos = enc.pos.get()
        >>> print(f"Position after zero: {pos}")  # Should be 0

        See Also
        --------
        pos : Position readback
        """
        logger.info(f"Zeroing encoder: {self.name}")
        self.zero.put(1)


# Convenience functions

def quick_delay_scan(
        start_ps: float,
        end_ps: float,
        sweep_time: float = 2.0,
        duration: float = 60.0,
        record: bool = False) -> None:
    """
    Quick delay scan with minimal setup.

    Parameters
    ----------
    start_ps : float
        Starting delay in picoseconds
    end_ps : float
        Ending delay in picoseconds
    sweep_time : float, optional
        Sweep duration in seconds (default: 2.0)
    duration : float, optional
        Total scan duration in seconds (default: 60.0)
    record : bool, optional
        Enable recording (default: False)

    Returns
    -------
    None

    Notes
    -----
    Simplified Interface:
    - Uses default lxt_fast motor
    - Converts ps to seconds automatically
    - Uses standard DAQ
    - Minimal parameters

    Examples
    --------
    Scan -1 to +5 ps for 1 minute:
    >>> from mfx.delay_scan import quick_delay_scan
    >>> quick_delay_scan(-1, 5, duration=60, record=True)

    Fast sweep:
    >>> quick_delay_scan(0, 10, sweep_time=1.0, duration=30)

    See Also
    --------
    delay_scan : Full control interface
    """
    from bluesky import RunEngine
    from mfx.db import daq, lxt_fast

    # Convert ps to seconds
    time_points = [start_ps * 1e-12, end_ps * 1e-12]

    logger.info(
        f"Quick delay scan: {start_ps} to {end_ps} ps "
        f"for {duration} s"
    )

    # Create and run plan
    RE = RunEngine()
    RE(delay_scan(
        daq,
        lxt_fast,
        time_points,
        sweep_time,
        duration=duration,
        record=record
    ))


def calculate_sweep_velocity(
        start_mm: float,
        end_mm: float,
        sweep_time: float) -> float:
    """
    Calculate required motor velocity for delay scan.

    Parameters
    ----------
    start_mm : float
        Starting position (mm)
    end_mm : float
        Ending position (mm)
    sweep_time : float
        Desired sweep time (seconds)

    Returns
    -------
    float
        Required velocity (mm/s)

    Examples
    --------
    >>> from mfx.delay_scan import calculate_sweep_velocity
    >>> vel = calculate_sweep_velocity(0, 100, 2.0)
    >>> print(f"Velocity: {vel} mm/s")
    50.0 mm/s

    See Also
    --------
    delay_scan : Uses this calculation
    """
    distance = abs(end_mm - start_mm)
    velocity = distance / sweep_time

    logger.info(
        f"Sweep calculation:\n"
        f"  Distance: {distance:.3f} mm\n"
        f"  Time: {sweep_time:.3f} s\n"
        f"  Velocity: {velocity:.6f} mm/s"
    )

    return velocity


def time_to_space(
        delay_ps: float,
        speed_factor: float = 2.0) -> float:
    """
    Convert time delay to spatial stage position.

    Parameters
    ----------
    delay_ps : float
        Time delay in picoseconds
    speed_factor : float, optional
        Factor for double-pass geometry (default: 2.0)
        2.0 for retroreflector (light travels twice)
        1.0 for single pass

    Returns
    -------
    float
        Stage position in millimeters

    Notes
    -----
    Conversion Formula:
    - c = speed of light (m/s)
    - distance (m) = delay (s) × c / speed_factor
    - Convert to mm

    Double-Pass:
    - Light reflects back
    - Effective speed = c/2
    - Factor = 2.0

    Single-Pass:
    - Direct beam path
    - Effective speed = c
    - Factor = 1.0

    Examples
    --------
    Convert 10 ps delay:
    >>> from mfx.delay_scan import time_to_space
    >>> pos = time_to_space(10)  # ps
    >>> print(f"Position: {pos:.6f} mm")

    Single-pass geometry:
    >>> pos = time_to_space(10, speed_factor=1.0)

    See Also
    --------
    space_to_time : Inverse conversion
    """
    # Convert ps to seconds
    delay_s = delay_ps * 1e-12

    # Calculate distance in meters
    distance_m = delay_s * speed_of_light / speed_factor

    # Convert to mm
    distance_mm = distance_m * 1000

    return distance_mm


def space_to_time(
        position_mm: float,
        speed_factor: float = 2.0) -> float:
    """
    Convert spatial stage position to time delay.

    Parameters
    ----------
    position_mm : float
        Stage position in millimeters
    speed_factor : float, optional
        Factor for geometry (default: 2.0)
        2.0 for double-pass
        1.0 for single-pass

    Returns
    -------
    float
        Time delay in picoseconds

    Examples
    --------
    Convert 100 mm position:
    >>> from mfx.delay_scan import space_to_time
    >>> delay = space_to_time(100)
    >>> print(f"Delay: {delay:.3f} ps")

    See Also
    --------
    time_to_space : Forward conversion
    """
    # Convert mm to meters
    distance_m = position_mm / 1000

    # Calculate delay in seconds
    delay_s = distance_m * speed_factor / speed_of_light

    # Convert to ps
    delay_ps = delay_s * 1e12

    return delay_ps


# Module initialization
logger.info("Delay scan utilities loaded for pump-probe experiments")