"""Attenuator scan utilities for MFX beamline."""

import logging
from time import sleep

logger = logging.getLogger(__name__)


def attenuator_scan(
        sample: str = '?',
        tag: str = None,
        transmissions: list = None,
        inspire: bool = False,
        duration: float = 10.0,
        record: bool = False,
        use_daq: bool = True,
        runs: int = 5,
        daq_delay: int = 5,
        picker: str = None,
        daq_num: int = 2):
    """
    Perform attenuator transmission scan.

    Scans through specified attenuator transmission values while
    collecting data with DAQ. Useful for measuring flux dependence
    or calibrating detectors.

    Parameters
    ----------
    sample : str, optional
        Sample name (default: '?')
    tag : str or None, optional
        Run tag (defaults to sample if None)
    transmissions : list or None, optional
        List of transmission values (0-1) to scan
        Default: [1.0, 0.5, 0.1, 0.05, 0.01]
    inspire : bool, optional
        Add inspirational quote to elog (default: False)
    duration : float, optional
        Acquisition time per transmission in seconds (default: 5.0)
    record : bool, optional
        Enable data recording (default: False)
    use_daq : bool, optional
        Use DAQ for acquisition (default: True)
        If False, runs without DAQ control
    runs : int, optional
        Number of complete scans to perform (default: 5)
    daq_delay : int, optional
        Delay between runs in seconds (default: 5)
    picker : str or None, optional
        Pulse picker mode: 'open', 'flip', or None
    daq_num : int, optional
        DAQ version to use: 1 (LCLS-I) or 2 (LCLS-II) (default: 2)

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
    - DAQ 1 (LCLS-I): Uses daq.configure() and daq.begin()
    - DAQ 2 (LCLS-II): Uses DaqControl state machine

    Pulse Picker:
    - 'open': Opens pulse picker before scan
    - 'flip': Flipflops pulse picker before scan
    - None: No pulse picker operation

    Special Behavior:
    - Sets inspire=True automatically if sample is 'water' or 'h2o'

    Procedure for each run:
    1. Get run number from DAQ
    2. Configure DAQ if recording
    3. For each transmission value:
       a. Set attenuator
       b. Acquire data for specified duration
    4. Post results to elog
    5. Wait daq_delay before next run

    The attenuator is accessed via mfx.db.att.
    DAQ is accessed via mfx.db.daq.

    Examples
    --------
    Basic transmission scan:
    >>> attenuator_scan(
    ...     sample='water',
    ...     transmissions=[1.0, 0.5, 0.1],
    ...     duration=10,
    ...     record=True
    ... )

    Scan without DAQ (manual timing):
    >>> attenuator_scan(
    ...     sample='test',
    ...     transmissions=[1.0, 0.5],
    ...     use_daq=False,
    ...     duration=5
    ... )
    """
    from mfx.db import att, pp, daq
    from mfx.autorun import quote, post
    from mfx.macros import get_run

    # Default transmission values
    if transmissions is None:
        transmissions = [1.0, 0.5, 0.1, 0.05, 0.01]

    # Auto-inspire for water samples
    if sample.lower() in ['water', 'h2o']:
        inspire = True

    # Default tag to sample name
    if tag is None:
        tag = sample

    # Validate DAQ number
    if daq_num not in [1, 2]:
        logger.error('daq_num must be 1 (LCLS-I) or 2 (LCLS-II)')
        raise ValueError('Invalid daq_num')

    # Operate pulse picker
    if picker == 'open':
        pp.open()
    elif picker == 'flip':
        pp.flipflop()

    # Main scan loop
    for run_idx in range(runs):

        # Determine station based on DAQ version
        station = 1 if daq_num == 1 else 0
        run_number = get_run(station=station) + 1

        logger.info(f"Run Number {run_number} Running {sample}......{quote()['quote']}")

        # Setup DAQ
        if use_daq:
            if daq_num == 2:
                # LCLS-II DAQ setup
                if not _setup_daq_lcls2(record):
                    logger.error('Failed to setup LCLS-II DAQ')
                    break
            elif daq_num == 1:
                # LCLS-I DAQ setup
                daq.configure(record=record)
                sleep(3)

        # Scan through transmissions
        for transmission in transmissions:
            att(transmission, wait=True)

            if use_daq and daq_num == 1:
                sleep(3)
                daq.begin(duration=duration, record=record, wait=True, use_l3t=False)
            else:
                sleep(duration)

        # Cleanup DAQ
        if use_daq:
            if daq_num == 2:
                _cleanup_daq_lcls2()
            elif daq_num == 1:
                daq.end_run()
                daq.disconnect()

        # Post to elog
        if record:
            sample_transmissions = f"{sample} \n transmissions: {transmissions}"
            post(
                sample=sample,
                tag=tag,
                run_number=run_number,
                post=record,
                inspire=inspire,
                daq_num=daq_num,
                add_note=sample_transmissions
            )

        # Close pulse picker after run
        pp.close()

        # Wait before next run
        if run_idx < runs - 1:
            sleep(daq_delay)


def _setup_daq_lcls2(record: bool) -> bool:
    """
    Setup LCLS-II DAQ for acquisition.

    Parameters
    ----------
    record : bool
        Enable recording if True

    Returns
    -------
    bool
        True if setup successful, False otherwise

    Notes
    -----
    Connects to DAQ, checks state, configures recording,
    and transitions to running state.
    Uses 10000ms timeout for connection.
    """
    from mfx.db import daq
    from psdaq.control.DaqControl import DaqControl

    # Reconnect to DAQ
    daq.control = DaqControl(
        host=daq.control.host,
        platform=daq.control.platform,
        timeout=10000
    )

    # Check connection
    instr = daq.control.getInstrument()
    if instr is None:
        logger.error('Failed to connect to LCLS-II DAQ')
        return False

    # Check state
    start_state = daq.control.getState()
    if start_state == 'error':
        logger.error('DAQ is in error state')
        return False

    # Configure
    daq.control.setState("configured")
    while daq.control.getState() != "configured":
        sleep(0.01)

    # Set recording
    daq.control.setRecord(record)

    # Start running
    daq.control.setState("running")
    while daq.control.getState() != "running":
        sleep(0.01)

    return True


def _cleanup_daq_lcls2():
    """
    Cleanup LCLS-II DAQ after acquisition.

    Stops recording and returns DAQ to configured state.

    Notes
    -----
    Reconnects to DAQ with fresh DaqControl instance
    to ensure clean state transitions.
    """
    from mfx.db import daq
    from psdaq.control.DaqControl import DaqControl

    # Reconnect to DAQ
    daq.control = DaqControl(
        host=daq.control.host,
        platform=daq.control.platform,
        timeout=10000
    )

    # Stop recording
    daq.control.setState("configured")
    while daq.control.getState() != "configured":
        sleep(0.01)

    daq.control.setRecord(False)

    # Resume running (non-recording)
    daq.control.setState("running")
    while daq.control.getState() != "running":
        sleep(0.01)