"""
Collection of Bluesky plans for collecting attenuator scans with the DAQ.

Functions
---------
attenuator_scan_multi_run()
    Collect multiple DAQ runs, each at a different transmission level, set by
    the attenuator configuration.
attenuator_scan_single_run()
    Collect a single DAQ run while varying the transmission level through the
    attenuator configuration.
"""

__all__ = ["attenuator_scan_multi_run", "attenuator_scan_single_run"]

import logging
from typing import Generator, List, Any

import numpy as np
import bluesky.plan_stubs as bps
from pcdsdaq.preprocessors import daq_during_decorator
from nabs.plans import daq_count

logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)

def determine_num_events(
        current_transmission: float,
        highest_transmission: float,
        evts_highest_transmission: float
) -> int:
    """
    Determine the number of events needed for a given attenuation level so that
    all steps in the attenuator scan are acquired with similar final statistics.

    Parameters
    ----------
    current_transmission : float
        The current transmission level. E.g. 1e-2, 3e-2, ...
    highest_transmission : float
        The highest transmission level in the attenuator scan series.
    evts_highest_transmission : float
        The number of events acquired at the highest transmission level.

    Returns
    -------
    num_evts : int
        Number of events to acquire at the current transmission level.
    """
    return int(
        evts_highest_transmission*(highest_transmission/current_transmission)
    )

def split_run_time_per_step(
        transmissions: List[float],
        run_length: int
) -> np.ndarray:
    """
    Split the total time of a single run into appropriate durations per step of
    an attenuator scan.

    Parameters
    ----------
    transmissions : List[float]
        List of all transmission levels to be acquired during the attenuator
        scan. Assumed to be sorted in descending order.
    run_length : int
        Total duration, in seconds, of the DAQ run during which the attenuator
        scan will occur.

    Returns
    -------
    step_durations : np.ndarray[float]
        Given the total run length, a list of durations to spend at each
        transmission level. There is one-to-one correspondence.
        E.g. spend durations[0] seconds at transmissions[0].
    """
    # `transmissions` assumed to be in descending order
    multipliers: np.ndarray = np.array(transmissions)
    multipliers = multipliers[0]/multipliers
    shortest_time: float = run_length/multipliers.sum()
    step_durations: np.ndarray = multipliers*shortest_time
    return step_durations

def attenuator_scan_multi_run(
        detectors: List[Any],
        attenuator: Any,
        transmissions: List[float],
        max_evts: int
) -> Generator:
    """
    Collect individual runs at different transmission levels by adjusting the
    attenuator settings. The run length is adjusted for each setting to ensure
    similar integrated statistics are collected for each transmission level.

    Parameters
    ----------
    detectors : List[Any]
        List of detector objects.
    attenuator : Any
        Attenuator to scan.
    transmissions : List[float]
        Transmission levels to step the attenuator through
    max_evts : float
        Number of events for the maximum transmission level.
    """
    transmissions = sorted(transmissions, reverse=True)

    def inner():
        for transmission in transmissions:
            n_evts = determine_num_events(transmission, transmissions[0], max_evts)
            logger.info(f"Acquiring {n_evts} events at transmission {transmission}")
            yield from bps.mv(attenuator, transmission)
            yield from daq_count(
                detectors=detectors,
                num=1,
                delay=0,
                events=n_evts,
                record=True
            )
    return (yield from inner())

@daq_during_decorator
def attenuator_scan_one_run(
        detectors: List[Any],
        attenuator: Any,
        transmissions: List[float],
        run_length: int
) -> Generator:
    """
    Collect a single run while adjusting transmission level by changing the
    attenuator settings. The time spent at each setting is changed to ensure
    similar integrated statistics are collected for each transmission level.

    Parameters
    ----------
    detectors : List[Any]
        List of detector objects.
    attenuator : Any
        Attenuator to scan.
    transmissions : List[float]
        Transmission levels to step the attenuator through
    run_length : int
        Total duration of the single DAQ run to collect. The time will be split
        between the various steps so that the integrated statistics per step
        are comparable.
    """
    transmissions = sorted(transmissions, reverse=True)
    step_durations = split_run_time_per_step(
        transmissions,
        run_length=run_length
    )

    def inner():
        for idx, transmission in enumerate(transmissions):
            yield from bps.mv(attenuator, transmission)
            yield from bps.sleep(step_durations[idx])

    return (yield from inner())
