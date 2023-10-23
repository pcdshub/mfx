"""
Wrapper functions for collecting DAQ runs with Bluesky.

Functions
---------
autorun(*, sample, run_length, record, runs, inspire, delay)
"""
import logging

from pcdsdaq.daq import Daq
from bluesky import RunEngine

logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)

def autorun(
        *,
        sample: str = "?",
        run_length: int = 300,
        record: bool = True,
        runs: int = 5,
        inspire: bool = False,
        delay: int = 5
) -> None:
    """
    Run the Bluesky RunEngine to collect multiple DAQ runs and log progress to
    the eLog.

    Parameters
    ----------
    sample : str
        Sample name to include in the eLog posts.
    run_length : int, optional
        Length of the DAQ run in seconds. Default: 300 s.
    record : bool, optional
        Whether to record the DAQ run data and post to eLog. Default: True.
    runs : int, optional
        Number of DAQ runs
    inspire : bool, optional
        Whether to add "inspirational" quotes to the posts. Default: False.
    delay : int, optional
        Time (in seconds) to wait between successive runs. Default: 5 s.
    """
    from mfx.plans import daq_multicount
    from mfx.db import daq, RE

    daq.connect()
    logger.info(f"Attempting {runs} DAQ runs of sample {sample}.")
    logger.debug(f"Adjusting DAQ configuration.")
    old_config, new_config = daq.configure(duration=run_length, record=record)
    logger.debug(f"{daq.config_info(config=new_config)}")
    RE(daq_multicount(
        [daq],
        sample=sample,
        run_length=run_length,
        record=record,
        runs=runs,
        inspire=inspire,
        delay=delay
    ))
    #pp.close()
    daq.disconnect()
