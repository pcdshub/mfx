"""
Laser-X-ray delay scanning for pump-probe experiments at MFX beamline.

Provides continuous delay scanning capabilities for time-resolved
studies, with automatic velocity control and DAQ synchronization.
"""

import logging
from typing import Optional, List, Dict
from time import time, sleep

import numpy as np
import bluesky.plan_stubs as bps
import bluesky.preprocessors as bpp
from ophyd.device import Device, Component as Cpt
from ophyd.signal import EpicsSignal
from ophyd.pseudopos import (PseudoPositioner, PseudoSingle,
                              pseudo_position_argument,
                              real_position_argument)
from ophyd.positioner import SoftPositioner
from scipy.constants import speed_of_light

from pcdsdaq.preprocessors import daq_during_wrapper
from pcdsdevices.interface import BaseInterface

logger = logging.getLogger(__name__)


def delay_scan(
        daq,
        time_motor,
        time_points,
        sweep_time,
        duration=None,
        record=None,
        use_l3t=False,
        controls=None):
    """
    Bluesky plan for continuous laser-X-ray delay scans.

    Performs pump-probe delay scan by continuously sweeping timing
    motor between specified time points while collecting data with
    DAQ. Motor moves at constant velocity for smooth, artifact-free
    scans.

    Parameters
    ----------
    daq : Daq
        DAQ object for data collection (pcdsdaq.daq.Daq instance)
    time_motor : DelayNewport or similar
        Timing motor in time units (seconds).
        Must support velocity control.
        Typical: DelayNewport, DelayBase, or similar
    time_points : list of float
        Time points to sweep between in seconds.
        Typically two values: [start, end]
        Example: [-1e-12, 5e-12] for -1 to +5 ps
        Can use more points for complex trajectories
    sweep_time : float
        Duration for one complete sweep in seconds.
        Motor velocity calculated from this value.
        Example: 2.0 for 2-second sweep
    duration : float or None, optional
        Total scan duration in seconds.
        If None, runs indefinitely until manual stop (Ctrl+C).
        If specified, stops after this time.
        Default is None (infinite).
    record : bool or None, optional
        Enable data recording in DAQ.
        If None, uses DAQ default setting.
        If True, forces recording on.
        If False, forces recording off (test mode).
        Default is None.
    use_l3t : bool, optional
        Use Level 3 trigger for event counting.
        If True, only L3T-passed events counted.
        If False, counts all events.
        Default is False.
    controls : dict or list, optional
        Control variables to record in DAQ data stream.
        Can be dict mapping names to Ophyd signals, or
        list of Ophyd signals.
        Values saved with each event for correlation.
        Default is None (no extra controls).

    Yields
    ------
    Msg
        Bluesky messages for plan execution

    Returns
    -------
    generator
        Bluesky plan generator

    Raises
    ------
    KeyboardInterrupt
        User interruption (Ctrl+C) stops scan gracefully

    Notes
    -----
    Delay Scan Principle:

    Traditional Step Scan:
    - Move to position, wait, collect, repeat
    - Dead time between points
    - Motor settling artifacts
    - Slower overall

    Continuous Delay Scan:
    - Motor sweeps continuously at constant velocity
    - DAQ records during entire motion
    - No settling time needed
    - More efficient use of beam time
    - Smoother data with fewer artifacts

    Advantages:
    - Faster data collection
    - Better statistics per time
    - No motor settling artifacts
    - Continuous sampling

    Disadvantages:
    - Position uncertainty during motion
    - Requires velocity control
    - Post-processing more complex
    - Less precise than step scan

    Velocity Calculation:
    - distance = max(time_points) - min(time_points)
    - velocity = distance / sweep_time
    - Motor commanded to this velocity

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

    Scan Duration:
    - If duration=None: infinite loop
    - User stops with Ctrl+C
    - Graceful cleanup on interrupt
    - If duration specified: auto-stop

    Warnings
    --------
    - Motor must support velocity control
    - Very fast sweeps may exceed motor limits
    - Position readback less precise during motion
    - Always test with record=False first

    Examples
    --------
    Basic delay scan from -1 to +5 ps:
    >>> from mfx.db import daq
    >>> from mfx.devices import lxt_fast
    >>> from mfx.delay_scan import delay_scan
    >>> from bluesky import RunEngine
    >>>
    >>> RE = RunEngine()
    >>> time_points = [-1e-12, 5e-12]  # -1 to +5 ps
    >>> sweep_time = 2.0  # 2 seconds per sweep
    >>>
    >>> # Run for 60 seconds
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

    With L3T filtering:
    >>> RE(delay_scan(
    ...     daq,
    ...     lxt_fast,
    ...     [-1e-12, 5e-12],
    ...     2.0,
    ...     duration=120,
    ...     record=True,
    ...     use_l3t=True
    ... ))

    With control PVs:
    >>> from ophyd import EpicsSignal
    >>> temp = EpicsSignal('MFX:TEMP:01', name='temperature')
    >>> RE(delay_scan(
    ...     daq,
    ...     lxt_fast,
    ...     [-1e-12, 5e-12],
    ...     2.0,
    ...     duration=60,
    ...     record=True,
    ...     controls=[temp]
    ... ))

    Test mode without recording:
    >>> RE(delay_scan(
    ...     daq,
    ...     lxt_fast,
    ...     [0, 5e-12],
    ...     1.0,
    ...     duration=10,
    ...     record=False
    ... ))

    See Also
    --------
    quick_delay_scan : Simplified interface for common use
    DelayNewport : Timing motor device
    daq_during_wrapper : DAQ synchronization wrapper
    """
    logger.info("="*60)
    logger.info("CONTINUOUS DELAY SCAN")
    logger.info("="*60)
    logger.info(f"Time points: {time_points} s")
    logger.info(f"Sweep time: {sweep_time} s")
    logger.info(f"Duration: {duration if duration else 'infinite'}")
    logger.info(f"Recording: {record}")
    logger.info("="*60)

    # Calculate sweep parameters
    time_array = np.array(time_points)
    min_time = time_array.min()
    max_time = time_array.max()
    time_range = max_time - min_time

    # Calculate required velocity
    velocity = time_range / sweep_time
    logger.info(f"Time range: {time_range*1e12:.2f} ps")
    logger.info(f"Velocity: {velocity*1e12:.2e} ps/s")

    # Configure motor velocity
    logger.info(f"Setting {time_motor.name} velocity...")
    original_velocity = time_motor.velocity.get()
    yield from bps.abs_set(time_motor.velocity, abs(velocity), wait=True)

    # Wrap scan with DAQ recording
    @bpp.run_decorator()
    def inner_scan():
        """Inner scan logic with DAQ recording."""
        start_time = time()

        # Continuous sweep loop
        while True:
            # Check duration limit
            if duration is not None:
                elapsed = time() - start_time
                if elapsed >= duration:
                    logger.info(
                        f"Duration limit reached: {elapsed:.1f}s"
                    )
                    break

            # Sweep forward
            logger.debug(f"Sweeping to {max_time*1e12:.2f} ps")
            yield from bps.mv(time_motor, max_time)

            # Sweep backward
            logger.debug(f"Sweeping to {min_time*1e12:.2f} ps")
            yield from bps.mv(time_motor, min_time)

    # Execute scan with DAQ
    try:
        logger.info("Starting continuous delay scan...")
        logger.info("Press Ctrl+C to stop")

        yield from daq_during_wrapper(
            inner_scan(),
            daq=daq,
            record=record,
            use_l3t=use_l3t,
            controls=controls
        )

    except KeyboardInterrupt:
        logger.warning("\nScan interrupted by user")

    finally:
        # Restore original velocity
        logger.info("Restoring original motor velocity...")
        yield from bps.abs_set(
            time_motor.velocity,
            original_velocity,
            wait=True
        )
        logger.info("Delay scan complete")


class DelayNewport(PseudoPositioner):
    """
    Laser delay stage with time-based positioning.

    Converts between physical motor position (mm) and time delay (s)
    for laser-X-ray timing control in pump-probe experiments.

    Components
    ----------
    delay : PseudoSingle
        Time delay in seconds (pseudo axis)
    motor : Motor
        Physical motor position in mm (real axis)

    Attributes
    ----------
    c : float
        Speed of light in mm/s (299792458000.0)

    Methods
    -------
    forward(pseudo_pos)
        Convert time delay to motor position
    inverse(real_pos)
        Convert motor position to time delay

    Notes
    -----
    Position Conversion:
    - Laser path length changes by moving motor
    - Time delay = 2 * distance / speed_of_light
    - Factor of 2 from double-pass geometry

    Double-Pass Geometry:
    - Laser reflects and returns
    - Each mm of motion = 2 mm path change
    - Provides finer time resolution

    Typical Parameters:
    - Motor range: ±100 mm
    - Time range: ±0.67 ns
    - Resolution: ~0.01 ps

    Examples
    --------
    Create delay stage:
    >>> delay = DelayNewport('MFX:DELAY', name='lxt_fast')

    Move to time delay:
    >>> delay.delay.move(5e-12)  # Move to +5 ps

    Read current delay:
    >>> current_delay = delay.delay.position
    >>> print(f"Current delay: {current_delay*1e12:.2f} ps")

    Use in delay scan:
    >>> from mfx.delay_scan import delay_scan
    >>> RE(delay_scan(daq, delay, [-1e-12, 5e-12], 2.0))

    See Also
    --------
    delay_scan : Continuous delay scanning
    PseudoPositioner : Base class for pseudo/real conversion
    """

    # Pseudo axis (what user sees)
    delay = Cpt(PseudoSingle, kind='hinted', egu='s')

    # Real axis (physical motor)
    # Defined in subclass with actual motor type

    # Speed of light in mm/s
    c = speed_of_light * 1000  # m/s to mm/s

    @pseudo_position_argument
    def forward(self, pseudo_pos):
        """
        Convert time delay to motor position.

        Parameters
        ----------
        pseudo_pos : namedtuple
            Pseudo position with delay attribute in seconds

        Returns
        -------
        namedtuple
            Real position with motor attribute in mm

        Notes
        -----
        Calculation:
        - path_change = delay * speed_of_light
        - motor_position = path_change / 2
        - Division by 2 accounts for double-pass

        Examples
        --------
        5 ps delay:
        >>> pos = delay.forward(PseudoPosition(delay=5e-12))
        >>> print(f"Motor position: {pos.motor} mm")
        """
        delay_s = pseudo_pos.delay
        # delay = 2 * distance / c
        # distance = delay * c / 2
        motor_mm = (delay_s * self.c) / 2.0
        return self.RealPosition(motor=motor_mm)

    @real_position_argument
    def inverse(self, real_pos):
        """
        Convert motor position to time delay.

        Parameters
        ----------
        real_pos : namedtuple
            Real position with motor attribute in mm

        Returns
        -------
        namedtuple
            Pseudo position with delay attribute in seconds

        Notes
        -----
        Calculation:
        - path_change = 2 * motor_position
        - delay = path_change / speed_of_light

        Examples
        --------
        Motor at 0.75 mm:
        >>> pos = delay.inverse(RealPosition(motor=0.75))
        >>> print(f"Time delay: {pos.delay*1e12:.2f} ps")
        """
        motor_mm = real_pos.motor
        # path_change = 2 * distance
        # delay = path_change / c
        delay_s = (2.0 * motor_mm) / self.c
        return self .PseudoPosition(delay=delay_s)


def quick_delay_scan(start_ps, end_ps, sweep_time=2.0,
                      duration=60, record=True):
    """
    Quick delay scan with simplified parameters.

    Convenience function for common delay scan use case with
    time specified in picoseconds.

    Parameters
    ----------
    start_ps : float
        Starting delay in picoseconds
    end_ps : float
        Ending delay in picoseconds
    sweep_time : float, optional
        Sweep duration in seconds. Default is 2.0.
    duration : float, optional
        Total scan duration in seconds. Default is 60.
    record : bool, optional
        Enable recording. Default is True.

    Returns
    -------
    None

    Notes
    -----
    Uses default MFX delay motor (lxt_fast) and DAQ.
    Automatically converts ps to seconds for delay_scan.

    Examples
    --------
    Scan -10 to +50 ps for 2 minutes:
    >>> quick_delay_scan(-10, 50, duration=120)

    Fast sweep for 30 seconds:
    >>> quick_delay_scan(0, 10, sweep_time=1.0, duration=30)

    Test without recording:
    >>> quick_delay_scan(0, 5, duration=10, record=False)

    See Also
    --------
    delay_scan : Full parameter control
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


def calculate_sweep_velocity(start_mm, end_mm, sweep_time):
    """
    Calculate required motor velocity for delay scan.

    Helper function to determine motor velocity needed to sweep
    between two positions in specified time.

    Parameters
    ----------
    start_mm : float
        Starting position in mm
    end_mm : float
        Ending position in mm
    sweep_time : float
        Desired sweep time in seconds

    Returns
    -------
    float
        Required velocity in mm/s

    Notes
    -----
    Simple calculation: velocity = distance / time

    Use to verify motor can achieve required velocity
    before starting scan.

    Examples
    --------
    Calculate velocity for 100 mm in 2 seconds:
    >>> vel = calculate_sweep_velocity(0, 100, 2.0)
    >>> print(f"Velocity: {vel} mm/s")
    50.0 mm/s

    Check if velocity is achievable:
    >>> required_vel = calculate_sweep_velocity(0, 50, 0.5)
    >>> if required_vel > motor.velocity.limits[1]:
    ...     print("Velocity too high!")

    See Also
    --------
    delay_scan : Uses this calculation internally
    """
    distance = abs(end_mm - start_mm)
    velocity = distance / sweep_time
    return velocity


def time_to_position(delay_s):
    """
    Convert time delay to motor position.

    Utility function for quick time-to-position conversion.

    Parameters
    ----------
    delay_s : float
        Time delay in seconds

    Returns
    -------
    float
        Motor position in mm

    Notes
    -----
    Uses standard double-pass geometry:
    position = (delay * c) / 2

    Examples
    --------
    Convert 5 ps to position:
    >>> pos = time_to_position(5e-12)
    >>> print(f"Position: {pos:.6f} mm")

    Convert array of delays:
    >>> import numpy as np
    >>> delays = np.array([0, 1e-12, 5e-12, 10e-12])
    >>> positions = [time_to_position(d) for d in delays]

    See Also
    --------
    position_to_time : Inverse conversion
    DelayNewport.forward : PseudoPositioner implementation
    """
    c_mm_per_s = speed_of_light * 1000
    position_mm = (delay_s * c_mm_per_s) / 2.0
    return position_mm


def position_to_time(position_mm):
    """
    Convert motor position to time delay.

    Utility function for quick position-to-time conversion.

    Parameters
    ----------
    position_mm : float
        Motor position in mm

    Returns
    -------
    float
        Time delay in seconds

    Notes
    -----
    Uses standard double-pass geometry:
    delay = (2 * position) / c

    Examples
    --------
    Convert 0.75 mm to time:
    >>> delay = position_to_time(0.75)
    >>> print(f"Delay: {delay*1e12:.2f} ps")

    Convert array of positions:
    >>> import numpy as np
    >>> positions = np.array([0, 0.5, 1.0, 1.5])
    >>> delays = [position_to_time(p) for p in positions]

    See Also
    --------
    time_to_position : Inverse conversion
    DelayNewport.inverse : PseudoPositioner implementation
    """
    c_mm_per_s = speed_of_light * 1000
    delay_s = (2.0 * position_mm) / c_mm_per_s
    return delay_s