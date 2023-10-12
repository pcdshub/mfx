import logging

from pcdsdaq.daq import Daq
from bluesky import RunEngine

logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)

def autorun(
        daq: Daq,
        RE: RunEngine,
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
    daq : Daq
        The PCDS Daq interface object. It should be available upon launching
        hutch Python.
    RE : RunEngine
        The RunEngine available in hutch Python.
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
    from mfx.plans import daq_multicount
    logger.info(f"Attempting {runs} DAQ runs of sample {sample}.")
    logger.debug(f"Adjusting DAQ configuration.")
    old_config, new_config = daq.configure(duration=run_length, record=record)
    RE(daq_multicount(
        [daq],
        sample=sample,
        run_length=run_length,
        record=record,
        runs=runs,
        inspire=inspire,
        delay=delay
    ))


#def autorun(sample='?', run_length=300, record=True, runs=5, inspire=False, delay=5):
#    """
#    Automate runs.... With optional quotes
#
#    Parameters
#    ----------
#    sample: str, optional
#        Sample Name
#
#    run_length: int, optional
#        number of seconds for run 300 is default
#
#    record: bool, optional
#        set True to record
#
#    runs: int, optional
#        number of runs 5 is default
#
#    inspire: bool, optional
#        Set false by default because it makes Sandra sad. Set True to inspire
#
#    delay: int, optional
#        delay time between runs. Default is 5 second but increase is the DAQ is being slow.
#
#    Operations
#    ----------
#
#    """
#    from time import sleep
#    from mfx.db import daq, elog, pp
#    import sys
#
#    if sample.lower()=='water' or sample.lower()=='h2o':
#        inspire=True
#    try:
#        for i in range(runs):
#            print(f"Run Number {daq.run_number() + 1} Running {sample}......{quote()['quote']}")
#            daq.begin(duration = run_length, record = record, wait = True, end_run = True)
#            if record:
#                if inspire:
#                    elog.post(f"Running {sample}......{quote()['quote']}", run=(daq.run_number()))
#                else:
#                    elog.post(f"Running {sample}", run=(daq.run_number()))
#            sleep(delay)
#        pp.close()
#        daq.end_run()
#       daq.disconnect()
#
#    except KeyboardInterrupt:
#        print(f"[*] Stopping Run {daq.run_number()} and exiting...",'\n')
#        pp.close()
#        daq.end_run()
#        daq.disconnect()
#        sys.exit()
