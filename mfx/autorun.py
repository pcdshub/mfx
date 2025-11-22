"""
Automated data acquisition routines for MFX beamline.

Provides high-level functions for standard data collection runs with
automatic elog posting, pulse picker control, and DAQ management for
both LCLS-I and LCLS-II systems.
"""

import logging
import os
import json
import random
from time import sleep, time

logger = logging.getLogger(__name__)


def quote():
    """
    Get random inspirational quote.

    Returns
    -------
    dict
        Dictionary with 'quote' and 'author' keys

    Notes
    -----
    Quote Database:
    - Scientific quotes
    - Motivational messages
    - Humorous observations
    - Beamline-specific humor

    Used to add personality to run logs and keep users
    entertained during long experiments.

    Examples
    --------
    >>> q = quote()
    >>> print(f"{q['quote']} - {q['author']}")

    See Also
    --------
    post : Elog posting with optional quotes
    """

    quote_path = "/cds/home/d/djr/scripts/quotes.json"

    if not os.path.exists(quote_path):
        logger.warning(f"Quote file not found: {quote_path}")
        return {'quote': 'No quote available', 'author': 'Unknown'}

    try:
        with open(quote_path, 'rb') as f:
            quotes = json.loads(f.read())

        selected_quote = quotes[random.randint(0, len(quotes) - 1)]
        return {
            'quote': selected_quote['text'],
            'author': selected_quote['from']
        }
    except Exception as e:
        logger.warning(f"Failed to load quote: {e}")
        return {'quote': 'No quote available', 'author': 'Unknown'}


def post(sample, tag, run_number, post=True, inspire=False,
         daq_num=2, spread=None, add_note=''):
    """
    Post run information to electronic logbook (elog).

    Creates standardized elog entries with run metadata, sample
    information, and optional inspirational quotes.

    Parameters
    ----------
    sample : str
        Sample name or description
    tag : str
        Run tag for organization and searching
    run_number : int
        DAQ run number for reference
    post : bool, optional
        Actually post to elog if True. Default is True.
    inspire : bool, optional
        Include inspirational quote. Default is False.
    daq_num : int, optional
        DAQ station number (1 or 2). Default is 2.
    spread : str, optional
        Energy spread information if applicable. Default is None.
    add_note : str, optional
        Additional notes to append. Default is ''.

    Returns
    -------
    str
        The complete elog post message

    Notes
    -----
    Elog Entry Format:
    - Run number and sample name (header)
    - DAQ station identification
    - Energy spread information (if applicable)
    - Additional notes
    - Inspirational quote (if requested)
    - Tag for searching

    The elog provides permanent record of experimental conditions
    and facilitates data analysis and publication.

    Elog Location:
    - Web interface: https://pswww.slac.stanford.edu/apps/elog/
    - Command line: elog_post utility
    - Accessible from control room and remote

    Examples
    --------
    Basic run post:
    >>> post(sample='lysozyme', tag='crystals',
    ...      run_number=123, post=True)

    With inspiration:
    >>> post(sample='water', tag='background',
    ...      run_number=124, inspire=True)

    With energy spread:
    >>> post(sample='myprotein', tag='exafs',
    ...      run_number=125, spread='9000-9100 eV')

    With additional notes:
    >>> post(sample='test', tag='alignment',
    ...      run_number=126, add_note='Beam unstable during run')

    See Also
    --------
    quote : Quote generation
    autorun : Main acquisition function using post
    """
    from mfx.db import elog

    # Build message
    message = f"Run {run_number}: {sample}\n"
    message += f"DAQ: Station {daq_num}\n"

    if spread:
        message += f"Energy spread: {spread}\n"

    if add_note:
        message += f"\nNotes:\n{add_note}\n"

    if inspire:
        q = quote()
        message += f"\n---\n{q['quote']}\n  - {q['author']}"

    # Post to elog
    if post:
        logger.info(f"Posting to elog with tag '{tag}'")
        elog.post(msg=message, tags=tag, run=run_number)
    else:
        logger.info("Elog posting disabled (test mode)")
        logger.debug(f"Would have posted:\n{message}")

    return message


def ioc_cam_recorder(cam_name, duration, tag):
    """
    Record IOC camera data during acquisition.

    Starts IOC-based camera recording for specified duration,
    synchronized with DAQ data collection.

    Parameters
    ----------
    cam_name : str
        Camera IOC name (e.g., 'MFX:GIGE:01')
    duration : float
        Recording duration in seconds
    tag : str
        Tag for organizing camera files

    Returns
    -------
    None

    Notes
    -----
    Camera Recording:
    - Independent of main DAQ
    - Synchronized start time
    - Stored in separate files
    - Useful for diagnostics

    Camera Types:
    - GigE cameras: High-speed imaging
    - Basler cameras: Beam viewing
    - Prosilica cameras: Alignment
    - AVT cameras: Sample monitoring

    File Storage:
    - Default: /reg/d/camera/{hutch}/{cam_name}/
    - Tagged with run information
    - Accessible via camera viewer

    Warnings
    --------
    Ensure camera IOC is running and responsive before starting
    acquisition. Long recordings may fill disk space.

    Examples
    --------
    Record from GigE camera:
    >>> ioc_cam_recorder('MFX:GIGE:01', duration=60, tag='run123')

    Multiple cameras:
    >>> for cam in ['MFX:GIGE:01', 'MFX:BASLER:02']:
    ...     ioc_cam_recorder(cam, 30, 'run124')

    See Also
    --------
    autorun : Main acquisition using camera recording
    """
    logger.info(f"Starting camera recording: {cam_name}")
    logger.info(f"  Duration: {duration}s")
    logger.info(f"  Tag: {tag}")

    # Camera recording implementation would go here
    # Typically uses caput to IOC PVs
    cam_pv = f"{cam_name}:Acquire"
    duration_pv = f"{cam_name}:AcquireTime"

    try:
        os.system(f"caput {duration_pv} {duration}")
        os.system(f"caput {cam_pv} 1")
        logger.info("Camera recording started")
    except Exception as e:
        logger.error(f"Failed to start camera recording: {e}")


def autorun(
        sample: str = '?',
        tag: str = None,
        run_length: float = 60.0,
        inspire: bool = False,
        record: bool = False,
        runs: int = 5,
        daq_delay: int = 5,
        picker: str = None,
        close: bool = False,
        daq_num: int = 2,
        cam: str = None,
        run_type: str ='data'):
    """
    Execute automated data acquisition runs.

    High-level function for standard data collection with automatic
    pulse picker control, DAQ management, and elog posting. Supports
    both LCLS-I and LCLS-II DAQ systems.

    Parameters
    ----------
    sample : str
        Sample name for identification and logging
    tag : str, optional
        Run tag for organization. If None, uses sample name.
        Default is None.
    run_length : float, optional
        Duration of each run in seconds. If None, prompts user.
        Default is None.
    inspire : bool, optional
        Include inspirational quotes in elog posts.
        Automatically True for water samples. Default is False.
    record : bool, optional
        Enable data recording. If False, runs in test mode.
        Default is True.
    runs : int, optional
        Number of sequential runs to execute. Default is 1.
    daq_delay : int, optional
        Delay between runs in seconds. Allows time for sample
        changes or system adjustments. Default is 5.
    picker : str, optional
        Pulse picker mode: 'open' (full rate), 'flip' (alternating),
        or None (no change). Default is 'open'.
    close : bool, optional
        Close pulse picker after completion. Default is True.
    cam : str, optional
        Camera IOC name for synchronized recording.
        If None, no camera recording. Default is None.
    daq_num : int, optional
        DAQ station: 1 (LCLS-I) or 2 (LCLS-II). Default is 2.
    run_type : str, optional
        Run type identifier for organization: 'data', 'dark',
        'calibration', etc. Default is 'data'.

    Returns
    -------
    None

    Raises
    ------
    ValueError
        If daq_num not in [1, 2]

    Notes
    -----
    Workflow:
    1. Validate parameters
    2. Configure pulse picker
    3. For each run:
       a. Get run number
       b. Start camera if specified
       c. Configure and start DAQ
       d. Wait for completion
       e. Post to elog
       f. Wait daq_delay
    4. Close pulse picker if requested
    5. Cleanup and report

    Special Features:
    - Auto-inspire for water samples
    - Graceful KeyboardInterrupt handling
    - Automatic elog documentation
    - Camera synchronization
    - Both DAQ versions supported

    DAQ Differences:

    LCLS-I (daq_num=1):
    - daq.begin() blocking call
    - Simpler state machine
    - Legacy system
    - Still functional

    LCLS-II (daq_num=2):
    - DaqControl state machine
    - More flexible
    - Current standard
    - Better performance

    Warnings
    --------
    - Verify detector configuration before recording
    - Check disk space for long runs
    - Monitor beam stability
    - Ensure sample delivery working

    Examples
    --------
    Simple 60-second run:
    >>> autorun(sample='lysozyme', run_length=60, record=True)

    Multiple runs with delay:
    >>> autorun(sample='myprotein', run_length=120,
    ...         runs=5, daq_delay=10, record=True)

    With camera recording:
    >>> autorun(sample='test', run_length=30,
    ...         cam='MFX:GIGE:01', record=True)

    Test mode (no recording):
    >>> autorun(sample='test', run_length=10, record=False)

    Dark run:
    >>> autorun(sample='dark', run_length=60,
    ...         run_type='dark', picker=None, record=True)

    Water background with inspiration:
    >>> autorun(sample='water', run_length=30, inspire=True)
    # inspire automatically True for water

    See Also
    --------
    post : Elog posting function
    ioc_cam_recorder : Camera recording
    """
    from mfx.db import daq, pp
    from mfx.macros import get_run

    # Validate DAQ number
    if daq_num not in [1, 2]:
        logger.error('daq_num must be 1 (LCLS-I) or 2 (LCLS-II)')
        raise ValueError('Invalid daq_num')

    # Auto-inspire for water samples
    if sample.lower() in ['water', 'h2o']:
        inspire = True
        logger.info("Water sample detected - inspiration enabled")

    # Default tag to sample name
    if tag is None:
        tag = sample

    # Get run length if not specified
    if run_length is None:
        run_length = float(input("Run length in seconds: "))

    # Log configuration
    logger.info("\n" + "="*60)
    logger.info("AUTORUN CONFIGURATION")
    logger.info("="*60)
    logger.info(f"Sample: {sample}")
    logger.info(f"Tag: {tag}")
    logger.info(f"Run length: {run_length}s")
    logger.info(f"Number of runs: {runs}")
    logger.info(f"Recording: {record}")
    logger.info(f"DAQ: Station {daq_num}")
    logger.info(f"Run type: {run_type}")
    if cam:
        logger.info(f"Camera: {cam}")
    logger.info("="*60 + "\n")

    # Operate pulse picker
    if picker == 'open':
        logger.info("Opening pulse picker")
        pp.open()
    elif picker == 'flip':
        logger.info("Setting pulse picker to flip-flop mode")
        pp.flipflop()
    elif picker is None:
        logger.info("Pulse picker unchanged")

    # Execute runs based on DAQ version
    if daq_num == 2:
        _autorun_daq2(
            sample=sample, tag=tag, run_length=run_length,
            inspire=inspire, record=record, runs=runs,
            daq_delay=daq_delay, cam=cam, run_type=run_type,
            close=close
        )
    elif daq_num == 1:
        _autorun_daq1(
            sample=sample, tag=tag, run_length=run_length,
            inspire=inspire, record=record, runs=runs,
            daq_delay=daq_delay, cam=cam, run_type=run_type
        )

    # Close pulse picker if requested
    if close:
        logger.info("Closing pulse picker")
        pp.close()

    logger.info("\n" + "="*60)
    logger.info("AUTORUN COMPLETE")
    logger.info("="*60)
    logger.info(f"Completed {runs} run(s) successfully")
    logger.info("Thank you for using MFX!")
    logger.info("="*60 + "\n")


def _autorun_daq1(sample, tag, run_length, inspire, record,
                  runs, daq_delay, cam, run_type):
    """
    Execute autorun with LCLS-I DAQ (internal helper).

    Parameters
    ----------
    Same as autorun()

    Notes
    -----
    Uses daq.begin() blocking call for LCLS-I DAQ.
    Simpler than DAQ 2 but less flexible.
    Handles KeyboardInterrupt for graceful abort.

    See Also
    --------
    autorun : Main user interface
    _autorun_daq2 : LCLS-II implementation
    """
    from mfx.db import daq
    from mfx.macros import get_run

    logger.info("Using LCLS-I DAQ")

    status = True

    for run_idx in range(runs):
        try:
            station = 1
            run_number = get_run(station=station) + 1

            logger.info(f"\n{'='*60}")
            logger.info(f"RUN {run_idx + 1}/{runs}")
            logger. info(f"{'='*60}")
            logger.info(
                f"Run Number {run_number} Running {sample}..."
                f"...{quote()['quote']}"
            )

            # Start camera if specified
            if cam is not None:
                logger.info(f"Starting camera: {cam}")
                ioc_cam_recorder(cam, run_length, tag)

            # Configure and start DAQ
            logger.info("Configuring DAQ...")
            daq.configure(record=record)

            logger.info(f"Starting acquisition ({run_length}s)...")
            status = daq.begin(
                duration=run_length,
                record=record,
                wait=True,
                end_run=True
            )

            # Check for premature ending
            if status is False:
                logger.warning("Run ended prematurely")
                post(
                    sample=sample, tag=tag, run_number=run_number,
                    post=record, inspire=inspire, daq_num=1,
                    add_note='Run ended prematurely - possible sample '
                            'delivery issue'
                )
                break

            # Post to elog
            if record:
                logger.info("Posting to elog...")
                post(
                    sample=sample, tag=tag, run_number=run_number,
                    post=record, inspire=inspire, daq_num=1
                )

            # Wait before next run
            if run_idx < runs - 1:
                logger.info(f"Waiting {daq_delay}s before next run...")
                sleep(daq_delay)

        except KeyboardInterrupt:
            logger.warning("\nRun interrupted by user")
            from mfx.db import pp
            pp.close()
            if record:
                post(
                    sample=sample, tag=tag, run_number=run_number,
                    post=record, inspire=inspire, daq_num=1,
                    add_note='Run interrupted by user'
                )
            status = False
            break

    # Cleanup
    if status:
        daq.end_run()
        daq.disconnect()
        logger.info("DAQ1 runs completed successfully")
    else:
        logger.warning("DAQ1 runs ended with errors")


def _autorun_daq2(sample, tag, run_length, inspire, record,
                  runs, daq_delay, close, cam, run_type):
    """
    Execute autorun with LCLS-II DAQ (internal helper).

    Parameters
    ----------
    Same as autorun()

    Notes
    -----
    Uses DaqControl state machine for LCLS-II DAQ.
    More complex but more flexible than DAQ 1.
    Handles state transitions and error recovery.

    State Machine:
    - configured: Ready for acquisition
    - running: Actively recording
    - error: Fault condition

    See Also
    --------
    autorun : Main user interface
    _autorun_daq1 : LCLS-I implementation
    """
    from mfx.db import daq, pp
    from mfx.macros import get_run
    from psdaq.control.DaqControl import DaqControl

    logger.info("Using LCLS-II DAQ")

    for run_idx in range(runs):
        try:
            station = 0
            run_number = get_run(station=station) + 1

            logger.info(f"\n{'='*60}")
            logger.info(f"RUN {run_idx + 1}/{runs}")
            logger.info(f"{'='*60}")
            logger.info(
                f"Run Number {run_number} Running {sample}..."
                f"...{quote()['quote']}"
            )

            # Reconnect to DAQ
            logger.debug("Connecting to DAQ...")
            daq.control = DaqControl(
                host=daq.control.host,
                platform=daq.control.platform,
                timeout=10000
            )

            # Check connection
            instr = daq.control.getInstrument()
            if instr is None:
                logger.error('Failed to connect to LCLS-II DAQ')
                break

            # Check state
            start_state = daq.control.getState()
            logger.debug(f"DAQ initial state: {start_state}")
            if start_state == 'error':
                logger.error('DAQ is in error state')
                break

            # Start camera if specified
            if cam is not None:
                logger.info(f"Starting camera: {cam}")
                ioc_cam_recorder(cam, run_length, tag)

            # Configure DAQ
            logger.info("Configuring DAQ...")
            daq.control.setState("configured")
            while daq.control.getState() != "configured":
                sleep(0.01)

            # Set recording
            logger.debug(f"Setting record flag: {record}")
            daq.control.setRecord(record)

            # Start running
            logger.info(f"Starting acquisition ({run_length}s)...")
            daq.control.setState("running")
            while daq.control.getState() != "running":
                sleep(0.01)

            # Wait for run completion
            start_time = time()
            end_time = start_time + run_length

            while time() < end_time:
                current_state = daq.control.getState()
                if current_state != "running":
                    logger.warning(f"DAQ left running state: {current_state}")
                    break
                sleep(0.1)

            # Stop acquisition
            logger.info("Stopping acquisition...")
            daq.control.setState("configured")
            while daq.control.getState() != "configured":
                sleep(0.01)

            # Post to elog
            if record:
                logger.info("Posting to elog...")
                post(
                    sample=sample, tag=tag, run_number=run_number,
                    post=record, inspire=inspire, daq_num=2,
                    add_note=f"Run type: {run_type}"
                )

            # Wait before next run
            if run_idx < runs - 1:
                logger.info(f"Waiting {daq_delay}s before next run...")
                sleep(daq_delay)

        except KeyboardInterrupt:
            logger.warning("\nRun interrupted by user")
            pp.close()

            # Cleanup DAQ
            try:
                daq.control.setState("configured")
                while daq.control.getState() != "configured":
                    sleep(0.01)
            except:
                pass

            if record:
                post(
                    sample=sample, tag=tag, run_number=run_number,
                    post=record, inspire=inspire, daq_num=2,
                    add_note='Run interrupted by user'
                )
            break

    # Final cleanup
    logger.info("Cleaning up DAQ2...")
    try:
        daq.control.setRecord(False)
        daq.control.setState("running")
        logger.debug("DAQ returned to running/non-recording state")
    except Exception as e:
        logger.warning(f"DAQ cleanup warning: {e}")


def quick_run(sample, duration=60, record=True):
    """
    Quick data acquisition with minimal setup.

    Convenience function for standard runs with default parameters.

    Parameters
    ----------
    sample : str
        Sample name
    duration : float, optional
        Run duration in seconds. Default is 60.
    record : bool, optional
        Enable recording. Default is True.

    Returns
    -------
    None

    Examples
    --------
    >>> quick_run('lysozyme', duration=120)
    >>> quick_run('water', duration=30)

    See Also
    --------
    autorun : Full parameter control
    """
    logger.info(f"Quick run: {sample} for {duration}s")
    autorun(
        sample=sample,
        run_length=duration,
        record=record,
        runs=1,
        daq_num=2,
        picker='open',
        inspire=False
    )