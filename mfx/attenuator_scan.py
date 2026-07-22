"""
Attenuator transmission scan utilities for MFX beamline.

Provides automated scanning through different attenuator transmission
values while recording detector data, useful for linearity studies,
saturation testing, and intensity optimization.
"""

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
    Execute automated attenuator transmission scan.

    Scans through a list of attenuator transmission values, recording
    detector data at each transmission level. Useful for detector
    linearity characterization, saturation studies, and intensity
    optimization.

    Parameters
    ----------
    sample : str
        Sample name for run identification and elog posting
    transmissions : list of float, optional
        List of transmission values (0.0-1.0) to scan through.
        Default: [1.0, 0.5, 0.1, 0.05, 0.01]
        Example: [1.0, 0.5, 0.1] = 100%, 50%, 10% transmission
    duration : float, optional
        Time to spend at each transmission value in seconds.
        Default is 10 seconds.
    tag : str, optional
        Run tag for elog organization. If None, uses sample name.
        Default is None.
    inspire : bool, optional
        Include inspirational quotes in elog posts. Automatically
        set to True if sample is 'water' or 'h2o'. Default is False.
    record : bool, optional
        Enable data recording. If False, runs DAQ without saving
        (useful for testing). Default is True.
    runs : int, optional
        Number of complete transmission scans to execute.
        Default is 1.
    daq_delay : int, optional
        Delay in seconds between consecutive runs. Allows time for
        sample delivery or setup changes. Default is 5 seconds.
    picker : str, optional
        Pulse picker mode: 'open' (full rate), 'flip' (alternating),
        or None (no change). Default is 'open'.
    use_daq : bool, optional
        Use DAQ for data acquisition. If False, only sets attenuator
        and waits (manual timing). Default is True.
    daq_num : int, optional
        DAQ station number: 1 (LCLS-I) or 2 (LCLS-II).
        Default is 2.

    Returns
    -------
    None

    Raises
    ------
    ValueError
        If daq_num is not 1 or 2
        If transmissions contains values outside [0.0, 1.0]

    Notes
    -----
    Attenuator System:
    - Si wafer blades in beam path
    - Continuous transmission control 0-100%
    - Automatic thickness calculation
    - Energy-dependent attenuation

    Scan Workflow:
    1. Configure pulse picker if requested
    2. Get starting run number
    3. For each run:
       a. Setup DAQ if recording
       b. For each transmission:
          - Set attenuator
          - Wait for settling
          - Acquire data for specified duration
       c. Post results to elog
       d. Wait daq_delay before next run
    4. Close pulse picker
    5. Report completion

    Special Behavior:
    - Auto-inspire for water samples
    - DAQ configuration varies by version
    - Attenuator motion takes ~1 second
    - Each transmission is separate acquisition

    Use Cases:
    - Detector linearity testing
    - Saturation threshold determination
    - Dynamic range characterization
    - Intensity optimization
    - Damage threshold studies

    Warnings
    --------
    - High transmission may saturate detectors
    - Very low transmission reduces statistics
    - Verify detector safe operating range
    - Long scans may have beam drift

    Examples
    --------
    Basic transmission scan with defaults:
    >>> attenuator_scan(sample='lysozyme', record=True)
    # Scans [1.0, 0.5, 0.1, 0.05, 0.01] at 10s each

    Custom transmission values:
    >>> attenuator_scan(
    ...     sample='myprotein',
    ...     transmissions=[1.0, 0.75, 0.5, 0.25, 0.1],
    ...     duration=15,
    ...     record=True
    ... )

    Quick test without recording:
    >>> attenuator_scan(
    ...     sample='test',
    ...     transmissions=[1.0, 0.5, 0.1],
    ...     duration=5,
    ...     record=False
    ... )

    Multiple runs for statistics:
    >>> attenuator_scan(
    ...     sample='water',
    ...     transmissions=[1.0, 0.5, 0.1],
    ...     duration=20,
    ...     runs=5,
    ...     record=True
    ... )

    Manual timing without DAQ:
    >>> attenuator_scan(
    ...     sample='test',
    ...     transmissions=[1.0, 0.5],
    ...     use_daq=False,
    ...     duration=10
    ... )

    See Also
    --------
    autorun : Standard data acquisition
    delay_scan : Time-delay scanning
    """
    from mfx.db import att, mfx_pulsepicker, daq
    from mfx.autorun import quote, post
    from mfx.macros import get_run

    # Default transmission values if not specified
    if transmissions is None:
        transmissions = [1.0, 0.5, 0.1, 0.05, 0.01]
        logger.info(
            f"Using default transmissions: {transmissions}"
        )

    # Validate transmission values
    for trans in transmissions:
        if not 0.0 <= trans <= 1.0:
            logger.error(
                f"Transmission {trans} outside valid range [0.0, 1.0]"
            )
            raise ValueError("Invalid transmission value")

    # Auto-inspire for water samples
    if sample.lower() in ['water', 'h2o']:
        inspire = True
        logger.info("Water sample detected - inspiring mode enabled")

    # Default tag to sample name
    if tag is None:
        tag = sample

    # Validate DAQ number
    if daq_num not in [1, 2]:
        logger.error('daq_num must be 1 (LCLS-I) or 2 (LCLS-II)')
        raise ValueError('Invalid daq_num')

    # Log scan configuration
    logger.info("\n" + "="*60)
    logger.info("ATTENUATOR SCAN CONFIGURATION")
    logger.info("="*60)
    logger.info(f"Sample: {sample}")
    logger.info(f"Transmissions: {transmissions}")
    logger.info(f"Duration per point: {duration}s")
    logger.info(f"Number of runs: {runs}")
    logger.info(f"Recording: {record}")
    logger.info(f"DAQ: {daq_num}, Use DAQ: {use_daq}")
    logger.info("="*60 + "\n")

    # Operate pulse picker
    if picker == 'open':
        logger.info("Opening pulse picker")
        mfx_pulsepicker.open()
    elif picker == 'flip':
        logger.info("Setting pulse picker to flip-flop mode")
        mfx_pulsepicker.flipflop()

    # Main scan loop
    for run_idx in range(runs):
        logger.info(f"\n{'='*60}")
        logger.info(f"RUN {run_idx + 1}/{runs}")
        logger.info(f"{'='*60}")

        # Determine station based on DAQ version
        station = 1 if daq_num == 1 else 0
        run_number = get_run(station=station) + 1

        logger.info(
            f"Run Number {run_number} Running {sample}..."
            f"...{quote()['quote']}"
        )

        # Setup DAQ if using it
        if use_daq:
            if daq_num == 2:
                # LCLS-II DAQ setup
                logger.info("Configuring LCLS-II DAQ...")
                if not _setup_daq_lcls2(record):
                    logger.error('Failed to setup LCLS-II DAQ')
                    break
            elif daq_num == 1:
                # LCLS-I DAQ setup
                logger.info("Configuring LCLS-I DAQ...")
                daq.configure(record=record)
                sleep(3)

        # Scan through transmissions
        logger.info(
            f"\nScanning through {len(transmissions)} "
            f"transmission values..."
        )
        for idx, transmission in enumerate(transmissions):
            logger.info(
                f"  Step {idx + 1}/{len(transmissions)}: "
                f"Setting transmission to {transmission*100:.1f}%"
            )

            # Set attenuator and wait for motion
            att(transmission, wait=True)
            logger.info(f"    Attenuator reached {transmission}")

            # Acquire data
            if use_daq and daq_num == 1:
                sleep(3)
                logger.info(
                    f"    Recording for {duration}s with DAQ1..."
                )
                daq.begin(
                    duration=duration,
                    record=record,
                    wait=True,
                    use_l3t=False
                )
            else:
                logger.info(
                    f"    Waiting {duration}s at this transmission..."
                )
                sleep(duration)

        # Cleanup DAQ
        if use_daq:
            if daq_num == 2:
                logger.info("Cleaning up LCLS-II DAQ...")
                _cleanup_daq_lcls2()
            elif daq_num == 1:
                logger.info("Ending DAQ1 run...")
                daq.end_run()
                daq.disconnect()

        # Post to elog
        if record:
            sample_transmissions = (
                f"{sample}\nTransmissions: {transmissions}"
            )
            logger.info("Posting run to elog...")
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
        mfx_pulsepicker.close()

        # Wait before next run
        if run_idx < runs - 1:
            logger.info(
                f"\nWaiting {daq_delay}s before next run..."
            )
            sleep(daq_delay)

    # Final summary
    logger.info("\n" + "="*60)
    logger.info("ATTENUATOR SCAN COMPLETE")
    logger.info("="*60)
    logger.info(f"Total runs completed: {runs}")
    logger.info(
        f"Transmissions scanned: {transmissions}"
    )
    logger.info("="*60 + "\n")


def _setup_daq_lcls2(record):
    """
    Setup LCLS-II DAQ for acquisition.

    Reconnects to DAQ, configures recording state, and transitions
    to running state for data acquisition.

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
    Setup Sequence:
    1. Reconnect to DAQ with fresh DaqControl instance
    2. Verify connection to instrument
    3. Check DAQ state (error check)
    4. Transition to 'configured' state
    5. Set recording flag
    6. Transition to 'running' state

    Connection:
    - Host and platform from existing daq.control
    - Timeout: 10000 ms (10 seconds)
    - Uses psdaq.control.DaqControl

    State Machine:
    - Initial: varies (should not be 'error')
    - Configured: DAQ ready, not recording
    - Running: DAQ actively acquiring

    Warnings
    --------
    Returns False if:
    - Cannot connect to DAQ
    - DAQ in error state
    - State transitions fail

    Examples
    --------
    Setup for recording:
    >>> success = _setup_daq_lcls2(record=True)
    >>> if success:
    ...     print("DAQ ready")

    Setup for test mode:
    >>> success = _setup_daq_lcls2(record=False)

    See Also
    --------
    _cleanup_daq_lcls2 : Cleanup after acquisition
    """
    from mfx.db import daq
    from psdaq.control.DaqControl import DaqControl

    logger.debug("Setting up LCLS-II DAQ...")

    # Reconnect to DAQ
    daq.control = DaqControl(
        host=daq.control.host,
        platform=daq.control.platform,
        timeout=10000
    )
    logger.debug(f"Connected to DAQ at {daq.control.host}")

    # Check connection
    instr = daq.control.getInstrument()
    if instr is None:
        logger.error('Failed to connect to LCLS-II DAQ')
        return False
    logger.debug(f"DAQ instrument: {instr}")

    # Check state
    start_state = daq.control.getState()
    logger.debug(f"DAQ initial state: {start_state}")
    if start_state == 'error':
        logger.error('DAQ is in error state')
        return False

    # Configure
    logger.debug("Transitioning DAQ to 'configured' state...")
    daq.control.setState("configured")
    while daq.control.getState() != "configured":
        sleep(0.01)
    logger.debug("DAQ configured")

    # Set recording
    logger.debug(f"Setting DAQ record flag: {record}")
    daq.control.setRecord(record)

    # Start running
    logger.debug("Transitioning DAQ to 'running' state...")
    daq.control.setState("running")
    while daq.control.getState() != "running":
        sleep(0.01)
    logger.debug("DAQ running")

    return True


def _cleanup_daq_lcls2():
    """
    Cleanup LCLS-II DAQ after acquisition.

    Stops recording and returns DAQ to configured state, ready for
    next acquisition or shutdown.

    Returns
    -------
    None

    Notes
    -----
    Cleanup Sequence:
    1. Reconnect to DAQ (fresh connection)
    2. Transition to 'configured' state (stops acquisition)
    3. Disable recording
    4. Transition to 'running' state (non-recording)

    The final 'running' state allows DAQ to continue monitoring
    without recording data, useful for diagnostics between runs.

    State Transitions:
    - Running (recording) → Configured
    - Set record=False
    - Configured → Running (non-recording)

    Examples
    --------
    Cleanup after scan:
    >>> _cleanup_daq_lcls2()
    # DAQ now in running/non-recording state

    See Also
    --------
    _setup_daq_lcls2 : Setup DAQ for acquisition
    """
    from mfx.db import daq
    from psdaq.control.DaqControl import DaqControl

    logger.debug("Cleaning up LCLS-II DAQ...")

    # Reconnect to DAQ
    daq.control = DaqControl(
        host=daq.control.host,
        platform=daq.control.platform,
        timeout=10000
    )

    # Stop recording
    logger.debug("Transitioning DAQ to 'configured' state...")
    daq.control.setState("configured")
    while daq.control.getState() != "configured":
        sleep(0.01)

    logger.debug("Disabling recording...")
    daq.control. setRecord(False)

    # Resume running (non-recording)
    logger.debug("Transitioning DAQ to 'running' (non-recording)...")
    daq.control.setState("running")
    while daq.control.getState() != "running":
        sleep(0.01)

    logger.debug("DAQ cleanup complete")


def quick_att_scan(sample, record=True):
    """
    Quick attenuator scan with default parameters.

    Convenience function for standard 5-point transmission scan
    with minimal setup.

    Parameters
    ----------
    sample : str
        Sample name
    record : bool, optional
        Enable recording. Default is True.

    Returns
    -------
    None

    Notes
    -----
    Default Configuration:
    - Transmissions: [1.0, 0.5, 0.1, 0.05, 0.01]
    - Duration: 10 seconds per point
    - Single run
    - DAQ2
    - Pulse picker open

    Examples
    --------
    Quick scan with recording:
    >>> quick_att_scan('lysozyme')

    Test scan without recording:
    >>> quick_att_scan('test', record=False)

    See Also
    --------
    attenuator_scan : Full parameter control
    """
    logger.info(f"Quick attenuator scan: {sample}")
    attenuator_scan(
        sample=sample,
        transmissions=[1.0, 0.5, 0.1, 0.05, 0.01],
        duration=10,
        record=record,
        runs=1,
        daq_num=2,
        picker='open'
    )