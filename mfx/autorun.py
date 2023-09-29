
def quote():
    import json,random
    from os import path
    _path = path.dirname(__file__)
    _path = path.join(_path,"/cds/home/d/djr/scripts/quotes.json")
    _quotes = json.loads(open(_path, 'rb').read())
    _quote = _quotes[random.randint(0,len(_quotes)-1)]
    _res = {'quote':_quote['text'],"author":_quote['from']}
    return _res


def autorun(sample='?', run_length=300, record=True, runs=5, inspire=False, delay=5):
    """
    Automate runs.... With optional quotes

    Parameters
    ----------
    sample: str, optional
        Sample Name

    run_length: int, optional
        number of seconds for run 300 is default

    record: bool, optional
        set True to record

    runs: int, optional
        number of runs 5 is default

    inspire: bool, optional
        Set false by default because it makes Sandra sad. Set True to inspire

    delay: int, optional
        delay time between runs. Default is 5 second but increase is the DAQ is being slow.

    Operations
    ----------

    """
    from time import sleep
    from mfx.db import daq, elog, pp
    import sys

    if sample.lower()=='water' or sample.lower()=='h2o':
        inspire=True
    try:
        for i in range(runs):
            print(f"Run Number {daq.run_number() + 1} Running {sample}......{quote()['quote']}")
            daq.begin(duration = run_length, record = record, wait = True, end_run = True)
            if record:
                if inspire:
                    elog.post(f"Running {sample}......{quote()['quote']}", run=(daq.run_number()))
                else:
                    elog.post(f"Running {sample}", run=(daq.run_number()))
            sleep(delay)
        pp.close()
        daq.end_run()
        daq.disconnect()

    except KeyboardInterrupt:
        print(f"[*] Stopping Run {daq.run_number()} and exiting...",'\n')
        pp.close()
        daq.end_run()
        daq.disconnect()
        sys.exit()
