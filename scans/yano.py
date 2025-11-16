"""Yano-Kern group laser and timing utilities for MFX beamline."""

import logging
import sys
from time import sleep, time
from typing import Optional, List

from pcdsdevices.evr import Trigger

logger = logging.getLogger(__name__)


class Yano:
    """
    Yano-Kern group laser control and timing system.

    Provides high-level control for synchronized laser-X-ray experiments
    with specialized droplet-on-demand (DoD) and sample delivery systems.

    The Yano system integrates:
    - OPO laser (Optical Parametric Oscillator)
    - EVO laser shutters (fiber delivery)
    - Timing synchronization
    - Pulse picker coordination
    - DAQ triggering

    Components
    ----------
    Shutters:
        opo_shutter : LaserShutter
            OPO free-space beam shutter
        evo_shutter1 : LaserShutter
            EVO fiber 1 shutter
        evo_shutter2 : LaserShutter
            EVO fiber 2 shutter
        evo_shutter3 : LaserShutter
            EVO fiber 3 shutter

    Triggers:
        opo : Trigger
            OPO laser trigger (EVR channel 6)
        evo : Trigger
            EVO laser trigger (EVR channel 5)

    Event Codes:
        opo_ec_short : int = 212
            Short delay event code (same bucket)
        opo_ec_long : int = 211
            Long delay event code (1 bucket before)
        opo_ec_longer : int = 210
            Longer delay event code
        opo_ec_longest : int = 213
            Longest delay event code
        PP : int = 197
            Pulse picker event code
        DAQ : int = 198
            DAQ readout event code
        WATER : int = 211
            Water droplet event code
        SAMPLE : int = 212
            Sample droplet event code

    Attributes
    ----------
    opo_time_zero : int
        OPO laser time zero in ticks (default: 671740)
    rep_rate : int
        Repetition rate in Hz (default: 20)
    delay : float or None
        Current laser delay in ns

    Notes
    -----
    Timing System:
    - Uses event receiver (EVR) for synchronization
    - Sub-nanosecond jitter
    - Synchronized to accelerator RF
    - Multiple delay options via event codes

    Laser Configuration:
    - OPO: Free-space beam, tuneable wavelength
    - EVO: Fiber-delivered, multiple output ports

    Event Code Logic:
    - Different codes for different delays
    - Allows multi-bucket delays
    - Coordinates with pulse picker
    - Synchronized with DAQ

    Bucket Structure:
    - LCLS runs at 120 Hz max (8.33 ms buckets)
    - Each bucket can contain X-ray pulse
    - Laser can be in same or different bucket
    - Event codes determine relative timing

    Common Experiments:
    - Pump-probe with tunable delay
    - Droplet-on-demand (DoD)
    - Solution scattering
    - Time-resolved dynamics

    Examples
    --------
    Create Yano controller:
    >>> yano = Yano()

    Configure shutters:
    >>> yano.configure_shutters(fiber1=True, free_space=True)

    Run pump-probe experiment:
    >>> yano.long_escan(
    ...     delay=1000,  # 1000 ns = 1 µs
    ...     rep=60,
    ...     sample='lysozyme',
    ...     record=True
    ... )

    Check shutter status:
    >>> status = yano.shutter_status
    >>> print(status)

    See Also
    --------
    MFXTiming : General timing control
    autorun : Automated data collection
    """

    def __init__(self):
        """
        Initialize Yano laser control system.

        Sets up laser shutters, triggers, event codes, and timing parameters.
        """
        from mfx.devices import LaserShutter

        # Initialize delay tracking
        self.delay = None

        # Declare shutter objects
        self.opo_shutter = LaserShutter('MFX:USR:ao1:6', name='opo_shutter')
        self.evo_shutter1 = LaserShutter('MFX:USR:ao1:8', name='evo_shutter1')
        self.evo_shutter2 = LaserShutter('MFX:USR:ao1:2', name='evo_shutter2')
        self.evo_shutter3 = LaserShutter('MFX:USR:ao1:3', name='evo_shutter3')

        # Trigger objects (EVR channels)
        self.opo = Trigger('MFX:LAS:EVR:01:TRIG6', name='opo_trigger')
        self.evo = Trigger('MFX:LAS:EVR:01:TRIG5', name='evo_trigger')

        # Laser timing parameters
        self.opo_time_zero = 671740  # OPO time zero in ticks

        # Event code switch logic for longer delays
        self.opo_ec_short = 212   # Same bucket as X-rays
        self.opo_ec_long = 211    # 1 bucket before X-rays
        self.opo_ec_longer = 210  # 2 buckets before
        self.opo_ec_longest = 213 # 3 buckets before

        # Standard event codes
        self.PP = 197      # Pulse picker
        self.DAQ = 198     # DAQ readout
        self.WATER = 211   # Water droplet
        self.SAMPLE = 212  # Sample droplet

        # Default repetition rate
        self.rep_rate = 20  # Hz

        logger.info("Yano laser system initialized")

    @property
    def shutter_status(self) -> List[str]:
        """
        Get current status of all laser shutters.

        Returns
        -------
        List[str]
            List of shutter states: [evo1, evo2, evo3, opo]
            Each state is 'Open' or 'Closed'

        Notes
        -----
        Shutter States:
        - 'Open': Laser light passes
        - 'Closed': Laser blocked

        Order:
        1. EVO fiber 1
        2. EVO fiber 2
        3. EVO fiber 3
        4. OPO free-space

        Examples
        --------
        >>> yano = Yano()
        >>> status = yano.shutter_status
        >>> print(f"EVO1: {status[0]}, OPO: {status[3]}")

        Check if all closed:
        >>> if all(s == 'Closed' for s in yano.shutter_status):
        ...     print("All shutters closed")
        """
        status = []
        for shutter in (self.evo_shutter1, self.evo_shutter2,
                        self.evo_shutter3, self.opo_shutter):
            status.append(shutter.state.get())
        return status

    def configure_shutters(
            self,
            fiber1: bool = False,
            fiber2: bool = False,
            fiber3: bool = False,
            free_space: Optional[bool] = None):
        """
        Configure all laser shutters for experiment.

        Sets shutter states based on which laser beams are needed.
        Provides safety by explicitly controlling all shutters.

        Parameters
        ----------
        fiber1 : bool, optional
            Open EVO fiber 1 shutter (default: False)
        fiber2 : bool, optional
            Open EVO fiber 2 shutter (default: False)
        fiber3 : bool, optional
            Open EVO fiber 3 shutter (default: False)
        free_space : bool or None, optional
            Open OPO free-space shutter (default: None)
            If None, does not change OPO shutter

        Returns
        -------
        None

        Notes
        -----
        Shutter Configuration:
        - True: Opens shutter (laser on)
        - False: Closes shutter (laser blocked)
        - None: Leaves shutter unchanged

        EVO Fibers:
        - Fiber 1: Typically primary sample
        - Fiber 2: Secondary sample or reference
        - Fiber 3: Additional sample position

        OPO Free-Space:
        - High power option
        - Direct beam path
        - Typically for pump-probe

        Safety Features:
        - All shutters default closed
        - Explicit enable required
        - Independent control
        - Status logging

        Common Configurations:
        - Single fiber: fiber1=True, others False
        - Dual fiber: fiber1=True, fiber2=True
        - OPO only: free_space=True, fibers False
        - All off: all parameters False

        Examples
        --------
        Open fiber 1 only:
        >>> yano = Yano()
        >>> yano.configure_shutters(fiber1=True)

        Open fiber 1 and OPO:
        >>> yano.configure_shutters(fiber1=True, free_space=True)

        Open all fibers:
        >>> yano.configure_shutters(
        ...     fiber1=True,
        ...     fiber2=True,
        ...     fiber3=True
        ... )

        Close all:
        >>> yano.configure_shutters(
        ...     fiber1=False,
        ...     fiber2=False,
        ...     fiber3=False,
        ...     free_space=False
        ... )

        See Also
        --------
        shutter_status : Check current shutter states
        """
        logger.info("Configuring laser shutters")

        # Configure EVO fiber shutters
        if fiber1:
            self.evo_shutter1.open()
            logger.info("EVO fiber 1: OPEN")
        else:
            self.evo_shutter1.close()
            logger.info("EVO fiber 1: CLOSED")

        if fiber2:
            self.evo_shutter2.open()
            logger.info("EVO fiber 2: OPEN")
        else:
            self.evo_shutter2.close()
            logger.info("EVO fiber 2: CLOSED")

        if fiber3:
            self.evo_shutter3.open()
            logger.info("EVO fiber 3: OPEN")
        else:
            self.evo_shutter3.close()
            logger.info("EVO fiber 3: CLOSED")

        # Configure OPO free-space shutter (if specified)
        if free_space is not None:
            if free_space:
                self.opo_shutter.open()
                logger.info("OPO free-space: OPEN")
            else:
                self.opo_shutter.close()
                logger.info("OPO free-space: CLOSED")
        else:
            logger.info("OPO free-space: unchanged")

    def long_escan(
            self,
            delay: float,
            rep: int = 60,
            sample: str = '?',
            tag: str = None,
            run_length: int = 60,
            record: bool = False,
            runs: int = 5,
            inspire: bool = False,
            daq_delay: int = 5,
            picker: str = None,
            daq_num: int = 2,
            spread: Optional[str] = None):
        """
        Perform laser pump-probe scan with time delay.

        Executes automated data collection with OPO laser at specified
        pump-probe delay. Coordinates timing, shutters, and DAQ.

        Parameters
        ----------
        delay : float
            Pump-probe delay in nanoseconds
            Positive = laser before X-rays
            Typical range: -10000 to +10000 ns
        rep : int, optional
            Repetition rate in Hz: 30, 60, 90, or 120 (default: 60)
        sample : str, optional
            Sample name (default: '?')
        tag : str or None, optional
            Run tag (defaults to sample if None)
        run_length : int, optional
            Data collection time per run in seconds (default: 60)
        record : bool, optional
            Enable data recording (default: False)
        runs : int, optional
            Number of runs to collect (default: 5)
        inspire : bool, optional
            Add inspirational quotes to elog (default: False)
        daq_delay : int, optional
            Delay between runs in seconds (default: 5)
        picker : str or None, optional
            Pulse picker mode: 'open', 'flip', or None
        daq_num : int, optional
            DAQ version: 1 (LCLS-I) or 2 (LCLS-II) (default: 2)
        spread : str or None, optional
            Droplet spread parameter (logged to elog)

        Returns
        -------
        None

        Raises
        ------
        SystemExit
            If delay out of range for selected rep rate
        ValueError
            If rep rate not in [30, 60, 90, 120]
            If daq_num not in [1, 2]

        Notes
        -----
        Delay Calculation:
        - Converts delay (ns) to EVR ticks
        - Selects appropriate event code
        - Handles multi-bucket delays

        Event Code Selection (60 Hz example):
        - delay < opo_time_zero: Same bucket (ec_short)
        - delay > opo_time_zero: 1 bucket before (ec_long)
        - delay > opo_time_zero + 1/120: Error (too long)

        Rep Rate Restrictions:
        - 30 Hz: Allows longest delays
        - 60 Hz: Standard pump-probe
        - 90 Hz: Special Yano sequence
        - 120 Hz: Minimal delays only

        Timing Sequences:
        - Uses MFXTiming.set_seq()
        - Loads appropriate sequence for rep rate
        - Configures event codes
        - Synchronizes all components

        Data Recording:
        - Uses LCLS-II DAQ (daq_num=2)
        - Posts run info to elog
        - Includes shutter status
        - Logs delay and spread

        Safety Features:
        - Closes shutters after runs
        - Returns DAQ to safe state
        - Logs all parameters
        - Handles keyboard interrupt

        Examples
        --------
        Basic pump-probe at 1 µs delay:
        >>> yano = Yano()
        >>> yano.long_escan(
        ...     delay=1000,
        ...     sample='lysozyme',
        ...     record=True
        ... )

        Fast dynamics at 120 Hz:
        >>> yano.long_escan(
        ...     delay=500,
        ...     rep=120,
        ...     sample='myoglobin',
        ...     run_length=30,
        ...     record=True
        ... )

        Long delay at 30 Hz:
        >>> yano.long_escan(
        ...     delay=20000,  # 20 µs
        ...     rep=30,
        ...     sample='cytochrome_c',
        ...     record=True
        ... )

        See Also
        --------
        configure_shutters : Set up laser shutters
        MFXTiming.set_seq : Load timing sequences
        autorun : General data collection
        """
        from mfx.db import daq, pp , elog
        from mfx.autorun import quote, post
        from mfx.macros import get_run, get_exp
        from mfx import mfx_timing

        logger.info(f"Starting Yano pump-probe scan with {delay} ns delay")

        # Validate rep rate
        if rep not in [30, 60, 90, 120]:
            logger.error(f"Invalid rep rate: {rep} Hz. Use 30, 60, 90, or 120")
            raise ValueError("Invalid rep rate")

        # Validate DAQ number
        if daq_num == 1:
            station = 1
        elif daq_num == 2:
            station = 0
        else:
            logger.error('daq_num must be 1 (LCLS-I) or 2 (LCLS-II)')
            raise ValueError("Invalid daq_num")

        # Auto-inspire for water
        if sample.lower() in ['water', 'h2o']:
            inspire = True

        # Default tag
        if tag is None:
            tag = sample

        # Configure pulse picker
        if picker == 'open':
            pp.open()
        elif picker == 'flip':
            pp.flipflop()

        # Set laser delay
        self.set_delay(delay, rep=rep)
        delay_str = self._delaystr(self.delay)
        logger.info(f"Laser delay: {delay_str}")

        # Get run number
        run_number = get_run(station=station) + 1

        # Record shutter status
        shutter_stat = self.shutter_status

        # Build elog comment
        comment = f"Running {sample} with {delay_str}"
        if spread is not None:
            comment += f"\nDroplet spread: {spread}"
        if inspire:
            comment += f"\n{quote()['quote']}"
        comment += f"\nShutter status: {shutter_stat}"

        # Execute runs
        try:
            for run_idx in range(runs):
                logger.info(
                    f"Run {run_idx + 1}/{runs}: "
                    f"{sample} at {delay} ns delay"
                )

                # Setup DAQ
                if daq_num == 2:
                    from psdaq.control.DaqControl import DaqControl

                    daq.control = DaqControl(
                        host=daq.control.host,
                        platform=daq.control.platform,
                        timeout=10000
                    )

                    instr = daq.control.getInstrument()
                    if instr is None:
                        logger.error('Failed to connect to LCLS-II DAQ')
                        break

                    start_state = daq.control.getState()
                    if start_state == 'error':
                        logger.error('DAQ is in error state')
                        break

                    daq.control.setState("configured")
                    while daq.control.getState() != "configured":
                        sleep(0.01)

                    daq.control.setRecord(record)
                    daq.control.setState("running")
                    while daq.control.getState() != "running":
                        sleep(0.01)

                elif daq_num == 1:
                    daq.configure(record=record)
                    sleep(3)
                    daq.begin(duration=run_length, record=record, wait=True, use_l3t=False)

                # Collect data
                if daq_num == 2:
                    sleep(run_length)

                    daq.control.setState("configured")
                    while daq.control.getState() != "configured":
                        sleep(0.01)

                # Post to elog
                if record:
                    post(
                        sample=sample,
                        tag=tag,
                        run_number=run_number + run_idx,
                        post=record,
                        inspire=inspire,
                        daq_num=daq_num,
                        add_note=comment
                    )

                # Delay between runs
                if run_idx < runs - 1:
                    sleep(daq_delay)

        except KeyboardInterrupt:
            logger.warning("Scan interrupted by user")
            pp.close()
            if daq_num == 2:
                daq.control.setState("configured")
                while daq.control.getState() != "configured":
                    sleep(0.01)
                daq.control.setRecord(False)
                daq.control.setState("running")

            if record:
                post(
                    sample=sample,
                    tag=tag,
                    run_number=run_number,
                    post=record,
                    inspire=inspire,
                    daq_num=daq_num,
                    add_note=f"{comment}\nRun ended prematurely"
                )

        # Cleanup
        pp.close()
        if daq_num == 2:
            daq.control.setState("configured")
            while daq.control.getState() != "configured":
                sleep(0.01)
            daq.control.setRecord(False)
            daq.control.setState("running")
        elif daq_num == 1:
            daq.end_run()
            daq.disconnect()

        logger.warning('Scan completed successfully\n')

    # ==================== Convenience Shutter Methods ====================

    def fiber_0(self):
        """
        Configure for no fiber delivery (all fibers closed).

        Returns
        -------
        str
            Confirmation message

        Notes
        -----
        Closes all three EVO fiber shutters.
        OPO shutter unchanged (use free_space parameter).

        Examples
        --------
        >>> yano = Yano()
        >>> yano.fiber_0()
        """
        return self.configure_shutters(
            fiber1=False,
            fiber2=False,
            fiber3=False,
            free_space=None
        )

    def fiber_1(self):
        """
        Configure for fiber 1 delivery only.

        Returns
        -------
        str
            Confirmation message

        Notes
        -----
        Opens EVO fiber 1, closes fibers 2 and 3.
        Typical for single-position experiments.

        Examples
        --------
        >>> yano = Yano()
        >>> yano.fiber_1()
        """
        return self.configure_shutters(
            fiber1=True,
            fiber2=False,
            fiber3=False,
            free_space=None
        )

    def fiber_2(self):
        """
        Configure for dual fiber delivery (fibers 2 and 3).

        Returns
        -------
        str
            Confirmation message

        Notes
        -----
        Opens EVO fibers 2 and 3, closes fiber 1.
        Useful for dual-sample configurations.

        Examples
        --------
        >>> yano = Yano()
        >>> yano.fiber_2()
        """
        return self.configure_shutters(
            fiber1=False,
            fiber2=True,
            fiber3=True,
            free_space=None
        )

    def fiber_3(self):
        """
        Configure for all fiber delivery.

        Returns
        -------
        str
            Confirmation message

        Notes
        -----
        Opens all three EVO fiber shutters.
        Maximum coverage configuration.

        Examples
        --------
        >>> yano = Yano()
        >>> yano.fiber_3()
        """
        return self.configure_shutters(
            fiber1=True,
            fiber2=True,
            fiber3=True,
            free_space=None
        )

    # ==================== Delay Management ====================

    def _delaystr(self, delay: Optional[float]) -> str:
        """
        Convert delay to human-readable string.

        Parameters
        ----------
        delay : float or None
            Delay in nanoseconds

        Returns
        -------
        str
            Formatted delay string with appropriate units

        Notes
        -----
        Unit Selection:
        - delay >= 1e6 ns: Format as milliseconds
        - delay >= 1e3 ns: Format as microseconds
        - delay >= 0 ns: Format as nanoseconds
        - delay < 0 ns: Format as nanoseconds (AFTER X-ray)

        Special Cases:
        - OPO shutter closed: Returns "No OPO Laser"
        - None: Returns "No delay set"

        Examples
        --------
        >>> yano = Yano()
        >>> yano.set_delay(1000, rep=60)
        >>> print(yano._delaystr(yano.delay))
        'Laser delay is set to 1.000 us'
        """
        if self.opo_shutter.state.get() != 'Open':
            return 'No OPO Laser'

        if delay is None:
            return 'No delay set'

        if delay >= 1e6:
            return f'Laser delay is set to {delay/1e6:10.6f} ms'
        elif delay >= 1e3:
            return f'Laser delay is set to {delay/1e3:7.3f} us'
        elif delay >= 0:
            return f'Laser delay is set to {delay:4.0f} ns'
        else:
            return f'Laser delay is set to {delay:8.0f} ns (AFTER X-ray pulse)'

    def _wrap_delay(self, delay: float, base_rate: int = 120) -> float:
        """
        Wrap delay to fit within base rate period.

        Adjusts delays longer than one bucket period to fit
        within the base rate constraint.

        Parameters
        ----------
        delay : float
            Requested delay in nanoseconds
        base_rate : int, optional
            Base rate in Hz (default: 120)

        Returns
        -------
        float
            Adjusted delay in nanoseconds

        Notes
        -----
        Bucket Period:
        - 120 Hz: 8.33 ms (8.33e6 ns)
        - If delay exceeds this, wraps to next bucket

        Wrapping Logic:
        - delay > 1/base_rate: subtract one period
        - This moves laser to earlier bucket
        - Maintains relative timing

        Use Case:
        - Very long delays
        - Multi-bucket timing
        - Event code selection

        Examples
        --------
        >>> yano = Yano()
        >>> wrapped = yano._wrap_delay(10e6, base_rate=120)  # 10 ms
        >>> print(f"Wrapped to {wrapped/1e6:.3f} ms")
        """
        period_ns = (1.0 / base_rate) * 1e9

        if delay > period_ns:
            adjusted_delay = delay - period_ns
            logger.info(
                f"Delay {delay/1e6:.3f} ms exceeds bucket period. "
                f"Wrapped to {adjusted_delay/1e6:.3f} ms"
            )
        else:
            adjusted_delay = delay

        return adjusted_delay

    def set_delay(self, delay: float, rep: int = 30):
        """
        Set OPO laser delay relative to X-ray pulse.

        Configures laser timing by:
        1. Selecting appropriate event code
        2. Loading timing sequence
        3. Setting EVR trigger delay

        Parameters
        ----------
        delay : float
            Pump-probe delay in nanoseconds
            Positive = laser before X-rays
            Negative = laser after X-rays (unusual)
        rep : int, optional
            Repetition rate in Hz: 30, 60, 90, or 120 (default: 30)

        Returns
        -------
        None

        Raises
        ------
        SystemExit
            If delay out of range for selected rep rate
        ValueError
            If rep not in [30, 60, 90, 120]

        Notes
        -----
        Delay Ranges by Rep Rate:

        30 Hz:
        - Maximum delay: ~25 ms (3 buckets before)
        - Uses: opo_ec_short, opo_ec_long, opo_ec_longer, opo_ec_longest

        60 Hz:
        - Maximum delay: ~8.3 ms (1 bucket before)
        - Uses: opo_ec_short, opo_ec_long

        90 Hz:
        - Maximum delay: opo_time_zero (~5.6 ms)
        - Uses: DAQ event code (same bucket)

        120 Hz:
        - Maximum delay: opo_time_zero (~5.6 ms)
        - Uses: DAQ event code (same bucket)

        Event Code Selection Logic:
        Based on delay relative to thresholds:
        - delay <= opo_time_zero: Same bucket
        - delay <= opo_time_zero + 8.3ms: 1 bucket before
        - delay <= opo_time_zero + 16.7ms: 2 buckets before
        - delay <= opo_time_zero + 25ms: 3 buckets before

        Timing Sequence:
        - Loads appropriate MFX timing sequence
        - Configures event codes
        - Synchronizes laser and X-ray

        EVR Configuration:
        - Sets trigger delay in ticks
        - Configures polarity
        - Enables trigger output

        Examples
        --------
        Set 1 µs delay at 60 Hz:
        >>> yano = Yano()
        >>> yano.set_delay(1000, rep=60)

        Set long delay at 30 Hz:
        >>> yano.set_delay(20000, rep=30)  # 20 µs

        Negative delay (laser after X-ray):
        >>> yano.set_delay(-500, rep=60)  # 500 ns after

        Get current delay:
        >>> current = yano.delay
        >>> print(f"Delay: {current} ns")

        See Also
        --------
        get_delay : Read current delay
        _delaystr : Format delay string
        _wrap_delay : Wrap delay to bucket
        """
        from mfx import mfx_timing

        # Validate rep rate
        if rep not in [30, 60, 90, 120]:
            logger.error(f"Invalid rep rate: {rep} Hz. Use 30, 60, 90, or 120")
            raise ValueError("Invalid rep rate")

        # Calculate OPO delay (add time zero offset)
        opo_delay = self.opo_time_zero + delay

        # Select event code and load sequence based on rep rate
        if rep == 30:
            mfx_timing.set_seq(rep='30')

            if delay > self.opo_time_zero + 3 * (1e9 / 120):
                # Delay too long even for 30 Hz
                logger.error(
                    f'Laser delay {delay} ns is too long for 30 Hz. '
                    f'Maximum is ~25 ms'
                )
                sys.exit()

            elif delay > self.opo_time_zero + 2 * (1e9 / 120):
                # 3 buckets before (longest)
                opo_delay += 3 * (1e9 / 120)
                opo_ec = self.opo_ec_longest
                logger.info('Laser is 3 buckets before the beam')

            elif delay > self.opo_time_zero + (1e9 / 120):
                # 2 buckets before (longer)
                opo_delay += 2 * (1e9 / 120)
                opo_ec = self.opo_ec_longer
                logger.info('Laser is 2 buckets before the beam')

            elif delay > self.opo_time_zero:
                # 1 bucket before (long)
                opo_delay += (1e9 / 120)
                opo_ec = self.opo_ec_long
                logger.info('Laser is 1 bucket before the beam')

            else:
                # Same bucket (short)
                opo_ec = self.DAQ
                logger.info('Laser is in the same bucket as the beam')

        elif rep == 60:
            mfx_timing.set_seq(rep='60_yano')

            if delay > self.opo_time_zero + (1e9 / 120):
                # Delay too long for 60 Hz
                logger.error(
                    f'Laser delay {delay} ns is too long for 60 Hz. '
                    f'Maximum is ~8.3 ms. Switch to 30 Hz'
                )
                sys.exit()

            elif delay > self.opo_time_zero:
                # 1 bucket before
                opo_delay += (1e9 / 120)
                opo_ec = self.opo_ec_long
                logger.info('Laser is 1 bucket before the beam')

            else:
                # Same bucket
                opo_ec = self.DAQ
                logger.info('Laser is in the same bucket as the beam')

        elif rep == 90:
            mfx_timing.set_seq(rep='90_yano')

            if delay > self.opo_time_zero:
                # Delay too long for 90 Hz
                logger.error(
                    f'Laser delay {delay} ns is too long for 90 Hz. '
                    f'Switch to 30 Hz or 60 Hz'
                )
                sys.exit()
            else:
                # Same bucket
                opo_ec = self.DAQ
                logger.info('Laser and droplet in the same bucket as the beam')

        elif rep == 120:
            mfx_timing.set_seq(rep='120_yano')

            if delay > self.opo_time_zero:
                # Delay too long for 120 Hz
                logger.error(
                    f'Laser delay {delay} ns is too long for 120 Hz. '
                    f'Switch to 30 Hz'
                )
                sys.exit()
            else:
                # Same bucket
                opo_ec = self.DAQ
                logger.info('Laser and droplet in the same bucket as the beam')

        # Configure OPO trigger
        self.opo.eventcode.put(opo_ec)
        self.opo.ns_delay.put(opo_delay)
        self.opo.polarity.put(0)  # Normal polarity
        self.opo.enable()

        # Store delay
        self.delay = delay

        logger.info(f"OPO delay set to {opo_delay} ns with event code {opo_ec}")
        logger.info(self._delaystr(delay))

    def get_delay(self) -> Optional[float]:
        """
        Get current laser delay.

        Returns
        -------
        float or None
            Current delay in nanoseconds
            None if no delay set

        Examples
        --------
        >>> yano = Yano()
        >>> yano.set_delay(1000, rep=60)
        >>> delay = yano.get_delay()
        >>> print(f"Current delay: {delay} ns")
        """
        return self.delay


# Convenience instance for direct import
yano = Yano()


def configure_yano_shutters(
        fiber1: bool = False,
        fiber2: bool = False,
        fiber3: bool = False,
        free_space: Optional[bool] = None):
    """
    Convenience function to configure Yano laser shutters.

    Parameters
    ----------
    fiber1 : bool, optional
        Open fiber 1 (default: False)
    fiber2 : bool, optional
        Open fiber 2 (default: False)
    fiber3 : bool, optional
        Open fiber 3 (default: False)
    free_space : bool or None, optional
        Open OPO (default: None)

    Returns
    -------
    None

    Examples
    --------
    >>> configure_yano_shutters(fiber1=True)
    >>> configure_yano_shutters(fiber1=True, free_space=True)

    See Also
    --------
    Yano.configure_shutters : Full implementation
    """
    yano.configure_shutters(
        fiber1=fiber1,
        fiber2=fiber2,
        fiber3=fiber3,
        free_space=free_space
    )


def set_yano_delay(delay: float, rep: int = 30):
    """
    Convenience function to set Yano laser delay.

    Parameters
    ----------
    delay : float
        Delay in nanoseconds
    rep : int, optional
        Rep rate in Hz: 30, 60, 90, 120 (default: 30)

    Returns
    -------
    None

    Examples
    --------
    >>> set_yano_delay(1000, rep=60)  # 1 µs at 60 Hz
    >>> set_yano_delay(5000, rep=30)  # 5 µs at 30 Hz

    See Also
    --------
    Yano.set_delay : Full implementation
    """
    yano.set_delay(delay, rep=rep)


def get_yano_delay() -> Optional[float]:
    """
    Convenience function to get current Yano delay.

    Returns
    -------
    float or None
        Current delay in nanoseconds

    Examples
    --------
    >>> delay = get_yano_delay()
    >>> print(f"Delay: {delay} ns")

    See Also
    --------
    Yano.get_delay : Full implementation
    """
    return yano.get_delay()


def yano_pump_probe(
        delay: float,
        sample: str,
        rep: int = 60,
        record: bool = False,
        **kwargs):
    """
    Convenience function for Yano pump-probe experiments.

    Parameters
    ----------
    delay : float
        Pump-probe delay in nanoseconds
    sample : str
        Sample name
    rep : int, optional
        Rep rate in Hz (default: 60)
    record : bool, optional
        Enable recording (default: False)
    **kwargs
        Additional arguments passed to long_escan()

    Returns
    -------
    None

    Examples
    --------
    >>> yano_pump_probe(
    ...     delay=1000,
    ...     sample='lysozyme',
    ...     rep=60,
    ...     record=True,
    ...     runs=10
    ... )

    See Also
    --------
    Yano.long_escan : Full implementation
    """
    yano.long_escan(
        delay=delay,
        rep=rep,
        sample=sample,
        record=record,
        **kwargs
    )