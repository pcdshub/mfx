import logging
import time
from typing import Iterable

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

def elog_post_trigger_and_read(
        detectors: Iterable,
        msg: str="DAQ Acquiring Sample"
):
    elog.post(msg)
    return (yield from bps.trigger_and_read(detectors))

def autorun(
        sample: str = "?",
        run_length: int = 300,
        record: bool = True,
        runs: int = 5,
        inspire: bool = False,
        delay: int = 5
) -> None:
    logging.basicConfig(level=logging.INFO)
    logger: logging.Logger = logging.getLogger(__name__)

    RE: RunEngine = RunEngine({})
    bec: BestEffortCallback = BestEffortCallback()
    RE.subscribe(bec)

    daq: Daq = Daq(RE=RE, hutch_name="mfx")
    daq.connect()
    old_config, new_config = daq.configure(
        duration=run_length,
        record=record,
        wait=True,
        end_run=True
    )
    logger.debug(f"Old configuration:\n{old_config}")
    daq.config_info(config=new_config)
    logger.info(f"Attempting DAQ {runs} runs for sample {sample}")

    RE(daq_count(
        detectors=[daq],
        num=runs,
        delay=delay,
        duration=run_length,
        record=record
    ))

    pp.close()
    daq.disconnect()
