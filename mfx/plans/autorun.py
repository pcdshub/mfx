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

def autorun(
        sample: str = "?",
        run_length: int = 300,
        record: bool = True,
        runs: int = 5,
        inspire: bool = False,
        delay: int = 5
) -> None:
    import logging
    from time import sleep

    from bluesky import RunEngine
    from bluesky.callbacks import BestEffortCallback
    from pcdsdaq.daq import Daq
    from mfx.db import pp, elog

    logging.basicConfig(level=logging.INFO)
    logger: logging.Logger = logging.getLogger(__name__)

    RE: RunEngine = RunEngine({})
    # Follow subscription model - this does nothing for the DAQ
    # since there is no data/Msg/etc. through the instance...
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

    for i in range(runs):
        try:
            logger.debug(f"Autorun run {i+1} of {runs}")
            logger.info(f"Beginning Run {daq.run_number() + 1}\n"
                        f"---------------------------\n"
                        f"Running sample {sample}")
            daq.begin()
            if record:
                msg: str = f"Running sample {sample}"
                if inspire:
                    msg += f"......{quote()['quote']}"

                elog.post(msg, run=(daq.run_number()))

            sleep(delay)
        except KeyboardInterrupt as e:
            logger.info(f"Run {daq.run_number()} stopped. Closing PP.")
            break

    pp.close()
    daq.disconnect()
