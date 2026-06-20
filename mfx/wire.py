"""
Wire scanner control and scanning utilities for MFX beamline.

Provides automated wire scanner operations for beam profiling,
position verification, and intensity measurements.
"""

import os
import logging
import numpy as np
from typing import Optional, List
from mfx.timing import Timing
timing=Timing()

logger = logging.getLogger(__name__)


class Wire:
    """
    Wire scanner control for beam profiling and alignment.

    Provides automated scans of thin wire targets through the X-ray beam
    to measure beam profile, position, and intensity distribution.

    Wire scanners use two motors (X and Y) to position a thin wire
    or edge across the beam. By measuring transmitted or scattered
    intensity while scanning, the beam profile can be reconstructed.

    Components
    ----------
    Motors:
        x_pv : str
            X-axis motor PV (MFX:USR:MMN:41)
        y_pv : str
            Y-axis motor PV (MFX:USR:MMN:42)

    Attributes
    ----------
    x_pv : str
        EPICS PV for X motor
    y_pv : str
        EPICS PV for Y motor

    Notes
    -----
    Wire Scanner Applications:
    - Beam size measurement
    - Beam position verification
    - Intensity profile mapping
    - Alignment verification
    - Focus characterization

    Scan Types:
    - Line scan: 1D profile (X or Y)
    - Grid scan: 2D intensity map (both X and Y)
    - Edge scan: Beam edge detection

    Typical Workflow:
    1. Position wire near beam
    2. Perform scan across beam
    3. Record intensity vs. position
    4. Analyze profile offline
    5. Extract beam parameters

    Beam Parameters from Wire Scan:
    - Beam width (FWHM)
    - Beam centroid position
    - Beam shape (Gaussian, flat-top, etc.)
    - Peak intensity
    - Background level

    Wire Scanner vs. Profile Monitor:
    - Wire: High resolution, destructive
    - Profile: Lower resolution, non-destructive
    - Wire: Manual scan required
    - Profile: Real-time imaging

    Safety Considerations:
    - Wire can be damaged by beam
    - Use minimal exposure time
    - Check wire condition regularly
    - Avoid high flux if possible

    Examples
    --------
    Create wire scanner:
    >>> wire = Wire()

    Perform X scan:
    >>> wire.scan(
    ...     start=-2.0,
    ...     end=2.0,
    ...     num_steps=41,
    ...     mcc='x',
    ...     record=True
    ... )

    Perform Y scan:
    >>> wire.scan(
    ...     start=-1.0,
    ...     end=1.0,
    ...     num_steps=21,
    ...     mcc='y',
    ...     record=True
    ... )

    Quick scan without recording:
    >>> wire.scan(
    ...     start=-1.0,
    ...     end=1.0,
    ...     num_steps=11,
    ...     mcc='x',
    ...     record=False
    ... )

    See Also
    --------
    get : Read current motor positions
    put : Move motors to positions
    output : Analyze scan results
    """

    def __init__(
            self,
            x_pv: str = 'MFX:LJH:JET:X',
            y_pv: str = 'MFX:LJH:JET:Y'):
        """
        Initialize Wire scanner controller.
        Parameters
        ----------
        x_pv : str, optional
            EPICS PV for X motor (default: 'MFX:LJH:JET:X')
        y_pv : str, optional
            EPICS PV for Y motor (default: 'MFX:LJH:JET:Y')
        """
        # self.x_pv = 'MFX:USR:MMN:41' #DoT motors
        # self.y_pv = 'MFX:USR:MMN:42'
        self.x_pv = x_pv
        self.y_pv = y_pv
        logger.info("Wire scanner initialized")

    def scan(
            self,
            start: float,
            end: float,
            num_steps: int,
            events_per_step: int = 120,
            sample: str = 'wire',
            tag: str = None,
            picker: str = None,
            inspire: bool = False,
            record: bool = False,
            daq_num: int = 2,
            pv: str = None,
            camera: str = 'alvium_dg3',
            analysis: bool = True):

        """
        Perform wire scan across beam.

        Executes automated scan of wire motor through specified range
        while collecting data with DAQ. Useful for beam profiling,
        alignment verification, and focus characterization.

        Parameters
        ----------
        start : float
            Starting position in mm
        end : float
            Ending position in mm
        num_steps : int
            Number of scan steps
            Step size = (end - start) / (num_steps - 1)
        events_per_step : int, optional
            Number of events to collect per step (default: 120)
            At 120 Hz, this is 1 second per point
        sample : str, optional
            Sample/scan name (default: 'wire')
        tag : str or None, optional
            Run tag for organization (defaults to sample if None)
        picker : str or None, optional
            Pulse picker mode: 'open', 'flip', or None
            - 'open': All pulses pass
            - 'flip': Alternating pulses for background
            - None: Current picker state
        inspire : bool, optional
            Add inspirational quote to elog (default: False)
        record : bool, optional
            Enable data recording (default: False)
        daq_num : int, optional
            DAQ version: 1 (LCLS-I) or 2 (LCLS-II) (default: 2)
        pv : str or None, required
            Motor to scan: 'x' or 'y'
        camera : str, optional
            Detector name for timing analysis camera (default: 'alvium_dg3')
        analysis : bool, optional
            Prompt for automatic analysis after scan completion,
            by default True.

        Returns
        -------
        None

        Raises
        ------
        SystemExit
            If pv not 'x' or 'y'
        ValueError
            If daq_num not in [1, 2]

        Notes
        -----
        Scan Sequence:
        1. Configure pulse picker
        2. Get run number
        3. Setup motor for scanning
        4. Configure DAQ with motor information
        5. For each step:
           a. Move motor to position
           b. Collect events_per_step
           c. Record data
        6. Close pulse picker
        7. Post results to elog

        DAQ Integration:
        - DAQ 1 (LCLS-I): Uses daq_scan plan
        - DAQ 2 (LCLS-II): Uses Bluesky scan plan
        - Motor positions stored in DAQ metadata
        - Intensities recorded per position

        Scan Duration:
        - Total time ≈ num_steps × (events_per_step / rep_rate)
        - Example: 41 steps × 120 events @ 120 Hz = 41 seconds
        - Plus motor move overhead (~0.5 s/step)

        Data Output:
        - Run number automatically assigned
        - Motor positions in metadata
        - Detector intensities vs. position
        - Can be analyzed offline

        Position Range:
        - Should span beam width
        - Include background on both sides
        - Typical: ±2× beam width

        Step Size Selection:
        - Nyquist: ≥2 points per beam width
        - Recommended: 5-10 points per beam width
        - Fine: 20+ points per beam width

        Typical Beam Widths:
        - Unfocused: 1-5 mm
        - Focused: 0.01-0.1 mm
        - Adjust range accordingly

        Analysis Options:
        - Prompt after scan to analyze
        - Runs on S3DF or NERSC
        - Generates profile plots
        - Extracts beam parameters

        Examples
        --------
        Standard X profile scan:
        >>> wire = Wire()
        >>> wire.scan(
        ...     start=-2.0,
        ...     end=2.0,
        ...     num_steps=41,
        ...     events_per_step=120,
        ...     sample='beam_profile_x',
        ...     pv='x',
        ...     record=True
        ... )

        High-resolution Y scan:
        >>> wire.scan(
        ...     start=-0.5,
        ...     end=0.5,
        ...     num_steps=101,
        ...     events_per_step=240,
        ...     sample='fine_profile_y',
        ...     pv='y',
        ...     record=True
        ... )

        Quick test scan:
        >>> wire.scan(
        ...     start=-1.0,
        ...     end=1.0,
        ...     num_steps=11,
        ...     events_per_step=60,
        ...     pv='x',
        ...     record=False
        ... )

        Scan with pulse picker:
        >>> wire.scan(
        ...     start=-2.0,
        ...     end=2.0,
        ...     num_steps=41,
        ...     pv='x',
        ...     picker='open',
        ...     record=True
        ... )
        
        Scan with non-default camera:
        >>> wire.scan(
        ...     start=-2.0,
        ...     end=2.0,
        ...     num_steps=41,
        ...     pv='x',
        ...     camera='t_zero_alvium',
        ...     record=True
        ... )

        See Also
        --------
        output : Analyze scan results
        get.x : Read X position
        get.y : Read Y position
        """
        from ophyd import EpicsSignal
        from pcdsdevices.pv_positioner import OnePVMotor
        from mfx.db import RE, pp, daq
        from mfx.autorun import quote, post
        from mfx.macros import get_exp, get_run

        # Validate motor selection
        if pv is None:
            logger.error("Must specify pv='x' or pv='y'")
            import sys
            sys.exit("No motor specified")

        pv = pv.lower()
        if pv not in ['x', 'y']:
            logger.error("pv must be 'x' or 'y'")
            import sys
            sys.exit("Invalid motor selection")

        # Validate motor selection
        if pv is None:
            logger.error("Must specify pv='x' or pv='y' or custom pv")
            import sys
            sys.exit("No motor specified")

        if pv not in ['x', 'y']:
            logger.warning("pv not 'x' or 'y'. using custom PV: {pv}")

        # Validate DAQ number
        if daq_num not in [1, 2]:
            logger.error('daq_num must be 1 (LCLS-I) or 2 (LCLS-II)')
            raise ValueError("Invalid daq_num")

        # Select motor PV
        if pv.lower() == 'x':
            pv = self.x_pv
            axis_name = 'X'
        elif pv.lower() == 'y':
            pv = self.y_pv
            axis_name = 'Y'
        else:
            pv = axis_name= pv.upper()

        logger.info(
            f"Starting {axis_name}-axis wire scan: "
            f"{start} to {end} mm in {num_steps} steps"
        )

        # Default tag
        if tag is None:
            tag = sample

        # Configure pulse picker
        if picker == 'open':
            pp.open()
            logger.info("Pulse picker: OPEN")
        elif picker == 'flip':
            pp.flipflop()
            logger.info("Pulse picker: FLIPFLOP")

        # Get run number
        station = 1 if daq_num == 1 else 0
        run_number = get_run(station=station) + 1

        logger.info(
            f"Run Number {run_number}: {sample}... {quote()['quote']}"
        )

        # Execute scan based on DAQ version
        if daq_num == 1:
            # LCLS-I DAQ
            from nabs.plans import daq_scan

            # Create motor object
            pv_motor = EpicsSignal(pv, name='pv')

            # Run scan
            RE(
                daq_scan(
                    [],
                    pv_motor,
                    start,
                    end,
                    num_steps,
                    events=events_per_step,
                    record=record
                )
            )

            # Cleanup
            daq.disconnect()

        elif daq_num == 2:
            # LCLS-II DAQ
            import bluesky.plans as bp

            # Create motor object
            pv_motor = OnePVMotor(pv, name="mcc")
            pv_motor.setpoint.kind = "hinted"

            original = pv_motor()

            # Configure DAQ
            daq.configure(
                motors=[pv_motor],
                group_mask=0x1,
                events=events_per_step,
                record=record
            )

            # Run scan
            RE(bp.scan(
                [daq],
                pv_motor,
                start,
                end,
                num_steps
            ))

        # Close pulse picker
        pp.close()
        logger.info("Pulse picker: CLOSED")

        # Post to elog
        scan_note = (
            f"Wire {axis_name}-scan: {start} to {end} mm, "
            f"{num_steps} steps @ {events_per_step} events/step"
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

        logger.warning(
            'Wire scan completed. '
            'Thank you for choosing the MFX beamline!\n'
        )

        exp = str(get_exp())
        logger.warning(
                f"timing.output(user='user', facility='s3df', "
                f"exp='{exp}', run={run_number}, daq_num={daq_num})")

        logger.info(f'Setting {pv} back to original: {original}')
        pv_motor(original)

        if analysis:
            logger.warning(f"Scan completed. Would you like to analyze the output?")
            answer = input("(y/n)? ")

            if answer.lower() == "y":
                facility = input("Enter facility (s3df or nersc) to continue: ")
                user = input("Enter username to continue: ")
                timing.output(
                    user=user,
                    facility=facility,
                    exp=exp,
                    run=run_number,
                    daq_num=daq_num,
                    camera=camera)