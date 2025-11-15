"""Time tool drift correction and monitoring utilities for MFX beamline."""

import logging
import time
from typing import Tuple, Optional

import numpy as np
from ophyd import EpicsSignal

logger = logging.getLogger(__name__)


def write_log(message: str, logfile: str = ""):
    """
    Write message to log file and console.

    Parameters
    ----------
    message : str
        Message to log
    logfile : str, optional
        Path to log file (default: "")
        If empty string, only prints to console

    Returns
    -------
    None

    Notes
    -----
    Logging Behavior:
    - Always prints to console with timestamp
    - Optionally writes to file if specified
    - Appends to existing file
    - Creates file if doesn't exist

    Timestamp Format:
    - ISO 8601 format
    - Includes date and time
    - Precision to seconds

    Use Cases:
    - Drift correction logging
    - Timing adjustment tracking
    - Diagnostic information

    Examples
    --------
    Console only:
    >>> write_log("Starting drift correction")

    Console and file:
    >>> write_log("Adjustment made", logfile="/tmp/timing.log")

    See Also
    --------
    correct_timing_drift : Uses this for logging
    """
    from datetime import datetime

    # Create timestamped message
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_message = f"[{timestamp}] {message}"

    # Print to console
    logger.info(message)

    # Write to file if specified
    if logfile:
        try:
            with open(logfile, 'a') as f:
                f.write(full_message + '\n')
        except IOError as e:
            logger.warning(f"Failed to write to log file: {e}")


def is_good_measurement(
        tt_data: np.ndarray,
        amplitude_thresh: float,
        ipm_thresh: float,
        fwhm_threshs: Tuple[float, float]) -> bool:
    """
    Determine if time tool measurement is valid for drift correction.

    Applies quality criteria to time tool data to filter out
    bad measurements before including in rolling average.

    Parameters
    ----------
    tt_data : np.ndarray
        Time tool EVENTBUILD data array (10 fields)
        Indices:
        - 0: IPM DG1 sum
        - 1: IPM DG2 sum
        - 2: TT amplitude
        - 3: TT edge position (ps)
        - 4: TT FWHM
        - 5-9: Additional TT fields
    amplitude_thresh : float
        Minimum TT amplitude to accept
        Typical: 0.01-0.05
    ipm_thresh : float
        Minimum IPM DG2 value to accept
        Typical: 100-1000
    fwhm_threshs : Tuple[float, float]
        (min, max) FWHM bounds
        Typical: (30, 130) for good fit quality

    Returns
    -------
    bool
        True if measurement passes all criteria
        False if any criterion fails

    Notes
    -----
    Quality Criteria:

    1. Amplitude Check:
       - TT fitted peak amplitude
       - Low amplitude = poor signal
       - Threshold depends on typical signal

    2. IPM Check:
       - DG2 intensity monitor
       - Low IPM = weak/no X-rays
       - Prevents drift correction without beam

    3. FWHM Check:
       - Width of TT fitted peak
       - Too narrow: noise spike
       - Too wide: poor fit or multiple peaks
       - Range indicates good Gaussian fit

    EVENTBUILD PV Structure:
    - Field 0: IPM DG1 sum
    - Field 1: IPM DG2 sum
    - Field 2: TT amplitude
    - Field 3: TT edge position (ps)
    - Field 4: TT FWHM
    - Fields 5-9: Reserved/additional

    Common Rejection Reasons:
    - Beam down (low IPM)
    - Noise spike (low amplitude)
    - Poor fit (FWHM out of range)
    - Missing data (NaN values)

    Threshold Tuning:
    - Monitor rejection rate
    - Adjust for your beam conditions
    - Balance filtering vs. statistics

    Examples
    --------
    >>> tt_data = timetool_signal.get()
    >>> is_valid = is_good_measurement(
    ...     tt_data,
    ...     amplitude_thresh=0.02,
    ...     ipm_thresh=500,
    ...     fwhm_threshs=(30, 130)
    ... )
    >>> if is_valid:
    ...     print("Good measurement")

    See Also
    --------
    correct_timing_drift : Uses this for filtering
    """
    # Extract relevant fields
    ipm_dg2 = tt_data[1]           # IPM DG2 sum
    timetool_amp = tt_data[2]      # TT amplitude
    fwhm = tt_data[4]              # TT FWHM

    # Check amplitude threshold
    if timetool_amp < amplitude_thresh:
        return False

    # Check IPM threshold (beam present)
    if ipm_dg2 < ipm_thresh:
        return False

    # Check FWHM range (good fit quality)
    if fwhm < fwhm_threshs[0] or fwhm > fwhm_threshs[1]:
        return False

    # All checks passed
    return True


def correct_timing_drift(
        amplitude_thresh: float = 0.02,
        ipm_thresh: float = 500.0,
        drift_adjustment_thresh: float = 0.05,
        fwhm_threshs: Tuple[float, float] = (30, 130),
        num_events: int = 61,
        will_log: bool = True) -> None:
    """
    Automate correction of laser timing drift.

    Monitors time tool edge position and automatically adjusts
    laser timing stages to compensate for drift. Maintains optimal
    pump-probe overlap during experiments.

    Parameters
    ----------
    amplitude_thresh : float, optional
        Minimum TT amplitude for valid measurement (default: 0.02)
        Lower values accept weaker signals but more noise
    ipm_thresh : float, optional
        Minimum IPM DG2 value to correct (default: 500.0)
        Prevents correction when beam is weak or down
    drift_adjustment_thresh : float, optional
        Minimum drift to trigger correction in ps (default: 0.05)
        Smaller values = more frequent corrections
    fwhm_threshs : Tuple[float, float], optional
        (min, max) FWHM for valid measurement (default: (30, 130))
        Range indicating good Gaussian fit quality
    num_events : int, optional
        Number of events in rolling average (default: 61)
        Prime number reduces systematic effects
        Larger = more stable but slower response
    will_log : bool, optional
        Enable logging to file (default: True)
        Prompts for log filename if True

    Returns
    -------
    None
        Runs continuously until KeyboardInterrupt

    Raises
    ------
    KeyboardInterrupt
        User stops correction loop with Ctrl+C

    Notes
    -----
    Drift Correction Algorithm:

    1. Initialize:
       - Create rolling average buffer
       - Optionally open log file
       - Record start time

    2. Acquire Good Measurements:
       - Read TT edge position
       - Apply quality filters
       - Accumulate until buffer full
       - Track time since last good measurement

    3. Calculate Average:
       - Mean of rolling buffer
       - Represents current drift

    4. Apply Correction:
       - If |drift| > threshold:
         - Move lxt (timing compensation)
         - Update txt (offset reference)
         - Log adjustment

    5. Repeat:
       - Clear buffer
       - Continue monitoring

    Time Tool (TT):
    - Measures relative arrival time
    - X-ray pulse vs. laser pulse
    - Edge detection algorithm
    - Sub-ps resolution

    Laser Timing System:
    - lxt: Main timing compensation stage
    - txt: Timing offset reference
    - Compensates for environmental drift
    - Temperature, vibration, etc.

    Rolling Average:
    - Reduces shot-to-shot noise
    - Prime number (61) reduces aliasing
    - Typical: 30-100 events
    - Balance between stability and response

    Drift Sources:
    - Temperature changes
    - Mechanical vibration
    - Air currents
    - Long-term laser drift
    - Typical: 10-100 fs over hours

    Correction Strategy:
    - Negative feedback loop
    - Proportional control
    - Threshold prevents over-correction
    - Maintains set point near zero

    Stage Movement:
    - lxt.mvr(): Relative move
    - Adds correction to current position
    - txt updated to maintain offset
    - Keeps lxt position trackable

    Safety Features:
    - Timeout on no good measurements
    - Logs all corrections
    - Keyboard interrupt stops cleanly
    - IPM threshold prevents blind correction

    Typical Performance:
    - Maintains timing ±50 fs
    - Correction every 1-10 minutes
    - Depends on environmental stability

    When to Use:
    - Long experiments (>1 hour)
    - Critical timing requirements
    - Unstable environments
    - After initial alignment

    When NOT to Use:
    - During timing scans
    - When TT signal poor
    - During alignment
    - Short experiments (<30 min)

    Monitoring:
    - Watch log messages
    - Check correction frequency
    - Verify TT signal quality
    - Monitor rejection rate

    Examples
    --------
    Standard drift correction:
    >>> correct_timing_drift()
    Please enter a file to log correction info to: /tmp/drift.log
    [Starts monitoring and correction loop]

    Sensitive correction:
    >>> correct_timing_drift(
    ...     drift_adjustment_thresh=0.02,  # Correct smaller drifts
    ...     num_events=101  # More averaging
    ... )

    Relaxed correction:
    >>> correct_timing_drift(
    ...     drift_adjustment_thresh=0.1,  # Only large drifts
    ...     num_events=31  # Faster response
    ... )

    No logging:
    >>> correct_timing_drift(will_log=False)

    Custom thresholds:
    >>> correct_timing_drift(
    ...     amplitude_thresh=0.05,  # Stricter amplitude
    ...     ipm_thresh=1000,  # Higher beam requirement
    ...     fwhm_threshs=(40, 120)  # Tighter FWHM range
    ... )

    See Also
    --------
    is_good_measurement : Quality filtering function
    write_log : Logging function
    """
    from mfx.db import lxt, txt

    # Setup logging
    logfile: str = ""
    if will_log:
        logfile = input("Please enter a file to log correction info to: ")
        write_log("Starting time tool drift correction", logfile)
        write_log(
            f"Parameters: amplitude_thresh={amplitude_thresh}, "
            f"ipm_thresh={ipm_thresh}, drift_thresh={drift_adjustment_thresh}, "
            f"fwhm_range={fwhm_threshs}, num_events={num_events}",
            logfile
        )

    # Initialize rolling average buffer
    timetool_edges: np.ndarray = np.zeros(num_events)

    # Create TT signal object
    timetool = EpicsSignal("MFX:TT:01:EVENTBUILD.VALA", name="timetool")

    write_log("Entering drift correction loop", logfile)
    logger.info(
        "Press Ctrl+C to stop drift correction\n"
        f"Accumulating {num_events} measurements per correction cycle"
    )

    try:
        while True:
            # Acquire good measurements
            num_curr_edges: int = 0
            time_last_good_val: float = time.time()

            while num_curr_edges < num_events:
                try:
                    # Read TT data
                    # EVENTBUILD.VALA contains 10 fields:
                    # [0]: IPM DG1, [1]: IPM DG2
                    # [2]: TT amplitude, [3]: TT edge (ps)
                    # [4]: TT FWHM, [5-9]: Additional fields
                    tt_data: np.ndarray = timetool.get()

                    # Extract edge position
                    timetool_edge_ps: float = tt_data[3]

                    # Check if measurement is good
                    if is_good_measurement(
                        tt_data, amplitude_thresh, ipm_thresh, fwhm_threshs
                    ):
                        # Add to rolling buffer
                        timetool_edges[num_curr_edges] = timetool_edge_ps
                        num_curr_edges += 1
                        time_last_good_val = time.time()

                        # Progress indicator
                        if num_curr_edges % 10 == 0:
                            logger.debug(
                                f"Collected {num_curr_edges}/{num_events} "
                                "good measurements"
                            )

                    # Check for timeout (no good measurements)
                    elif time.time() - time_last_good_val > 60:
                        write_log(
                            "No good measurement in 60s. Check thresholds and beam.",
                            logfile
                        )
                        logger.warning(
                            "No good TT measurements. Possible issues:\n"
                            f"  - Beam down (IPM < {ipm_thresh})\n"
                            f"  - TT signal weak (amp < {amplitude_thresh})\n"
                            f"  - Poor fit (FWHM not in {fwhm_threshs})"
                        )
                        time_last_good_val = time.time()

                    # Small delay to avoid overwhelming EPICS
                    time.sleep(0.01)

                except KeyboardInterrupt:
                    raise  # Re-raise to outer handler

                except Exception as e:
                    logger.error(f"Error reading TT data: {e}")
                    time.sleep(0.1)

            # Calculate average drift
            tt_edge_average_ps: float = np.mean(timetool_edges)
            write_log(
                f"Average drift: {tt_edge_average_ps:.3f} ps "
                f"from {num_events} measurements",
                logfile
            )

            # Apply correction if drift exceeds threshold
            if np.abs(tt_edge_average_ps) > drift_adjustment_thresh:
                # Convert ps to seconds (negative for correction)
                tt_average_seconds: float = -(tt_edge_average_ps * 1e-12)

                write_log(
                    f"Applying correction: {tt_average_seconds*1e12:.3f} ps",
                    logfile
                )
                logger.info(
                    f"Drift detected: {tt_edge_average_ps:+.3f} ps\n"
                    f"Correcting by {-tt_average_seconds*1e12:.3f} ps"
                )

                # Move laser timing stage (relative move)
                lxt.mvr(tt_average_seconds)

                # Update timing offset to maintain reference
                # This keeps lxt position meaningful
                lxt .set_current_position(-float(txt.position))

                write_log(
                    f"Correction applied. New lxt position: "
                    f"{lxt.position*1e12:.3f} ps",
                    logfile
                )
            else:
                logger.info(
                    f"Drift within threshold: {tt_edge_average_ps:+.3f} ps "
                    f"(threshold: ±{drift_adjustment_thresh} ps)"
                )

    except KeyboardInterrupt:
        write_log("Exiting drift correction loop (user interrupt)", logfile)
        logger.info("\nDrift correction stopped by user")
        logger.info("Timing stages remain at current positions")

    except Exception as e:
        write_log(f"Error in drift correction: {e}", logfile)
        logger.error(f"Drift correction error: {e}")
        raise


def monitor_timing(
        duration: float = 60.0,
        logfile: str = "") -> Tuple[np.ndarray, np.ndarray]:
    """
    Monitor time tool measurements without correction.

    Records time tool edge positions for specified duration
    to assess drift rate and timing stability.

    Parameters
    ----------
    duration : float, optional
        Monitoring duration in seconds (default: 60.0)
    logfile : str, optional
        Log file path (default: "")
        If empty, no logging

    Returns
    -------
    times : np.ndarray
        Timestamps (seconds since start)
    edges : np.ndarray
        TT edge positions (ps)

    Notes
    -----
    Use Cases:
    - Assess drift rate before correction
    - Verify timing stability
    - Diagnose timing issues
    - Characterize environmental effects

    No Correction Applied:
    - Only monitors, doesn't adjust
    - All measurements recorded
    - No quality filtering

    Analysis:
    - Calculate drift rate (ps/min)
    - Assess jitter (std deviation)
    - Identify systematic trends

    Examples
    --------
    Monitor for 5 minutes:
    >>> times, edges = monitor_timing(duration=300)
    >>> drift_rate = (edges[-1] - edges[0]) / (times[-1] / 60)
    >>> print(f"Drift rate: {drift_rate:.2f} ps/min")

    Monitor with logging:
    >>> times, edges = monitor_timing(
    ...     duration=600,
    ...     logfile='/tmp/timing_monitor.log'
    ... )

    See Also
    --------
    correct_timing_drift : Automatic correction
    """
    from mfx.db import lxt, txt

    timetool = EpicsSignal("MFX:TT:01:EVENTBUILD.VALA", name="timetool")

    write_log(f"Starting timing monitor for {duration} s", logfile)

    times = []
    edges = []
    start_time = time.time()

    try:
        while time.time() - start_time < duration:
            try:
                # Read TT data
                tt_data = timetool.get()
                edge = tt_data[3]

                # Record measurement
                elapsed = time.time() - start_time
                times.append(elapsed)
                edges.append(edge)

                # Log every 10 seconds
                if len(times) % 100 == 0:
                    write_log(
                        f"t={elapsed:.1f}s: edge={edge:.3f} ps",
                        logfile
                    )

                time.sleep(0.1)

            except Exception as e:
                logger.error(f"Error reading TT: {e}")
                time.sleep(0.5)

    except KeyboardInterrupt:
        logger.info("Monitoring stopped by user")

    times = np.array(times)
    edges = np.array(edges)

    # Calculate statistics
    drift = edges[-1] - edges[0]
    jitter = np.std(edges)

    write_log(
        f"Monitoring complete: {len(edges)} measurements\n"
        f"  Total drift: {drift:.3f} ps\n"
        f"  RMS jitter: {jitter:.3f} ps",
        logfile
    )

    logger.info(
        f"\nMonitoring Results ({duration:.1f} s):\n"
        f"  Measurements: {len(edges)}\n"
        f"  Total drift: {drift:+.3f} ps\n"
        f"  Drift rate: {drift/(duration/60):.3f} ps/min\n"
        f"  RMS jitter: {jitter:.3f} ps\n"
        f"  Mean: {np.mean(edges):.3f} ps\n"
        f"  Range: {np.min(edges):.3f} to {np.max(edges):.3f} ps"
    )

    return times, edges


# Convenience functions

def start_drift_correction(
        sensitivity: str = 'normal',
        logfile: Optional[str] = None) -> None:
    """
    Start drift correction with preset sensitivity levels.

    Parameters
    ----------
    sensitivity : str, optional
        Sensitivity level: 'tight', 'normal', 'relaxed' (default: 'normal')
    logfile : str or None, optional
        Log file path (prompted if None)

    Returns
    -------
    None

    Notes
    -----
    Sensitivity Presets:

    'tight':
    - drift_thresh = 0.02 ps (20 fs)
    - num_events = 101
    - For critical timing experiments

    'normal':
    - drift_thresh = 0.05 ps (50 fs)
    - num_events = 61
    - Standard operation

    'relaxed':
    - drift_thresh = 0.1 ps (100 fs)
    - num_events = 31
    - Less critical timing

    Examples
    --------
    >>> start_drift_correction('normal')
    >>> start_drift_correction('tight', logfile='/tmp/drift.log')

    See Also
    --------
    correct_timing_drift : Full control
    """
    # Preset configurations
    configs = {
        'tight': {
            'drift_adjustment_thresh': 0.02,
            'num_events': 101,
            'amplitude_thresh': 0.03,
        },
        'normal': {
            'drift_adjustment_thresh': 0.05,
            'num_events': 61,
            'amplitude_thresh': 0.02,
        },
        'relaxed': {
            'drift_adjustment_thresh': 0.1,
            'num_events': 31,
            'amplitude_thresh': 0.01,
        }
    }

    if sensitivity not in configs:
        logger.error(
            f"Unknown sensitivity: {sensitivity}. "
            "Use 'tight', 'normal', or 'relaxed'"
        )
        return

    config = configs[sensitivity]

    logger.info(f"Starting drift correction with '{sensitivity}' sensitivity")
    logger.info(f"Configuration: {config}")

    # Determine logging
    will_log = logfile is not None or input(
        "Enable logging? (y/n): "
    ).lower() == 'y'

    correct_timing_drift(
        drift_adjustment_thresh=config['drift_adjustment_thresh'],
        num_events=config['num_events'],
        amplitude_thresh=config['amplitude_thresh'],
        will_log=will_log
    )


def quick_drift_check(duration: float = 60.0) -> dict:
    """
    Quick assessment of timing drift and stability.

    Parameters
    ----------
    duration : float, optional
        Check duration in seconds (default: 60.0)

    Returns
    -------
    dict
        Drift statistics:
        - 'drift_ps': Total drift (ps)
        - 'drift_rate': Drift rate (ps/min)
        - 'jitter_ps': RMS jitter (ps)
        - 'mean_ps': Mean position (ps)
        - 'num_measurements': Sample count

    Examples
    --------
    >>> stats = quick_drift_check(duration=120)
    >>> print(f"Drift: {stats['drift_ps']:.2f} ps")
    >>> print(f"Rate: {stats['drift_rate']:.2f} ps/min")

    See Also
    --------
    monitor_timing : Full monitoring
    """
    logger.info(f"Performing {duration}s drift check...")

    times, edges = monitor_timing(duration=duration)

    stats = {
        'drift_ps': edges[-1] - edges[0],
        'drift_rate': (edges[-1] - edges[0]) / (duration / 60),
        'jitter_ps': np.std(edges),
        'mean_ps': np.mean(edges),
        'num_measurements': len(edges)
    }

    return stats


# Module initialization
logger.info("Time tool drift correction utilities loaded")