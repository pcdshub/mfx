"""Generic scan utilities for MFX beamline experiments."""

import logging
from time import sleep
from typing import Optional, List, Union

import numpy as np

logger = logging.getLogger(__name__)


class Scan:
    """
    Generic scan controller for arbitrary PV/motor scans.

    Provides flexible scanning capabilities for any EPICS PV or motor
    while collecting synchronized data with the DAQ. Useful for:
    - Delay scans (laser timing)
    - Motor alignment scans
    - Voltage/current scans
    - Temperature scans
    - Any parameter vs. detector response

    The scan controller integrates with both LCLS-I and LCLS-II DAQ
    systems and supports single scans or series of scans.

    Methods
    -------
    scan(scan_start, scan_end, scan_steps, pv, ...) : None
        Perform single scan
    series(pv_values, scan_start, scan_end, scan_steps, pv, ...) : None
        Perform series of scans at different PV values

    Attributes
    ----------
    None

    Notes
    -----
    Scan Types:

    Single Scan:
    - Sweeps one parameter across range
    - Records data at each point
    - Typical for alignment, optimization

    Series Scan:
    - Multiple scans at different settings
    - Each scan uses same range
    - Useful for parameter studies

    PV Selection:
    The 'pv' parameter can be:
    - Pre-defined string ('lxt_fast', 'lxt', etc.)
    - Custom EPICS PV name
    - Motor object name

    Pre-defined PVs:
    - 'lxt_fast': Fast laser timing stage
    - 'lxt': Laser timing compensation
    - Custom: Specify full EPICS PV

    DAQ Integration:
    - Motors registered with DAQ
    - Positions stored in metadata
    - Event-synchronized data
    - Supports step scanning

    Bluesky Plans:
    - Uses Bluesky scanning framework
    - RunEngine (RE) executes scans
    - Motors are hinted for plotting
    - DAQ treated as detector

    Common Applications:
    - Laser delay scans
    - Motor alignment (X, Y, Z)
    - Focus optimization
    - Attenuation studies
    - Temperature sweeps

    Examples
    --------
    Create scan controller:
    >>> scan = Scan()

    Simple delay scan:
    >>> scan.scan(
    ...     scan_start=0.0,
    ...     scan_end=100.0,
    ...     scan_steps=11,
    ...     pv='lxt_fast',
    ...     sample='lysozyme',
    ...     record=True
    ... )

    Series of scans:
    >>> scan.series(
    ...     pv_values=[1000, 2000, 3000],
    ...     scan_start=0.0,
    ...     scan_end=50.0,
    ...     scan_steps=6,
    ...     pv='lxt_fast',
    ...     record=True
    ... )

    See Also
    --------
    Wire : Specialized wire scanner
    Vernier : Energy vernier scans
    """

    def __init__(self):
        """Initialize Scan controller."""
        logger.info("Scan controller initialized")

    def scan(
            self,
            scan_start: float,
            scan_end: float,
            scan_steps: int,
            events_per_step: int = 120,
            sample: str = '?',
            tag: str = None,
            picker: str = None,
            runs: int = 1,
            inspire: bool = False,
            record: bool = False,
            pv: str = 'lxt_fast',
            close: bool = True,
            daq_num: int = 2,
            exp: str = None):
        """
        Perform single parameter scan.

        Sweeps specified PV/motor across range while collecting
        data with DAQ at each step.

        Parameters
        ----------
        scan_start : float
            Starting value for scan parameter
        scan_end : float
            Ending value for scan parameter
        scan_steps : int
            Number of scan steps
            Step size = (scan_end - scan_start) / (scan_steps - 1)
        events_per_step : int, optional
            Number of events to collect per step (default: 120)
            At 120 Hz, 120 events = 1 second
        sample : str, optional
            Sample name (default: '?')
        tag : str or None, optional
            Run tag for organization (defaults to sample if None)
        picker : str or None, optional
            Pulse picker mode: 'open', 'flip', or None
            - 'open': All pulses pass
            - 'flip': Alternating pulses for background
            - None: Current state unchanged
        runs : int, optional
            Number of times to repeat scan (default: 1)
        inspire : bool, optional
            Add inspirational quotes to elog (default: False)
        record : bool, optional
            Enable data recording (default: False)
        pv : str, optional
            PV/motor to scan (default: 'lxt_fast')
            Pre-defined: 'lxt_fast', 'lxt'
            Custom: Full EPICS PV name
        close : bool, optional
            Close pulse picker after scan (default: True)
        daq_num : int, optional
            DAQ version: 1 (LCLS-I) or 2 (LCLS-II) (default: 2)
        exp : str or None, optional
            Experiment name (auto-detected if None)

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If daq_num not in [1, 2]
        KeyboardInterrupt
            User can abort scan, will cleanup safely

        Notes
        -----
        Scan Sequence:
        1. Configure pulse picker
        2. Get run number
        3. Create motor/PV object
        4. Configure DAQ with motor
        5. For each run:
           a. Execute Bluesky scan plan
           b. Post results to elog
           c. Wait before next run
        6. Close pulse picker (if requested)
        7. Cleanup DAQ

        PV Types:

        Pre-defined Motors:
        - 'lxt_fast': Fast laser timing stage
          - IMS motor at MFX:LAS:MMN:16
          - Range typically -50 to +150 mm
          - 1 mm ≈ 6.67 ps delay

        Custom PVs:
        - Specify full EPICS PV name
        - Creates OnePVMotor object
        - PV must support put/get

        DAQ Versions:

        DAQ 1 (LCLS-I):
        - Legacy system
        - Uses daq_scan plan
        - Event-based triggering

        DAQ 2 (LCLS-II):
        - Current system
        - Uses Bluesky bp.scan
        - Motor positions in metadata
        - Better metadata handling

        Scan Duration:
        - Single scan: scan_steps × (events_per_step / rep_rate)
        - Example: 11 steps × 120 events @ 120 Hz = 11 seconds
        - Multiple runs: scan_time × runs
        - Plus move overhead (~0.5 s/step)

        Data Organization:
        - Each run gets unique run number
        - Motor positions stored in DAQ
        - Scan parameters in elog
        - Can be analyzed offline

        Pulse Picker Modes:
        - 'open': Maximum flux, no background
        - 'flip': Alternating for laser on/off
        - None: Manual control

        Keyboard Interrupt:
        - Ctrl+C aborts scan safely
        - Closes pulse picker
        - Returns DAQ to safe state
        - Posts abort note to elog

        Examples
        --------
        Basic delay scan:
        >>> scan = Scan()
        >>> scan.scan(
        ...     scan_start=0.0,
        ...     scan_end=100.0,
        ...     scan_steps=21,
        ...     pv='lxt_fast',
        ...     sample='lysozyme',
        ...     record=True
        ... )

        High-resolution scan:
        >>> scan.scan(
        ...     scan_start=10.0,
        ...     scan_end=20.0,
        ...     scan_steps=101,
        ...     events_per_step=240,
        ...     pv='lxt_fast',
        ...     record=True
        ... )

        Multiple runs for statistics:
        >>> scan.scan(
        ...     scan_start=0.0,
        ...     scan_end=50.0,
        ...     scan_steps=11,
        ...     runs=5,
        ...     pv='lxt_fast',
        ...     record=True
        ... )

        Custom PV scan:
        >>> scan.scan(
        ...     scan_start=-5.0,
        ...     scan_end=5.0,
        ...     scan_steps=21,
        ...     pv='MFX:DG1:MMS:01',  # Custom motor
        ...     record=True
        ... )

        See Also
        --------
        series : Multiple scans at different settings
        Wire.scan : Specialized wire scanner
        """
        from mfx.db import RE, daq, pp
        from mfx.devices import Lxt, LxtFast
        from pcdsdevices.pv_positioner import OnePVMotor
        from mfx.autorun import quote, post
        from mfx.macros import get_run, get_exp
        import bluesky.plans as bp

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

        # Get experiment
        if exp is None:
            exp = get_exp()

        # Configure pulse picker
        if picker == 'open':
            pp.open()
            logger.info("Pulse picker: OPEN")
        elif picker == 'flip':
            pp.flipflop()
            logger.info("Pulse picker: FLIPFLOP")

        # Create motor/PV object
        logger.info(f"Setting up scan on PV: {pv}")

        if pv.lower() == 'lxt_fast':
            motor = LxtFast(name='lxt_fast')
            motor_name = 'lxt_fast'
        elif pv.lower() == 'lxt':
            motor = Lxt(name='lxt')
            motor_name = 'lxt'
        else:
            # Custom PV
            motor = OnePVMotor(pv, name='scan_motor')
            motor_name = pv

        # Set motor as hinted for plotting
        motor.setpoint.kind = "hinted"

        logger.info(
            f"Scan configuration: "
            f"{scan_start} to {scan_end} in {scan_steps} steps"
        )

        # Execute scans
        try:
            if daq_num == 2:
                # LCLS-II DAQ
                for run_idx in range(runs):
                    run_number = get_run(station=station) + 1

                    logger.info(
                        f"Run {run_idx + 1}/{runs} "
                        f"(Run Number {run_number}): "
                        f"{sample}... {quote()['quote']}"
                    )

                    # Configure DAQ
                    daq.configure(
                        motors=[motor],
                        group_mask=0x1,
                        events=events_per_step,
                        record=record
                    )

                    # Execute scan
                    RE(bp.scan(
                        [daq],
                        motor,
                        scan_start,
                        scan_end,
                        scan_steps
                    ))

                    # Post to elog
                    if record:
                        scan_note = (
                            f"Scan: {motor_name} from {scan_start} to {scan_end}, "
                            f"{scan_steps} steps @ {events_per_step} events/step"
                        )

                        post(
                            sample=sample,
                            tag=tag,
                            run_number=run_number,
                            post=record,
                            inspire=inspire,
                            daq_num=daq_num,
                            add_note=scan_note
                        )

                    # Wait before next run
                    if run_idx < runs - 1:
                        sleep(5)

            elif daq_num == 1:
                # LCLS-I DAQ
                from nabs.plans import daq_scan

                for run_idx in range(runs):
                    run_number = get_run(station=station) + 1

                    logger.info(
                        f"Run {run_idx + 1}/{runs} "
                        f"(Run Number {run_number}): "
                        f"{sample}... {quote()['quote']}"
                    )

                    # Execute scan
                    RE(daq_scan(
                        [],
                        motor,
                        scan_start,
                        scan_end,
                        scan_steps,
                        events=events_per_step,
                        record=record
                    ))

                    # Post to elog
                    if record:
                        scan_note = (
                            f"Scan: {motor_name} from {scan_start} to {scan_end}, "
                            f"{scan_steps} steps @ {events_per_step} events/step"
                        )

                        post(
                            sample=sample,
                            tag=tag,
                            run_number=run_number,
                            post=record,
                            inspire=inspire,
                            daq_num=daq_num,
                            add_note=scan_note
                        )

                    # Wait before next run
                    if run_idx < runs - 1:
                        sleep(5)

        except KeyboardInterrupt:
            logger.warning("Scan interrupted by user")

            # Cleanup
            if close:
                pp.close()

            if daq_num == 2:
                daq.control.setState("configured")
                while daq.control.getState() != "configured":
                    sleep(0.01)
                daq.control.setRecord(False)
                daq.control.setState("running")

            # Post abort note
            if record:
                post(
                    sample=sample,
                    tag=tag,
                    run_number=run_number,
                    post=record,
                    inspire=inspire,
                    daq_num=daq_num,
                    add_note=f"{scan_note}\nScan aborted by user"
                )

            logger.warning("Scan aborted. DAQ returned to safe state.")
            return

        # Cleanup
        if close:
            pp.close()
            logger.info("Pulse picker: CLOSED")

        if daq_num == 2:
            daq.control.setState("configured")
            while daq.control.getState() != "configured":
                sleep(0.01)
            daq.control.setRecord(False)
            daq.control.setState("running")
        elif daq_num == 1:
            daq.disconnect()

        logger.warning(
            f'Completed {runs} scan(s). '
            'Thank you for choosing the MFX beamline!\n'
        )

    def series(
            self,
            pv_values: List[float] = None,
            daq_delay: int = 5,
            scan_start: float = None,
            scan_end: float = None,
            scan_steps: int = None,
            events_per_step: int = 120,
            sample: str = '?',
            tag: str = None,
            picker: str = None,
            runs: int = 1,
            inspire: bool = False,
            record: bool = False,
            pv: str = 'lxt_fast',
            close: bool = True,
            daq_num: int = 2,
            exp: str = None):
        """
        Perform series of scans at different PV settings.

        Executes multiple scans, each at a different base PV value.
        Useful for parameter studies where you want to scan a motor
        at multiple fixed settings of another parameter.

        Parameters
        ----------
        pv_values : List[float] or None, required
            List of base PV values for each scan
            One scan executed per value
        daq_delay : int, optional
            Delay between scans in seconds (default: 5)
        scan_start : float, required
            Starting value for each scan
        scan_end : float, required
            Ending value for each scan
        scan_steps : int, required
            Number of steps in each scan
        events_per_step : int, optional
            Events per step (default: 120)
        sample : str, optional
            Sample name (default: '?')
        tag : str or None, optional
            Run tag (defaults to sample if None)
        picker : str or None, optional
            Pulse picker mode: 'open', 'flip', None
        runs : int, optional
            Number of repeats per scan (default: 1)
        inspire : bool, optional
            Add quotes to elog (default: False)
        record : bool, optional
            Enable recording (default: False)
        pv : str, optional
            PV to set for each scan (default: 'lxt_fast')
        close : bool, optional
            Close pulse picker when done (default: True)
        daq_num : int, optional
            DAQ version: 1 or 2 (default: 2)
        exp : str or None, optional
            Experiment name (auto-detected if None)

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If pv_values, scan_start, scan_end, or scan_steps is None
            If daq_num not in [1, 2]

        Notes
        -----
        Series Scan Sequence:
        1. Store original PV value
        2. For each value in pv_values:
           a. Set PV to value
           b. Perform full scan (scan_start to scan_end)
           c. Record data
           d. Post to elog
           e. Wait daq_delay
        3. Optionally return to original value
        4. Optionally analyze results

        Use Cases:

        Temperature Series:
        - Set different temperatures
        - Scan delay at each temperature
        - Study temperature dependence

        Voltage Series:
        - Set different voltages
        - Scan motor at each voltage
        - Characterize voltage response

        Energy Series:
        - Set different energies
        - Scan timing at each energy
        - Energy-dependent dynamics

        Data Organization:
        - Each scan gets unique run number
        - PV value stored in elog note
        - Can correlate scans in analysis

        Analysis:
        - Prompted after series completes
        - Can analyze all runs together
        - Extract trends vs. PV value

        Scan Duration:
        - Per scan: scan_steps × (events_per_step / rep_rate)
        - Total: duration × len(pv_values) × runs
        - Plus daq_delay between scans

        Examples
        --------
        Temperature series:
        >>> scan = Scan()
        >>> scan.series(
        ...     pv_values=[300, 310, 320, 330],  # K
        ...     scan_start=0.0,
        ...     scan_end=100.0,
        ...     scan_steps=21,
        ...     pv='TEMP:CONTROL',
        ...     sample='temp_study',
        ...     record=True
        ... )

        Voltage series with delay scan:
        >>> scan.series(
        ...     pv_values=[1.0, 2.0, 3.0, 4.0, 5.0],  # Volts
        ...     scan_start=-10.0,
        ...     scan_end=10.0,
        ...     scan_steps=41,
        ...     pv='MFX:VOLTAGE:01',
        ...     record=True
        ... )

        Multiple runs per setting:
        >>> scan.series(
        ...     pv_values=[100, 200, 300],
        ...     scan_start=0.0,
        ...     scan_end=50.0,
        ...     scan_steps=11,
        ...     runs=3,  # 3 scans at each PV value
        ...     pv='lxt_fast',
        ...     record=True
        ... )

        See Also
        --------
        scan : Single scan
        output : Analyze series results
        """
        from mfx.db import pp, daq
        from mfx.autorun import quote, autorun
        from mfx.macros import get_exp

        # Validate required parameters
        if pv_values is None or len(pv_values) == 0:
            logger.error("pv_values required for series scan")
            raise ValueError("Must provide list of PV values")

        if scan_start is None or scan_end is None or scan_steps is None:
            logger.error("scan_start, scan_end, and scan_steps required")
            raise ValueError("Must provide scan parameters")

        # Validate DAQ number
        if daq_num == 1:
            station = 1
        elif daq_num == 2:
            station = 0
        else:
            logger.error('daq_num must be 1 (LCLS-I) or 2 (LCLS-II)')
            raise ValueError("Invalid daq_num")

        # Get experiment
        if exp is None:
            exp = get_exp()

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

        # Store original PV value
        logger.info(f"Storing original {pv} value")
        original_val = self._get_pv_value(pv)

        # Get starting run number
        from mfx.macros import get_run
        first_run = get_run(station=station) + 1

        logger.info(
            f"Starting series: {len(pv_values)} scans, "
            f"first run = {first_run}"
        )

        # Execute series
        try:
            for idx, pv_val in enumerate(pv_values):
                logger.info(
                    f"Series scan {idx + 1}/{len(pv_values)}: "
                    f"Setting {pv} = {pv_val}"
                )

                # Set PV value
                self._set_pv_value(pv, pv_val)
                sleep(2)  # Allow settling time

                # Perform scan at this PV value
                self.scan(
                    scan_start=scan_start,
                    scan_end=scan_end,
                    scan_steps=scan_steps,
                    events_per_step=events_per_step,
                    sample=f"{sample}_pv{pv_val}",
                    tag=tag,
                    picker=None,  # Already configured
                    runs=runs,
                    inspire=inspire,
                    record=record,
                    pv=pv,
                    close=False,  # Don't close between scans
                    daq_num=daq_num,
                    exp=exp
                )

                # Wait before next scan
                if idx < len(pv_values) - 1:
                    sleep(daq_delay)

        except KeyboardInterrupt:
            logger.warning("Series interrupted by user")

        finally:
            # Cleanup
            if close:
                pp.close()

            # Prompt to return to original value
            logger.warning("Series completed. Return to original PV value?")
            answer = input("(y/n)? ")

            if answer.lower() == "y":
                logger.info(f"Returning {pv} to {original_val}")
                self._set_pv_value(pv, original_val)

        logger.warning('Series scan completed!\n')

    def _get_pv_value(self, pv: str) -> float:
        """
        Get current value of PV.

        Parameters
        ----------
        pv : str
            PV name or pre-defined motor

        Returns
        -------
        float
            Current PV value

        Notes
        -----
        Handles pre-defined motors and custom PVs.
        Uses appropriate method for each type.
        """
        from mfx.db import lxt_fast
        import os

        if pv.lower() == 'lxt_fast':
            from mfx.db import lxt_fast
            return lxt_fast.position
        elif pv.lower() == 'lxt':
            from mfx.db import lxt
            return lxt.position
        else:
            # Custom PV - use caget
            result = os.popen(f"caget -t {pv}").read().strip()
            return float(result)

    def _set_pv_value(self, pv: str, value: float):
        """
        Set PV to specified value.

        Parameters
        ----------
        pv : str
            PV name or pre-defined motor
        value : float
            Target value

        Notes
        -----
        Handles pre-defined motors and custom PVs.
        Uses appropriate method for each type.
        Waits for move completion.
        """
        import os

        if pv.lower() == 'lxt_fast':
            from mfx.db import lxt_fast
            lxt_fast.move(value, wait=True)
        elif pv.lower() == 'lxt':
            from mfx.db import lxt
            lxt.move(value, wait=True)
        else:
            # Custom PV - use caput
            os.system(f"caput {pv} {value}")
            sleep(1)  # Allow settling


# Convenience instance for direct import
scan = Scan()


def quick_scan(
        start: float,
        end: float,
        steps: int,
        pv: str = 'lxt_fast',
        sample: str = 'quick_scan',
        record: bool = False,
        **kwargs):
    """
    Convenience function for quick single scan.

    Parameters
    ----------
    start : float
        Starting value
    end : float
        Ending value
    steps : int
        Number of steps
    pv : str, optional
        PV to scan (default: 'lxt_fast')
    sample : str, optional
        Sample name (default: 'quick_scan')
    record : bool, optional
        Enable recording (default: False)
    **kwargs
        Additional arguments passed to Scan.scan()

    Returns
    -------
    None

    Examples
    --------
    >>> quick_scan(0.0, 100.0, 21, record=True)
    >>> quick_scan(-10, 10, 41, pv='MFX:MOTOR:01')

    See Also
    --------
    Scan.scan : Full implementation
    """
    scan.scan(
        scan_start=start,
        scan_end=end,
        scan_steps=steps,
        pv=pv,
        sample=sample,
        record=record,
        **kwargs
    )


def delay_scan(
        start: float,
        end: float,
        steps: int,
        sample: str = 'delay_scan',
        record: bool = False,
        **kwargs):
    """
    Convenience function for laser delay scan.

    Parameters
    ----------
    start : float
        Starting delay (mm or ps depending on motor)
    end : float
        Ending delay
    steps : int
        Number of steps
    sample : str, optional
        Sample name (default: 'delay_scan')
    record : bool, optional
        Enable recording (default: False)
    **kwargs
        Additional arguments passed to Scan.scan()

    Returns
    -------
    None

    Notes
    -----
    Uses lxt_fast motor by default.
    For lxt_fast: 1 mm ≈ 6.67 ps delay

    Examples
    --------
    Scan 0-100 mm (0-667 ps):
    >>> delay_scan(0.0, 100.0, 21, record=True)

    Fine scan:
    >>> delay_scan(10.0, 20.0, 101, sample='fine_delay', record=True)

    See Also
    --------
    Scan.scan : Full implementation
    quick_scan : General quick scan
    """
    scan.scan(
        scan_start=start,
        scan_end=end,
        scan_steps=steps,
        pv='lxt_fast',
        sample=sample,
        record=record,
        **kwargs
    )


def series_scan(
        pv_values: List[float],
        start: float,
        end: float,
        steps: int,
        pv: str = 'lxt_fast',
        sample: str = 'series',
        record: bool = False,
        **kwargs):
    """
    Convenience function for series of scans.

    Parameters
    ----------
    pv_values : List[float]
        List of PV values for each scan
    start : float
        Scan starting value
    end : float
        Scan ending value
    steps : int
        Number of scan steps
    pv : str, optional
        PV to set (default: 'lxt_fast')
    sample : str, optional
        Sample name (default: 'series')
    record : bool, optional
        Enable recording (default: False)
    **kwargs
        Additional arguments passed to Scan.series()

    Returns
    -------
    None

    Examples
    --------
    >>> series_scan(
    ...     pv_values=[100, 200, 300],
    ...     start=0.0,
    ...     end=50.0,
    ...     steps=11,
    ...     record=True
    ... )

    See Also
    --------
    Scan.series : Full implementation
    """
    scan.series(
        pv_values=pv_values,
        scan_start=start,
        scan_end=end,
        scan_steps=steps,
        pv=pv,
        sample=sample,
        record=record,
        **kwargs
    )


def alignment_scan(
        motor: str,
        center: float = 0.0,
        range: float = 2.0,
        steps: int = 21,
        sample: str = 'alignment',
        record: bool = False,
        **kwargs):
    """
    Convenience function for motor alignment scan.

    Scans motor symmetrically around center position.

    Parameters
    ----------
    motor : str Motor PV name
    center : float, optional
        Center position (default: 0.0)
    range : float, optional
        Total scan range (default: 2.0)
        Actual scan: center ± range/2
    steps : int, optional
        Number of steps (default: 21)
    sample : str, optional
        Sample name (default: 'alignment')
    record : bool, optional
        Enable recording (default: False)
    **kwargs
        Additional arguments

    Returns
    -------
    None

    Examples
    --------
    Scan ±1 mm around center:
    >>> alignment_scan('MFX:DG1:MMS:01', center=0.0, range=2.0)

    Fine alignment:
    >>> alignment_scan(
    ...     'MFX:DG1:MMS:01',
    ...     center=0.5,
    ...     range=0.2,
    ...     steps=41,
    ...     record=True
    ... )

    See Also
    --------
    quick_scan : General scan
    """
    start = center - range / 2.0
    end = center + range / 2.0

    scan.scan(
        scan_start=start,
        scan_end=end,
        scan_steps=steps,
        pv=motor,
        sample=sample,
        record=record,
        **kwargs
    )


# Module-level convenience instance
logger.info("Scan utilities loaded and ready")