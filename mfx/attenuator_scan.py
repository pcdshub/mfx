"""
Wrapper functions for Bluesky attenuator scans with DAQ support.

Functions
---------
scan_attenuator_multiple_runs(max_events, transmissions)
    Scan the attenuator through multiple steps collecting a DAQ run at each
    transmission level.
scan_attenuator_single_runs(max_events, run_length, record)
    Scan the attenuator through multiple transmission levels over a single DAQ
    run.
"""

import logging
from typing import List, Any

from pcdsdaq.daq import Daq
from bluesky import RunEngine

logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)

def scan_attenuator_multiple_runs(
        max_events: int = 240,
        transmissions: List[float] = [],
        record: bool = True,
        flat: bool = False
) -> None:
    """
    Scan the attenuator through multiple steps recording a DAQ run at each
    transmission level. The number of events collected at each step is adjusted
    so the final statistics are similar at all transmission levels.

    Parameters
    ----------
    max_events : int
        Number of events to record for the highest transmission level. Steps at
        lower transmission levels will have proportionally more events iff.
        `flat = True`, otherwise, all transmission levels will use this number
        of events.
    transmissions: List[float]
        List of transmission levels to step through
    record : bool
        Whether to record the data. Default: True
    flat : bool
        Whether to acquire homogeneous statistics or not. If False all
        transmission levels will have `max_events` acquired.
    """
    from mfx.plans import attenuator_scan_multi_run
    from mfx.db import daq, att, RE

    daq.connect()
    logger.info(
        f"Beginning attenuator scan across multiple DAQ runs.\n"
        f"{len(transmissions)} transmission levels chosen: {transmissions}."
    )
    logger.debug(f"Adjusting DAQ configuration.")
    old_config, new_config = daq.configure(events=max_events, record=record)

    transmissions = sorted(transmissions, reverse=True)
    RE(attenuator_scan_multi_run(
        detectors=[daq],
        attenuator=att,
        transmissions=transmissions,
        max_evts=max_events,
        record=record,
        flat=flat
    ))
    daq.disconnect()


def scan_attenuator_single_run(
        max_events: int = 240,
        transmissions: List[float] =[],
        record: bool = True,
        acq_freq: int = 120,
        flat: bool = True
) -> None:
    """
    Scan the attenuator through multiple steps over a single DAQ run.
    The number of events collected at each step is adjusted so the final
    statistics are similar at all transmission levels.

    Parameters
    ----------
    max_events : int
        Number of events to record for the highest transmission level. Steps at
        lower transmission levels will have proportionally more events iff.
        `flat = True`, otherwise, all transmission levels will use this number
        of events.
    transmissions: List[float]
        List of transmission levels to step through
    record : bool
        Whether to record the data. Default: True
    acq_freq : int
        DAQ acquisition frequency.
    flat : bool
        Whether to acquire homogeneous statistics or not. If False all
        transmission levels will have `max_events` acquired.
    """
    from mfx.plans import attenuator_scan_one_run
    from mfx.db import daq, att, RE

    daq.connect()
    logger.info(
        f"Beginning attenuator scan across single DAQ run.\n"
        f"{len(transmissions)} transmission levels chosen: {transmissions}."
    )
    logger.debug(f"Adjusting DAQ configuration.")
    old_config, new_config = daq.configure(events=max_events, record=record)
    logger.debug(f"{daq.config_info(config=new_config)}")

    transmissions = sorted(transmissions, reverse=True)
    RE(attenuator_scan_one_run(
        detectors=[daq],
        attenuator=att,
        transmissions=transmissions,
        max_evts=max_events,
        record=record,
        acq_freq=acq_freq,
        flat=flat
    ))
    daq.disconnect()
