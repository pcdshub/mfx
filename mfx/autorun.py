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
from datetime import datetime
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


# ---------------------------------------------------------------------------
# Elog samples
#
# The elog attaches a run to a sample by itself: when a run starts, it copies
# the experiment's *active* sample onto the run. autorun therefore only has to
# make the right sample active before the DAQ starts. Only one sample can be
# active per experiment (shared by everyone), and each activation posts an
# elog entry, so a sample is only activated when it changes.
# ---------------------------------------------------------------------------

class SampleError(Exception):
    """An elog sample request failed."""


def _sample_ws(method, endpoint, **kwargs):
    """
    Call an experiment endpoint of the elog web service.

    Reuses the login of the hutch-python ``elog`` object (Kerberos or
    ws-auth), so it works wherever elog posts work.

    The elog answers HTTP 200 with ``success: false`` on application errors
    (locked experiment, missing rights, unknown sample...), so the JSON is
    checked and not only the HTTP status.
    """
    import requests
    from mfx.db import elog

    service = elog.service
    exp = elog.logbooks['experiment']
    url = f"{service._lgbk_base_url}/lgbk/{exp}/ws/{endpoint}"
    resp = requests.request(method, url, timeout=10, **service._auth,
                            **kwargs)
    resp.raise_for_status()
    result = resp.json()
    if not result.get('success', False):
        reason = result.get('errormsg') or result.get('error_msg') or result
        raise SampleError(f"{endpoint} failed: {reason}")
    return result.get('value')


def list_samples():
    """
    Return the names of all samples defined in the experiment elog.

    Examples
    --------
    >>> list_samples()
    ['Lyso', 'Thermolysin']
    """
    return [s['name'] for s in _sample_ws('GET', 'samples/')]


def get_sample():
    """
    Return the name of the active elog sample, or None if none is active.

    Runs started now are attached to this sample by the elog.

    Examples
    --------
    >>> get_sample()
    'Lyso'
    """
    return _sample_ws('GET', 'current_sample_name') or None


def set_sample(name, description=None):
    """
    Make ``name`` the active elog sample, creating it if needed.

    Every run started afterwards is attached to this sample by the elog,
    until another sample is activated. Only one sample can be active per
    experiment, so this applies to everyone taking data on it.

    Parameters
    ----------
    name : str
        Sample name. If a sample with the same name in a different case
        exists (e.g. 'lyso' for 'Lyso'), that one is used rather than
        creating a near-duplicate: samples with runs cannot be deleted.
    description : str, optional
        Description used if the sample is created.
        Default is 'Created by autorun on <date>'.

    Returns
    -------
    str
        Name of the active sample (existing spelling if matched).

    Examples
    --------
    >>> set_sample('Lyso', description='lysozyme 30 mg/ml')
    >>> autorun(run_length=60, runs=5, record=True)   # runs go to Lyso

    See Also
    --------
    get_sample, clear_sample, list_samples
    """
    existing = list_samples()
    if name not in existing:
        same = [s for s in existing if s.lower() == name.lower()]
        if same:
            logger.warning(f"Using existing elog sample '{same[0]}' "
                           f"for '{name}'")
            name = same[0]
        else:
            if not description:
                description = (f"Created by autorun on "
                               f"{datetime.now():%Y-%m-%d %H:%M}")
            _sample_ws('POST', 'samples/', json={
                'name': name, 'description': description, 'params': {}})
            print(f"Created new elog sample '{name}'")

    if get_sample() != name:
        _sample_ws('GET', 'make_sample_current',
                   params={'sample_name': name})
        print(f"Elog sample '{name}' is now active")
    return name


def clear_sample():
    """
    Deactivate the active elog sample; runs started afterwards get none.
    """
    current = get_sample()
    if current is not None:
        _sample_ws('GET', 'stop_current_sample',
                   params={'sample_name': current})
        print(f"Elog sample '{current}' deactivated")


def _activate_sample(sample):
    """
    Choose the elog sample for the coming runs and make it active.

    - ``sample`` given: created if needed and activated.
    - ``sample`` None: the active sample is kept; if none is active, the
      runs get no sample.

    Elog errors are logged and never stop the runs.

    Returns
    -------
    str or None
        Name of the sample the runs will be attached to.
    """
    try:
        if sample is None:
            sample = get_sample()
            logger.info(f"Using active elog sample: {sample}")
            return sample
        return set_sample(sample)
    except Exception as e:
        logger.warning(f"Could not set elog sample ({e}); runs may not be "
                       f"attached to a sample")
        return sample


def _check_run_sample(run_number, sample):
    """
    Make sure ``run_number`` is attached to ``sample`` in the elog.

    The elog normally does it at run start from the active sample; this is
    a safety net (``change_sample_for_run`` needs the elog 'edit' role).
    Errors are only logged.
    """
    try:
        run = _sample_ws('GET', f'runs/{run_number}')
        if run is None:
            logger.warning(f"Run {run_number} not found in elog, cannot "
                           f"check its sample")
            return
        # ws/runs/<n> expands the sample into the full sample document
        run_sample = run.get('sample')
        if isinstance(run_sample, dict) and run_sample.get('name') == sample:
            return
        _sample_ws('GET', 'change_sample_for_run',
                   params={'run_num': run_number, 'sample_name': sample})
        logger.info(f"Run {run_number} attached to elog sample '{sample}'")
    except Exception as e:
        logger.warning(f"Could not check elog sample of run {run_number}: "
                       f"{e}")


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
    message = f"Run {run_number}: {sample or 'no sample'}\n"
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


def _autorun(
        sample: str = None,
        tag: str = None,
        run_length: float = 60.0,
        inspire: bool = False,
        record: bool = False,
        runs: int = 5,
        daq_delay: int = 5,
        picker: str = None,
        close: bool = True,
        daq_num: int = 2,
        cam: str = None,
        run_type: str ='data',
        elog_sample: bool = True):
    """
    Execute automated data acquisition runs.

    High-level function for standard data collection with automatic
    pulse picker control, DAQ management, and elog posting. Supports
    both LCLS-I and LCLS-II DAQ systems.

    Parameters
    ----------
    sample : str, optional
        Sample name. When recording, the runs are attached to this elog
        sample: it is created if it does not exist yet, and made active.
        If None, the currently active elog sample is used; if no sample
        is active, the runs get no sample. Default is None.
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
    elog_sample : bool, optional
        Create/activate the elog sample. Set False when ``sample`` is only
        a label (e.g. an energy in a scan). Default is True.

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
    from mfx.db import daq, mfx_pulsepicker
    from mfx.macros import get_run

    # Validate DAQ number
    if daq_num not in [1, 2]:
        logger.error('daq_num must be 1 (LCLS-I) or 2 (LCLS-II)')
        raise ValueError('Invalid daq_num')

    # Elog sample: the elog attaches each new run to the active sample
    if record and elog_sample:
        sample = _activate_sample(sample)

    # Auto-inspire for water samples
    if sample and sample.lower() in ['water', 'h2o']:
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
        mfx_pulsepicker.open()
    elif picker == 'flip':
        logger.info("Setting pulse picker to flip-flop mode")
        mfx_pulsepicker.flipflop()
    elif picker is None:
        logger.info("Pulse picker unchanged")

    # Execute runs based on DAQ version
    if daq_num == 2:
        _autorun_daq2(
            sample=sample, tag=tag, run_length=run_length,
            inspire=inspire, record=record, runs=runs,
            daq_delay=daq_delay, cam=cam, run_type=run_type,
            close=close, check_sample=record and elog_sample
        )
    elif daq_num == 1:
        _autorun_daq1(
            sample=sample, tag=tag, run_length=run_length,
            inspire=inspire, record=record, runs=runs,
            daq_delay=daq_delay, cam=cam, run_type=run_type,
            check_sample=record and elog_sample
        )

    # Close pulse picker if requested
    if close:
        logger.info("Closing pulse picker")
        mfx_pulsepicker.close()

    logger.info("\n" + "="*60)
    logger.info("AUTORUN COMPLETE")
    logger.info("="*60)
    logger.info(f"Completed {runs} run(s) successfully")
    logger.info("Thank you for using MFX!")
    logger.info("="*60 + "\n")

def _display_progress(run_length):
    """
    Display simple progress bar during run.
    Parameters
    ----------
    run_length : float
        Total run length in seconds
    Returns
    -------
    None
    Notes
    -----
    Updates progress bar in terminal.
    """
    # Simple progress bar
    start_time = time()
    end_time = start_time + run_length

    while time() < end_time:
        elapsed_time = time() - start_time
        progress = min(elapsed_time / run_length, 1)  # Ensure progress doesn't exceed 1

        filled_length = int(60 * progress)
        bar = '=' * filled_length + '-' * (60 - filled_length)

        percentage = f"{progress:.0%}"

        print(f"\rProgress: [{bar}] {percentage}", end="")

        sleep(0.2)  # Update frequency
    return


def _autorun_daq1(sample, tag, run_length, inspire, record,
                  runs, daq_delay, cam, run_type, check_sample=False):
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
                if check_sample and sample:
                    _check_run_sample(run_number, sample)

            # Wait before next run
            if run_idx < runs - 1:
                logger.info(f"Waiting {daq_delay}s before next run...")
                sleep(daq_delay)

        except KeyboardInterrupt:
            logger.warning("\nRun interrupted by user")
            from mfx.db import mfx_pulsepicker
            mfx_pulsepicker.close()
            daq.disconnect()
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
                  runs, daq_delay, close, cam, run_type,
                  check_sample=False):
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
    from mfx.db import daq, mfx_pulsepicker
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
            _display_progress(run_length)

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
                if check_sample and sample:
                    _check_run_sample(run_number, sample)

            # Wait before next run
            if run_idx < runs - 1:
                logger.info(f"Waiting {daq_delay}s before next run...")
                sleep(daq_delay)

        except KeyboardInterrupt:
            logger.warning("\nRun interrupted by user")
            mfx_pulsepicker.close()

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


def autorun(**kwargs):
    _autorun(**kwargs)


def geomrun(**kwargs):
    """
    Geometry calibration runs, attached to the 'geometry-calibration'
    elog sample.

    When recording, the elog sample that was active before is restored
    afterwards, so later autorun() calls keep going to the user's sample.
    """
    kwargs['tag'] = "geom"
    kwargs['sample'] = "geometry-calibration"
    kwargs['run_type'] = "GEOM"
    if not kwargs.get('record', False):
        _autorun(**kwargs)
        return

    try:
        previous = get_sample()
    except Exception as e:
        logger.warning(f"Could not read active elog sample ({e}); it will "
                       f"not be restored after geomrun")
        _autorun(**kwargs)
        return

    try:
        _autorun(**kwargs)
    finally:
        try:
            if previous is None:
                clear_sample()
            else:
                set_sample(previous)
        except Exception as e:
            logger.warning(f"Could not restore elog sample "
                           f"'{previous}': {e}")


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