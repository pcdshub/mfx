"""
Collection of Bluesky plans involving the DAQ but not requiring motors or other
devices.

Functions
---------
quote()
    Grab a random quote from Daniel's collection...
daq_multicount(detectors: List, sample: str, run_length: int, record: bool,
               inspire: bool, delay: int)
    Plan for collecting multiple DAQ runs with logging to the eLog in between.
"""

import logging
import time
from typing import Iterable, List, Any

import bluesky.plan_stubs as bps
import bluesky.plans as bp
from bluesky import RunEngine
from bluesky.callbacks import BestEffortCallback
from pcdsdaq.daq import Daq
from nabs.plans import daq_count
from nabs.preprocessors import daq_step_scan_decorator
from mfx.db import pp, elog

logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)

def quote():
    import json
    import random
    from os import path
    _path = path.dirname(__file__)
    _path = path.join(_path,"/cds/home/d/djr/scripts/quotes.json")
    _quotes = json.loads(open(_path, 'rb').read())
    _quote = _quotes[random.randint(0,len(_quotes)-1)]
    _res = {'quote':_quote['text'],"author":_quote['from']}
    return _res

def daq_multicount(
        detectors: List[Any],
        *,
        sample: str = "?",
        run_length: int = 300,
        record: bool = True,
        runs: int = 5,
        inspire: bool = False,
        delay: int = 5
) -> None:
    """
    Bluesky plan to collect multiple DAQ runs with information posted to the
    eLog in between. Each DAQ run corresponds to a single Bluesky run.

    Parameters
    ----------
    detectors : List[Any]
        List of detectors for the Bluesky plan. The DAQ *MUST* be the first
        detector.
    sample : str
        Sample name to include in the eLog posts.
    run_length : int, optional
        Length of the DAQ run in seconds. Default: 300 s.
    record : bool, optional
        Whether to record the DAQ run data. Default: True.
    runs : int, optional
        Number of DAQ runs
    inspire : bool, optional
        Whether to add "inspirational" quotes to the posts. Default: False.
    delay : int, optional
        Time (in seconds) to wait between successive runs. Default: 5 s.
    """
    daq: Daq = detectors[0]
    def inner():
        for run in range(runs):
            logger.info(f"Beginning DAQ run {daq.run_number() + 1}")
            msg: str = (
                f"Beginning run {run + 1} of {runs} - Running sample {sample}"
            )
            if inspire:
                msg += f"......{quote()['quote']}"
            elog.post(msg, run=detectors[0].run_number())
            logger.info(
                f"Beginning run {run + 1} of {runs} - Running sample {sample}"
            )
            yield from daq_count(
                detectors=detectors,
                num=runs,
                delay=0,
                duration=run_length,
                record=record
            )
            logger.debug(f"Ending run {run + 1} of {runs} - DAQ run {daq.run_number()}")
            yield from bps.sleep(delay)

    pp.close()
    daq.disconnect()
    return (yield from inner())
