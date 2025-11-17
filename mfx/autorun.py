"""Automated run control utilities for MFX beamline."""

import logging
from time import sleep, time

logger = logging.getLogger(__name__)


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
        run_type: str = ""):
    """
    Perform automated data acquisition runs.

    Executes multiple data acquisition runs with consistent timing and control.
    Supports both LCLS-I and LCLS-II DAQ systems with optional camera recording.

    Parameters
    ----------
    sample : str, optional
        Sample name (default: '?')
    tag : str or None, optional
        Run tag for organization (defaults to sample if None)
    run_length : float, optional
        Duration of each run in seconds (default: 60.0)
    inspire : bool, optional
        Add inspirational quote to elog posts (default: False)
    record : bool, optional
        Enable data recording (default: False)
        If False, runs in preview mode
    runs : int, optional
        Number of runs to execute (default: 5)
    daq_delay : int, optional
        Delay between runs in seconds (default: 5)
    picker : str or None, optional
        Pulse picker mode: 'open', 'flip', or None
        - 'open': Opens pulse picker before runs
        - 'flip': Flipflops pulse picker before runs
        - None: No pulse picker operation
    close : bool, optional
        Close pulse picker after completion (default: False)
    daq_num : int, optional
        DAQ version: 1 (LCLS-I) or 2 (LCLS-II) (default: 2)
    cam : str or None, optional
        Camera IOC name for synchronized recording (default: None)
        Example: 'MFX:GIGE:01'
    run_type : str, optional
        Run type label for DAQ metadata (default: "")
        Examples: 'dark', 'sample', 'background'

    Returns
    -------
    None

    Raises
    ------
    ValueError
        If daq_num not in [1, 2]

    Notes
    -----
    DAQ Control:
    - DAQ 1 (LCLS-I): Uses daq.begin() with blocking wait
    - DAQ 2 (LCLS-II): Uses DaqControl state machine with progress bar

    Special Behavior:
    - Automatically sets inspire=True for 'water' or 'h2o' samples
    - Posts run information to elog if record=True
    - Handles KeyboardInterrupt for graceful abort

    Run Sequence:
    1. Configure pulse picker
    2. For each run:
       a. Get run number
       b. Configure DAQ with run_type
       c. Start camera recording (if specified)
       d. Execute run with progress indication
       e. Post results to elog (if recording)
       f. Wait daq_delay before next run
    3. Close pulse picker (if requested)

    Progress Display:
    - DAQ 2: Shows real-time progress bar with percentage
    - DAQ 1: Simple status messages

    Error Handling:
    - KeyboardInterrupt: Posts premature end note to elog, cleans up DAQ
    - DAQ errors: Logs errors and exits cleanly

    Examples
    --------
    Basic automated run:
    >>> autorun(
    ...     sample='lysozyme',
    ...     run_length=120,
    ...     runs=10,
    ...     record=True
    ... )

    Run with camera recording:
    >>> autorun(
    ...     sample='water',
    ...     run_length=60,
    ...     cam='MFX:GIGE:01',
    ...     record=True,
    ...     runs=5
    ... )

    Dark run with custom type:
    >>> autorun(
    ...     sample='dark',
    ...     run_length=30,
    ...     run_type='dark',
    ...     record=True,
    ...     picker='open'
    ... )

    See Also
    --------
    ioc_cam_recorder : Camera recording function
    post : Elog posting function
    """
    from mfx.db import daq, pp
    from mfx.autorun import quote, post
    from mfx.macros import get_run

    # Validate DAQ number
    if daq_num not in [1, 2]:
        logger.error('daq_num must be 1 (LCLS-I) or 2 (LCLS-II)')
        raise ValueError('Invalid daq_num')

    # Auto-inspire for water samples
    if sample.lower() in ['water', 'h2o']:
        inspire = True

    # Default tag to sample name
    if tag is None:
        tag = sample

    # Operate pulse picker
    if picker == 'open':
        pp.open()
    elif picker == 'flip':
        pp.flipflop()

    # Execute runs based on DAQ version
    if daq_num == 2:
        _autorun_daq2(
            sample=sample,
            tag=tag,
            run_length=run_length,
            inspire=inspire,
            record=record,
            runs=runs,
            daq_delay=daq_delay,
            close=close,
            cam=cam,
            run_type=run_type
        )
    elif daq_num == 1:
        _autorun_daq1(
            sample=sample,
            tag=tag,
            run_length=run_length,
            inspire=inspire,
            record=record,
            runs=runs,
            daq_delay=daq_delay,
            close=close,
            cam=cam
        )

    # Close pulse picker
        pp.close()


def _autorun_daq2(
        sample: str,
        tag: str,
        run_length: float,
        inspire: bool,
        record: bool,
        runs: int,
        daq_delay: int,
        close: bool,
        cam: str,
        run_type: str):
    """
    Execute automated runs using LCLS-II DAQ.

    Parameters
    ----------
    sample : str
        Sample name
    tag : str
        Run tag
    run_length : float
        Run duration in seconds
    inspire : bool
        Add inspirational quotes
    record : bool
        Enable recording
    runs : int
        Number of runs
    daq_delay : int
        Delay between runs in seconds
    close : bool
        Close pulse picker when done
    cam : str or None
        Camera IOC name
    run_type : str
        Run type label

    Notes
    -----
    Uses DaqControl state machine for LCLS-II DAQ.
    Displays real-time progress bar during acquisition.
    Handles KeyboardInterrupt for graceful abort.
    """
    from mfx.db import daq, pp
    from mfx.autorun import quote, post
    from mfx.macros import get_run
    from psdaq.control.DaqControl import DaqControl

    try:
        for run_idx in range(runs):
            run_number = get_run(station=0) + 1
            logger.info(f"Run Number {run_number} Running {sample}......{quote()['quote']}")

            # Setup DAQ
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
            if start_state == 'error':
                logger.error('DAQ is in error state')
                break

            # Configure
            daq.control.setState("configured")
            while daq.control.getState() != "configured":
                sleep(0.01)

            # Set recording
            daq.control.setRecord(record)

            # Start running with run_type
            daq.control.setState("running", {"run_type": run_type})
            while daq.control.getState() != "running":
                sleep(0.01)

            # Start camera if specified
            if cam is not None:
                ioc_cam_recorder(cam, run_length, tag)

            # Display progress bar
            _show_progress_bar(run_length)

            # Stop DAQ
            daq.control.setState("configured")
            while daq.control.getState() != "configured":
                sleep(0.01)

            # Post to elog
            if record:
                post(
                    sample=sample,
                    tag=tag,
                    run_number=run_number,
                    post=record,
                    inspire=inspire,
                    daq_num=2
                )

            # Wait before next run
            if run_idx < runs - 1:
                sleep(daq_delay)

    except KeyboardInterrupt:
        logger.warning("[*] Stopping Run and exiting...")

        # Cleanup DAQ
        daq.control.setState("configured")
        while daq.control.getState() != "configured":
            sleep(0.01)
        daq.control.setRecord(False)
        daq.control.setState("running")

        # Close pulse picker
        pp.close()

        # Post abort notice
        if record:
            post(
                sample=sample,
                tag=tag,
                run_number=run_number,
                post=record,
                inspire=inspire,
                daq_num=2,
                add_note='Run ended prematurely. Probably sample delivery problem'
            )

        logger.warning('Run ended prematurely. Probably sample delivery problem')
        return

    # Cleanup
    if close:
        pp.close()

    daq.control.setState("configured")
    while daq.control.getState() != "configured":
        sleep(0.01)
    daq.control.setRecord(False)
    daq.control.setState("running")

    logger.warning('Finished with all runs thank you for choosing the MFX beamline!\n')


def _autorun_daq1(
        sample: str,
        tag: str,
        run_length: float,
        inspire: bool,
        record: bool,
        runs: int,
        daq_delay: int,
        close: bool,
        cam: str):
    """
    Execute automated runs using LCLS-I DAQ.

    Parameters
    ----------
    sample : str
        Sample name
    tag : str
        Run tag
    run_length : float
        Run duration in seconds
    inspire : bool
        Add inspirational quotes
    record : bool
        Enable recording
    runs : int
        Number of runs
    daq_delay : int
        Delay between runs in seconds
    close : bool
        Close pulse picker when done
    cam : str or None
        Camera IOC name

    Notes
    -----
    Uses daq.begin() blocking call for LCLS-I DAQ.
    Simpler than DAQ 2 but less flexible.
    Handles KeyboardInterrupt for graceful abort.
    """
    from mfx.db import daq, pp
    from mfx.autorun import quote, post
    from mfx.macros import get_run

    status = True

    for run_idx in range(runs):
        run_number = get_run(station=1) + 1
        logger.info(f"Run Number {run_number} Running {sample}......{quote()['quote']}")

        # Execute run
        status = _daq_begin(duration=run_length, record=record, wait=True, end_run=True)

        # Start camera if specified
        if cam is not None:
            ioc_cam_recorder(cam, run_length, tag)

        # Check status
        if status is False:
            pp.close()
            post(
                sample=sample,
                tag=tag,
                run_number=run_number,
                post=record,
                inspire=inspire,
                daq_num=1,
                add_note='Run ended prematurely. Probably sample delivery problem'
            )
            logger.warning("[*] Stopping Run and exiting...")
            sleep(5)
            daq.stop()
            daq.disconnect()
            logger.warning('Run ended prematurely. Probably sample delivery problem')
            break

        # Post to elog
        post(
            sample=sample,
            tag=tag,
            run_number=run_number,
            post=record,
            inspire=inspire,
            daq_num=1
        )

        try:
            sleep(daq_delay)
        except KeyboardInterrupt:
            pp.close()
            logger.warning("[*] Stopping Run and exiting...")
            sleep(5)
            daq.disconnect()
            status = False
            if status is False:
                logger.warning('Run ended prematurely. Probably sample delivery problem')
                break

    # Cleanup
    if status:
        if close:
            pp.close()
        daq.end_run()
        daq.disconnect()
        logger.warning('Finished with all runs thank you for choosing the MFX beamline!\n')


def _show_progress_bar(duration: float):
    """
    Display real-time progress bar for run duration.

    Parameters
    ----------
    duration : float
        Total duration in seconds

    Notes
    -----
    Updates progress bar every second with:
    - Visual bar (60 characters wide)
    - Percentage complete
    - Carriage return for in-place update

    Final bar shows 100% completion.

    Examples
    --------
    Progress display:
    Progress: [============================------------------------------] 47%
    """
    start_time = time()
    end_time = start_time + duration

    while time() < end_time:
        elapsed_time = time() - start_time
        progress = min(elapsed_time / duration, 1.0)  # Cap at 100%

        filled_length = int(60 * progress)
        bar = '=' * filled_length + '-' * (60 - filled_length)

        percentage = f"{progress:.0%}"

        print(f"\rProgress: [{bar}] {percentage}", end="", flush=True)

        sleep(1)  # Update every second

    # Final complete bar
    print("\rProgress: [" + "=" * 60 + "] 100%", flush=True)


def ioc_cam_recorder(cam='camera name', run_length=10, tag='?'):
    """
    Record camera images during acquisition.

    Configures camera IOC to save images with proper naming and timing.

    Parameters
    ----------
    cam : str
        Camera IOC prefix (e.g., 'MFX:GIGE:01')
    duration : float
        Recording duration in seconds
    tag : str
        Tag for filename generation

    Notes
    -----
    Camera Configuration:
    - Sets auto-save mode to 'Stream'
    - Configures file plugin for TIFF format
    - Sets filename pattern with tag
    - Starts acquisition for specified duration

    Examples --------
    Record 60 seconds of images:
    >>> ioc_cam_recorder(
    ...     cam='MFX:GIGE:01',
    ...     duration=60.0,
    ...     tag='water_sample'
    ... )

    See Also
    --------
    autorun : Main automated run function
    """
    import subprocess
    from epics import caget
    import logging
    from mfx.bash_utilities import BashUtilities
    bs = BashUtilities()
    camera_names = bs.camera_list_out()
    if cam not in [pv[1] for pv in camera_names]:
            logging.info("Desired Camera not in List. Please choose from the above list:.")
    else:
        rate = caget(f'{cam}:ArrayRate_RBV')
        n_images = int(run_length * rate)
        logging.info(f"Recording Camera {cam} for {run_length} sec")
        logging.info(
            f"/reg/g/pcds/engineering_tools/latest-released/scripts/image_saver "
            f"-c {cam} -n {n_images} -f {tag} -p /cds/data/iocData")

        subprocess.Popen(
            [f"source /cds/group/pcds/pyps/conda/pcds_conda; "
            f"/reg/g/pcds/engineering_tools/latest-released/scripts/image_saver "
            f"-c {cam} -n {n_images} -f {tag} -p /cds/data/iocData"],
            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

def quote():
    """
    Get random inspirational quote.

    Returns
    -------
    dict
        Dictionary with 'quote' and 'author' keys

    Notes
    -----
    Loads quotes from JSON file at /cds/home/d/djr/scripts/quotes.json.
    Returns random quote from available collection.

    Examples
    --------
    >>> q = quote()
    >>> print(f"{q['quote']} - {q['author']}")
    Science is magic that works. - Kurt Vonnegut
    """
    import json
    import random
    from os import path

    quote_path = "/cds/home/d/djr/scripts/quotes.json"

    if not path.exists(quote_path):
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


def post(
        sample: str = '?',
        tag: str = None,
        run_number: int = None,
        post: bool = False,
        inspire: bool = False,
        daq_num: int = 2,
        add_note: str = ''):
    """
    Post run information to electronic logbook.

    Parameters
    ----------
    sample : str, optional
        Sample name (default: '?')
    tag : str or None, optional
        Run tag (defaults to sample if None)
    run_number : int or None, optional
        Run number (auto-detected if None)
    post : bool, optional
        Actually post to elog if True (default: False)
        If False, only prints message to console
    inspire : bool, optional
        Include inspirational quote (default: False)
    daq_num : int, optional
        DAQ number for station selection (default: 2)
    add_note : str, optional
        Additional note to append (default: '')

    Returns
    -------
    str
        Complete post message

    Notes
    -----
    Message Format:
    - Run number and sample name
    - Inspirational quote (if inspire=True)
    - Additional notes (if provided)

    Always prints message to console.
    Only posts to elog if post=True.

    Station mapping:
    - daq_num=1: Station 1 (LCLS-I)
    - daq_num=2: Station 0 (LCLS-II)

    Examples
    --------
    Post with quote:
    >>> post(
    ...     sample='water',
    ...     run_number=123,
    ...     post=True,
    ...     inspire=True
    ... )

    Post with additional note:
    >>> post(
    ...     sample='lysozyme',
    ...     run_number=456,
    ...     post=True,
    ...     add_note='Changed flow rate to 10 uL/min'
    ... )
    """
    from mfx.db import elog
    from mfx.macros import get_run

    # Default tag to sample
    if tag is None:
        tag = sample

    # Get run number if not provided
    if run_number is None:
        station = 1 if daq_num == 1 else 0
        run_number = get_run(station=station)

    # Build message
    message = f"Running {sample}"

    if inspire:
        q = quote()
        message += f"\n{q['quote']}"

    if add_note:
        message += f"\n{add_note}"

    # Format post
    post_msg = f"Run Number {run_number}: {message}"

    # Print to console
    print(f'\n{post_msg}\n')

    # Post to elog if requested
    if post:
        elog.post(msg=post_msg, tags=tag, run=run_number)

    return post_msg


def _daq_begin(
        duration: float = 300.0,
        record: bool = False,
        wait: bool = True,
        end_run: bool = True,
        use_l3t: bool = True):
    """
    Begin DAQ acquisition (LCLS-I compatibility wrapper).

    Wrapper around daq.begin() with additional status handling
    and keyboard interrupt support.

    Parameters
    ----------
    duration : float, optional
        Acquisition duration in seconds (default: 300.0)
    record : bool, optional
        Enable recording (default: False)
    wait : bool, optional
        Block until completion (default: True)
    end_run : bool, optional
        End run after completion (default: True)
    use_l3t : bool, optional
        Use L3 trigger (default: True)

    Returns
    -------
    bool
        True if acquisition completed successfully, False otherwise

    Notes
    -----
    Behavior:
    - If wait=True: Blocks until completion or interrupt
    - If wait=False and end_run=True: Spawns thread for cleanup
    - Handles KeyboardInterrupt gracefully

    Additional sleep controlled by daq.config['begin_sleep']
    to ensure DAQ is fully started.

    Examples
    --------
    Blocking acquisition:
    >>> _daq_begin(duration=60, record=True, wait=True)
    True

    Non-blocking with auto-end:
    >>> _daq_begin(duration=120, record=True, wait=False, end_run=True)
    True

    See Also
    --------
    autorun : Main automated run function
    """
    import threading
    from mfx.db import daq

    status = True

    try:
        # Configure DAQ
        if not hasattr(daq, 'config'):
            daq.config = {'begin_sleep': 0}

        # Begin acquisition
        daq.begin(
            duration=duration,
            record=record,
            use_l3t=use_l3t
        )

        # Additional sleep for DAQ startup
        sleep(daq.config.get('begin_sleep', 0))

        # Wait for completion if requested
        if wait:
            daq.wait()
            if end_run:
                daq.end_run()

        # Spawn cleanup thread if non-blocking
        if end_run and not wait:
            threading.Thread(target=daq._ender_thread, args=()).start()

        return status

    except KeyboardInterrupt:
        logger.warning("DAQ acquisition interrupted by user")
        status = False
        return status


# Convenience aliases
run = autorun
auto_run = autorun
automated_run = autorun