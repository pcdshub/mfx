
def quote():
    import json,random
    from os import path
    _path = path.dirname(__file__)
    _path = path.join(_path,"/cds/home/d/djr/scripts/quotes.json")
    _quotes = json.loads(open(_path, 'rb').read())
    _quote = _quotes[random.randint(0,len(_quotes)-1)]
    _res = {'quote':_quote['text'],"author":_quote['from']}
    return _res


class Laser:
    def __init__(self,
                 opo_shutter_pv='MFX:USR:ao1:6',
                 opo_trigger_pv='MFX:LAS:EVR:01:TRIG6',
                 evo_shutter1_pv='MFX:USR:ao1:7',
                 evo_shutter2_pv='MFX:USR:ao1:2',
                 evo_shutter3_pv='MFX:USR:ao1:3',
                 evo_trigger_pv='MFX:LAS:EVR:01:TRIG8'):
        from mfx.devices import LaserShutter
        from pcdsdevices.evr import Trigger
        # Declare shutter and trigger objects
        self.opo_shutter = LaserShutter(opo_shutter_pv, name='opo_shutter')
        self.evo_shutter1 = LaserShutter(evo_shutter1_pv, name='evo_shutter1')
        self.evo_shutter2 = LaserShutter(evo_shutter2_pv, name='evo_shutter2')
        self.evo_shutter3 = LaserShutter(evo_shutter3_pv, name='evo_shutter3')
        self.opo = Trigger(opo_trigger_pv, name='opo_trigger')
        self.evo = Trigger(evo_trigger_pv, name='evo_trigger')
        # Laser parameters
        self.delay = None
        self.opo_time_zero = 576058
        # Event code switch logic for longer delay
        self.min_evr_delay = 669800
        self.opo_ec_short = 203
        self.opo_ec_long = 203
        self.rep_rate = 20

    @property
    def _delaystr(self):
        """
        OPO delay string
        """
        delay = self.delay
        if self.opo_shutter.state.value == 'IN':
            return 'No OPO Laser'
        elif delay >= 1e6:
            return 'Laser delay is set to {:10.6f} ms'.format(delay/1.e6)
        elif delay >= 1e3:
            return 'Laser delay is set to {:7.3f} us'.format(delay/1.e3)
        elif delay >= 0:
            return 'Laser delay is set to {:4.0f} ns'.format(delay)
        else:
            return 'Laser delay is set to {:8.0f} ns (AFTER X-ray pulse)'.format(delay)

    def set_delay(self,delay):
        print(f"Setting delay {delay} ns ({delay/1000} us).")
        self.delay = delay
        opo_delay = self.opo_time_zero - delay
        opo_ec = self.opo_ec_short
        if delay > self.min_evr_delay:
            opo_delay += 1e9 / 120
            opo_ec = self.opo_ec_long
        self.opo.ns_delay.put(opo_delay)
        print(f"Setting OPO delay {opo_delay} ns")
        self.opo.eventcode.put(opo_ec)
        print(f"Setting OPO ec {opo_ec}")
        print(self._delaystr)


def autorun(sample='?', run_length=300, record=True,
            runs=5, inspire=False, delay=5, picker=None,
            laser_delay=None):
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

    picker: str, optional
        If 'open' it opens pp before run starts. If 'flip' it flipflops before run starts

    Operations
    ----------

    """
    from time import sleep
    from mfx.db import daq, elog, pp
    import sys

    if laser_delay is not None:
        laser = Laser()
        laser.opo_shutter.move(2)
        laser.set_delay(laser_delay)
    if sample.lower()=='water' or sample.lower()=='h2o':
        inspire=True
    if picker=='open':
        pp.open()
    if picker=='flip':
        pp.flipflop()
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
        if laser_delay is not None:
            laser.opo_shutter.move(1)
        pp.close()
        daq.end_run()
        daq.disconnect()

    except KeyboardInterrupt:
        print(f"[*] Stopping Run {daq.run_number()} and exiting...",'\n')
        if laser_delay is not None:
            laser.opo_shutter.move(1)
        pp.close()
        daq.stop()
        daq.disconnect()
        sys.exit()
