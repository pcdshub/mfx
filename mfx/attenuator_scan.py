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
        record: bool = True
) -> None:
    """
    Scan the attenuator through multiple steps recording a DAQ run at each
    transmission level. The number of events collected at each step is adjusted
    so the final statistics are similar at all transmission levels.

    Parameters
    ----------
    max_events : int
        Number of events to record for the highest transmission level. Steps at
        lower transmission levels will have proportionally more events.
    transmissions: List[float]
        List of transmission levels to step through
    record : bool
        Whether to record the data.
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
        record=record
    ))
    daq.disconnect()


def scan_attenuator_single_run(
        max_events: int = 240,
        transmissions: List[float] =[],
        record: bool = True,
        acq_freq: int = 120
) -> None:
    """
    Scan the attenuator through multiple steps over a single DAQ run.
    The number of events collected at each step is adjusted so the final
    statistics are similar at all transmission levels.

    Parameters
    ----------
    max_events : int
        Number of events to record for the highest transmission level. Steps at
        lower transmission levels will have proportionally more events.
    transmissions: List[float]
        List of transmission levels to step through
    record : bool
        Whether to record the data.
    acq_freq : int
        DAQ acquisition frequency.
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
        acq_freq=acq_freq
    ))
    daq.disconnect()


def attenuator_scan_separate_runs(events=240, record=False, config=True, transmissions=[0.01,0.02,0.03]):
    """
    Runs through attenuator conditions and records each as an individual run

    Parameters
    ----------
    events: int, optional
        number of events. default 240

    record: bool, optional
        set True to record

    transmissions: list of floats, optional
        list of transmissions to run through. default [0.01,0.02,0.03]

    Operations
    ----------

    """
    from time import sleep
    from mfx.db import daq, att, pp

    pp.open()
    for i in transmissions:
        att(i)
        sleep(3)
        daq.begin(events=events,record=record,wait=True, use_l3t=False)
        daq.end_run()
    pp.close()
    daq.disconnect()


def attenuator_scan_single_run(events=240, record=False, transmissions=[0.01,0.02,0.03]):
    """
    Runs through attenuator conditions and records them all as one continuous run

    Parameters
    ----------
    events: int, optional
        number of events. default 240

    record: bool, optional
        set True to record

    transmissions: list of floats, optional
        list of transmissions to run through. default [0.01,0.02,0.03]

    Operations
    ----------

    """
    from time import sleep
    from mfx.db import daq, att, pp

    daq.end_run()
    daq.disconnect()
    try:
        pp.open()
        daq.configure(record=record)
        sleep(3)
        for i in transmissions:
            att(i,wait=True)
            sleep(3)
            daq.begin(events=events,record=record,wait=True, use_l3t=False)
    finally:
        daq.end_run()
        pp.close()
        daq.disconnect()
