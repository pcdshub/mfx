"""
Wire scanner control and scanning utilities for MFX beamline.

Provides automated wire scanner operations for beam profiling,
position verification, and intensity measurements.
"""

import os
import logging
from typing import Optional, List

import numpy as np

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

    def __init__(self):
        """
        Initialize Wire scanner controller.

        Sets up motor PV connections for X and Y axes.
        """
        self.x_pv = 'MFX:USR:MMN:41'
        self.y_pv = 'MFX:USR:MMN:42'
        logger.info("Wire scanner initialized")

    def scan(
            self,
            start: float,
            end: float,
            num_steps: int,
            num_events: int = 120,
            sample: str = 'wire',
            tag: str = None,
            picker: str = None,
            inspire: bool = False,
            record: bool = False,
            daq_num: int = 2,
            mcc: str = None):
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
        num_events : int, optional
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
        mcc : str or None, required
            Motor to scan: 'x' or 'y'

        Returns
        -------
        None

        Raises
        ------
        SystemExit
            If mcc not 'x' or 'y'
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
           b. Collect num_events
           c. Record data
        6. Close pulse picker
        7. Post results to elog

        DAQ Integration:
        - DAQ 1 (LCLS-I): Uses daq_scan plan
        - DAQ 2 (LCLS-II): Uses Bluesky scan plan
        - Motor positions stored in DAQ metadata
        - Intensities recorded per position

        Scan Duration:
        - Total time ≈ num_steps × (num_events / rep_rate)
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
        ...     num_events=120,
        ...     sample='beam_profile_x',
        ...     mcc='x',
        ...     record=True
        ... )

        High-resolution Y scan:
        >>> wire.scan(
        ...     start=-0.5,
        ...     end=0.5,
        ...     num_steps=101,
        ...     num_events=240,
        ...     sample='fine_profile_y',
        ...     mcc='y',
        ...     record=True
        ... )

        Quick test scan:
        >>> wire.scan(
        ...     start=-1.0,
        ...     end=1.0,
        ...     num_steps=11,
        ...     num_events=60,
        ...     mcc='x',
        ...     record=False
        ... )

        Scan with pulse picker:
        >>> wire.scan(
        ...     start=-2.0,
        ...     end=2.0,
        ...     num_steps=41,
        ...     mcc='x',
        ...     picker='open',
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
        if mcc is None:
            logger.error("Must specify mcc='x' or mcc='y'")
            import sys
            sys.exit("No motor specified")

        mcc = mcc.lower()
        if mcc not in ['x', 'y']:
            logger.error("mcc must be 'x' or 'y'")
            import sys
            sys.exit("Invalid motor selection")

        # Validate DAQ number
        if daq_num not in [1, 2]:
            logger.error('daq_num must be 1 (LCLS-I) or 2 (LCLS-II)')
            raise ValueError("Invalid daq_num")

        # Select motor PV
        if mcc == 'x':
            mcc_pv = self.x_pv
            axis_name = 'X'
        else:
            mcc_pv = self.y_pv
            axis_name = 'Y'

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
            mcc_pv_motor = EpicsSignal(mcc_pv, name='mcc')

            # Run scan
            RE(
                daq_scan(
                    [],
                    mcc_pv_motor,
                    start,
                    end,
                    num_steps,
                    events=num_events,
                    record=record
                )
            )

            # Cleanup
            daq.disconnect()

        elif daq_num == 2:
            # LCLS-II DAQ
            import bluesky.plans as bp

            # Create motor object
            mcc_pv_motor = OnePVMotor(mcc_pv, name="mcc")
            mcc_pv_motor.setpoint.kind = "hinted"

            # Configure DAQ
            daq.configure(
                motors=[mcc_pv_motor],
                group_mask=0x1,
                events=num_events,
                record=record
            )

            # Run scan
            RE(bp.scan(
                [daq],
                mcc_pv_motor,
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
            f"{num_steps} steps @ {num_events} events/step"
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

        # Prompt for analysis
        logger.warning("Scan completed. Analyze output?")
        answer = input("(y/n)? ")

        if answer.lower() == "y":
            facility = input("Facility (S3DF/NERSC): ")
            user = input("Username: ")

            if facility.upper() in ['S3DF', 'NERSC']:
                self.output(
                    user=user,
                    facility=facility.upper(),
                    exp=get_exp(),
                    run=run_number
                )
            else:
                logger.warning(f"Unknown facility: {facility}")

    def output(
            self,
            user: str,
            facility: str = 'S3DF',
            run_type: str = 'scan',
            exp: str = None,
            run: int = None):
        """
        Analyze wire scan results.

        Submits analysis job to computing facility to process
        wire scan data and generate beam profile plots.

        Parameters
        ----------
        user : str
            Username for SSH and computing access
        facility : str, optional
            Computing facility: 'S3DF' or 'NERSC' (default: 'S3DF')
        run_type : str, optional
            Analysis type (default: 'scan')
            Currently only 'scan' is supported
        exp : str or None, optional
            Experiment name (e.g., 'mfxls1234')
            If None, uses current experiment
        run : int or None, optional
            Run number to analyze
            If None, uses most recent run

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If facility not 'S3DF' or 'NERSC'

        Notes
        -----
        Analysis Process:
        1. SSH to computing facility
        2. Load run data from HDF5
        3. Extract motor positions
        4. Extract detector intensities
        5. Generate profile plots
        6. Fit beam profile (Gaussian, etc.)
        7. Extract beam parameters
        8. Save results

        Analysis Scripts:
        - S3DF: /sdf/group/lcls/ds/tools/mfx/scripts/wire_scan_analysis.py
        - NERSC: Similar path on NERSC filesystem

        Output Products:
        - Profile plots (PNG/PDF)
        - Fitted parameters (text/CSV)
        - Beam width (FWHM)
        - Beam centroid
        - Peak intensity

        Beam Profile Fits:
        - Gaussian: Most common for focused beams
        - Flat-top: For unfocused beams
        - Error function: For edge scans

        SSH Requirements:
        - Valid account on facility
        - SSH keys configured
        - Network access
        - NERSC may require token (sshproxy)

        Processing Time:
        - Typical : 1-5 minutes
        - Check status: squeue -u $USER

        Results Location:
        - Experiment analysis directory
        - /reg/d/pscdata/mfx/{exp}/scratch/

        Examples
        --------
        Analyze on S3DF:
        >>> wire = Wire()
        >>> wire.output(
        ...     user='myuser',
        ...     facility='S3DF',
        ...     exp='mfxls1234',
        ...     run=123
        ... )

        Analyze most recent run:
        >>> wire.output(user='myuser', facility='S3DF')

        Analyze on NERSC:
        >>> wire.output(
        ...     user='myuser',
        ...     facility='NERSC',
        ...     exp='mfxls1234',
        ...     run=123
        ... )

        See Also
        --------
        scan : Perform wire scan
        """
        from mfx.db import daq
        from mfx.macros import get_exp
        import mfx.cctbx as cctbx

        logger.info("Submitting wire scan analysis")

        # Get experiment name
        if exp is None:
            exp = str(get_exp())

        # Get run number
        if run is None:
            run = daq.run_number()

        # Validate facility
        facility = facility.upper()
        if facility not in ['S3DF', 'NERSC']:
            logger.error(
                f"Unknown facility: {facility}. Use 'S3DF' or 'NERSC'"
            )
            raise ValueError("Invalid facility")

        # Handle NERSC SSH proxy
        if facility == 'NERSC':
            logger.warning("Have you renewed your SSH token today?")
            token = input("(y/n)? ")

            if token.lower() == "n":
                cctbx.sshproxy(user)

        # Build and execute analysis command
        if facility == 'S3DF':
            cmd = (
                f"ssh -Yt {user}@s3dflogin "
                f"source /sdf/group/lcls/ds/ana/sw/conda1/manage/bin/psconda.sh; "
                f"python /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/"
                f"energy_calib_output.py "
                f"-f {facility} -t {run_type} -e {exp} -r {run}"
            )
        else:  # NERSC
            cmd = (
                f"ssh -Yt {user}@perlmutter-p1.nersc.gov "
                f"python /global/cfs/cdirs/lcls/mfxopr/scripts/"
                f"wire_scan_analysis.py "
                f"-f {facility} -t {run_type} -e {exp} -r {run}"
            )

        logger.info(f"Executing: {cmd}")
        os.system(cmd)

        logger.info(
            f"Analysis submitted to {facility}. "
            "Check results in experiment directory."
        )

    class get:
        """
        Read current wire motor positions.

        Provides static methods to query current X and Y positions
        of the wire scanner motors.

        Methods
        -------
        x() : str
            Get current X position
        y() : str
            Get current Y position

        Examples
        --------
        >>> x_pos = Wire.get.x()
        >>> y_pos = Wire.get.y()
        >>> print(f"Wire at ({x_pos}, {y_pos}) mm")

        See Also
        --------
        put : Move motors to positions
        """

        def __init__(self):
            """Initialize get interface."""
            pass

        @staticmethod
        def x() -> str:
            """
            Get current X motor position.

            Returns
            -------
            str
                X position in mm

            Notes
            -----
            Uses caget to read EPICS PV.
            Returns position as string from PV.

            Examples
            --------
            >>> x_pos = Wire.get.x()
            >>> print(f"X position: {x_pos} mm")

            See Also
            --------
            y : Get Y position
            put.x : Set X position
            """
            os.system('caget MFX:USR:MMN:41')
            value = os.popen(
                "caget MFX:USR:MMN:41 | awk '{print $2}'"
            ).read().strip()
            return value

        @staticmethod
        def y() -> str:
            """
            Get current Y motor position.

            Returns
            -------
            str
                Y position in mm

            Notes
            -----
            Uses caget to read EPICS PV.
            Returns position as string from PV.

            Examples
            --------
            >>> y_pos = Wire.get.y()
            >>> print(f"Y position: {y_pos} mm")

            See Also
            --------
            x : Get X position
            put.y : Set Y position
            """
            os.system('caget MFX:USR:MMN:42')
            value = os.popen(
                "caget MFX:USR:MMN:42 | awk '{print $2}'"
            ).read().strip()
            return value

    class put:
        """
        Move wire motors to specified positions.

        Provides static methods to move X and Y motors
        to desired positions.

        Methods
        -------
        x(value) : None
            Move X motor to position
        y(value) : None
            Move Y motor to position

        Notes
        -----
        Motion is non-blocking by default.
        Use get methods to verify final position.

        Safety:
        - No limit checking in this class
        - Motor limits enforced by EPICS
        - Be cautious near beam

        Examples
        --------
        >>> Wire.put.x(0.0)  # Move X to zero
        >>> Wire.put.y(-1.5)  # Move Y to -1.5 mm

        See Also
        --------
        get : Read current positions
        """

        def __init__(self):
            """Initialize put interface."""
            pass

        @staticmethod
        def x(value: float):
            """
            Move X motor to specified position.

            Parameters
            ----------
            value : float
                Target X position in mm

            Returns
            -------
            None

            Notes
            -----
            Uses caput to write to EPICS PV.
            Motion is asynchronous (non-blocking).

            Motor Limits:
            - Enforced by EPICS
            - Typically ±5 mm
            - Check motor configuration

            Safety:
            - Verify position before moving
            - Check beam status
            - Avoid collisions

            Examples
            --------
            Move to center:
            >>> Wire.put.x(0.0)

            Move to +2 mm:
            >>> Wire.put.x(2.0)

            Move and verify:
            >>> Wire.put.x(1.5)
            >>> import time
            >>> time.sleep(1)  # Wait for motion
            >>> pos = Wire.get.x()
            >>> print(f"Moved to {pos} mm")

            See Also
            --------
            get.x : Read X position
            y : Move Y motor
            """
            os.system(f'caput MFX:USR:MMN:41 {value}')
            logger.info(f"Moving wire X to {value} mm")

        @staticmethod
        def y(value: float):
            """
            Move Y motor to specified position.

            Parameters
            ----------
            value : float
                Target Y position in mm

            Returns
            -------
            None

            Notes
            -----
            Uses caput to write to EPICS PV.
            Motion is asynchronous (non-blocking).

            Motor Limits:
            - Enforced by EPICS
            - Typically ±5 mm
            - Check motor configuration

            Safety:
            - Verify position before moving
            - Check beam status
            - Avoid collisions

            Examples
            --------
            Move to center:
            >>> Wire.put.y(0.0)

            Move to -1 mm:
            >>> Wire.put.y(-1.0)

            Move and verify:
            >>> Wire.put.y(0.5)
            >>> import time
            >>> time.sleep(1)  # Wait for motion
            >>> pos = Wire.get.y()
            >>> print(f"Moved to {pos} mm")

            See Also
            --------
            get.y : Read Y position
            x : Move X motor
            """
            os.system(f'caput MFX:USR:MMN:42 {value}')
            logger.info(f"Moving wire Y to {value} mm")


# Convenience instance for direct import
wire = Wire()


def wire_scan(
        start: float,
        end: float,
        num_steps: int,
        mcc: str,
        num_events: int = 120,
        record: bool = False,
        **kwargs):
    """
    Convenience function to perform wire scan.

    Parameters
    ----------
    start : float
        Starting position in mm
    end : float
        Ending position in mm
    num_steps : int
        Number of scan steps
    mcc : str
        Motor to scan: 'x' or 'y'
    num_events : int, optional
        Events per step (default: 120)
    record : bool, optional
        Enable recording (default: False)
    **kwargs
        Additional arguments passed to Wire.scan()

    Returns
    -------
    None

    Examples
    --------
    >>> wire_scan(-2.0, 2.0, 41, mcc='x', record=True)
    >>> wire_scan(-1.0, 1.0, 21, mcc='y', num_events=240)

    See Also
    --------
    Wire.scan : Full implementation
    """
    wire.scan(
        start=start,
        end=end,
        num_steps=num_steps,
        num_events=num_events,
        mcc=mcc,
        record=record,
        **kwargs
    )


def get_wire_position() -> tuple:
    """
    Get current wire (X, Y) position.

    Returns
    -------
    tuple
        (x_position, y_position) in mm

    Examples
    --------
    >>> x, y = get_wire_position()
    >>> print(f"Wire at ({x}, {y}) mm")

    See Also
    --------
    set_wire_position : Move wire to position
    Wire.get : Get individual positions
    """
    x = float(Wire.get.x())
    y = float(Wire.get.y())
    return (x, y)


def set_wire_position(x: Optional[float] = None, y: Optional[float] = None):
    """
    Move wire to specified position.

    Parameters
    ----------
    x : float or None, optional
        X position in mm (None = don't move X)
    y : float or None, optional
        Y position in mm (None = don't move Y)

    Returns
    -------
    None

    Examples
    --------
    Move both axes:
    >>> set_wire_position(x=0.0, y=0.0)

    Move X only:
    >>> set_wire_position(x=1.5)

    Move Y only:
    >>> set_wire_position(y=-0.5)

    See Also
    --------
    get_wire_position : Read current position
    Wire.put : Move individual motors
    """
    if x is not None:
        Wire.put.x(x)

    if y is not None:
        Wire.put.y(y)


def analyze_wire_scan(
        user: str,
        facility: str = 'S3DF',
        exp: str = None,
        run: int = None):
    """
    Convenience function to analyze wire scan.

    Parameters
    ----------
    user : str
        Username for computing facility
    facility : str, optional
        'S3DF' or 'NERSC' (default: 'S3DF')
    exp : str or None, optional
        Experiment name
    run : int or None, optional
        Run number

    Returns
    -------
    None

    Examples
    --------
    >>> analyze_wire_scan('myuser', exp='mfxls1234', run=123)
    >>> analyze_wire_scan('myuser', facility='NERSC')

    See Also
    --------
    Wire.output : Full implementation
    """
    wire.output(
        user=user,
        facility=facility,
        exp=exp,
        run=run
    )


def home_wire():
    """
    Move wire to home position (0, 0).

    Returns
    -------
    None

    Examples
    --------
    >>> home_wire()

    See Also
    --------
    set_wire_position : Move to arbitrary position
    """
    logger.info("Homing wire scanner to (0, 0)")
    set_wire_position(x=0.0, y=0.0)


def park_wire(x_park: float = -10.0, y_park: float = -10.0):
    """
    Park wire scanner out of beam path.

    Parameters
    ----------
    x_park : float, optional
        X park position in mm (default: -10.0)
    y_park : float, optional
        Y park position in mm (default: -10.0)

    Returns
    -------
    None

    Notes
    -----
    Parks wire at specified position, typically
    well outside the beam path for safety.

    Default park position is (-10, -10) mm,
    which should be clear of typical beam.

    Examples
    --------
    >>> park_wire()  # Use default
    >>> park_wire(x_park=-5.0, y_park=-5.0)  # Custom

    See Also
    --------
    home_wire : Return to center position
    """
    logger.info(f"Parking wire scanner at ({x_park}, {y_park}) mm")
    set_wire_position(x=x_park, y=y_park)