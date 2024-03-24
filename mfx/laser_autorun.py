import logging
logger = logging.getLogger(__name__)

def quote():
    import json,random
    from os import path
    _path = path.dirname(__file__)
    _path = path.join(_path,"/cds/home/d/djr/scripts/quotes.json")
    _quotes = json.loads(open(_path, 'rb').read())
    _quote = _quotes[random.randint(0,len(_quotes)-1)]
    _res = {'quote':_quote['text'],"author":_quote['from']}
    return _res


class LaserSetup:
    def __init__(self):
        self.delay = None
        self._default_timing()
        self._default_pvs()
        self._declare_shutters_n_triggers()

    def _default_pvs(self):
        """
        Default PVs for laser shutters and triggers

        Note: these values need to be found and replaced using the .set_pvs() function.
        """
        for key,value in zip(
                ('opo_shutter','evo_shutter1','evo_shutter2','evo_shutter3',
                 'opo_trigger','evo_trigger'),
                ('MFX:USR:ao1:6','MFX:USR:ao1:7','MFX:USR:ao1:2','MFX:USR:ao1:3',
                 'MFX:LAS:EVR:01:TRIG6','MFX:LAS:EVR:01:TRIG8')):
            logger.info(f'Default PV - {key}: {value}')
            self.pvs[key] = value

    def _default_timing(self):
        """
        Default/placeholder values for:
        - OPO time-zero
        - OPO event code for delays shorter than min_evr_delay
        - OPO event code for delays longer than min_evr_delay
        - min_evr_delay

        Note: these values need to be found and replaced using the .set_timing() function.
        """
        for key,value in zip(
                ('opo_time_zero', 'opo_ec_short', 'opo_ec_long', 'min_evr_delay'),
                (576058, 203, 203, 669800)):
            logger.info(f'Default timing - {key}: {value}')
            self.timing[key] = value

    def _declare_shutters_n_triggers(self):
        """
        Declares/Instantiates the OPO and EVO shutter and trigger objects.
        """
        from mfx.devices import LaserShutter
        from pcdsdevices.evr import Trigger
        self.opo_shutter = LaserShutter(self.pvs['opo_shutter'], name='opo_shutter')
        self.evo_shutter1 = LaserShutter(self.pvs['evo_shutter1'], name='evo_shutter1')
        self.evo_shutter2 = LaserShutter(self.pvs['evo_shutter2'], name='evo_shutter2')
        self.evo_shutter3 = LaserShutter(self.pvs['evo_shutter3'], name='evo_shutter3')
        self.opo = Trigger(self.pvs['opo_trigger'], name='opo_trigger')
        self.evo = Trigger(self.pvs['evo_trigger'], name='evo_trigger')
        logger.info(f'OPO and EVO shutters and triggers declared.')

    def set_pvs(self, pv_name, pv_value):
        """
        Updates the PVs associated with laser shutters and triggers.
        """
        self.pvs = {}
        if pv_name in self.pvs:
            logger.info(f'PV {pv_name}: replacing {self.pvs[pv_name]} by {pv_value}')
            self.pvs[pv_name] = pv_value

    def set_timing(self, key, value):
        """
        Updates the values of:
        - OPO time-zero
        - OPO event code for delays shorter than min_evr_delay
        - OPO event code for delays longer than min_evr_delay
        - min_evr_delay
        """
        if key in self.timing:
            logger.info(f'Timing {key}: replacing {self.timing[key]} by {value}')
            self.timing[key] = value

    @property
    def _delaystr(self):
        """
        OPO delay string
        """
        if self.opo_shutter.state.value == 'IN':
            return 'No OPO Laser'
        elif self.delay >= 1e6:
            return f'Laser delay is set to {self.delay/1.e6:10.6f} ms'
        elif self.delay >= 1e3:
            return f'Laser delay is set to {self.delay/1.e3:7.3f} us'
        elif self.delay >= 0:
            return f'Laser delay is set to {self.delay:4.0f} ns'
        else:
            return f'Laser delay is set to {self.delay:8.0f} ns (AFTER X-ray pulse)'

    def set_delay(self,delay):
        """
        Set up OPO delay and event code in EVR panel

        Parameters
        ----------
        delay: float
            Desired OPO pump X-ray probe delay in nanosecond.
        """
        logger.info(f"Setting delay {delay} ns ({delay/1000} us).")
        self.delay = delay
        opo_delay = self.timing['opo_time_zero'] - self.delay
        opo_ec = self.timing['opo_ec_short']
        if self.delay > self.timing['min_evr_delay']:
            opo_delay += 1e9 / 120
            opo_ec = self.timing['opo_ec_long']
        self.opo.ns_delay.put(opo_delay)
        logger.info(f"Setting OPO delay {opo_delay} ns")
        self.opo.eventcode.put(opo_ec)
        logger.info(f"Setting OPO event code: {opo_ec}")
        logger.info(self._delaystr)


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

    laser_delay: float, optional
        If not None, sets the OPO laser delay relative to time zero.

    Operations
    ----------

    """
    from time import sleep
    from mfx.db import daq, elog, pp
    import sys

    if laser_delay is not None:
        laser = LaserSetup()
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
            logger.info(f"Run Number {daq.run_number() + 1} Running {sample}......{quote()['quote']}")
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
        logger.info(f"[*] Stopping Run {daq.run_number()} and exiting...",'\n')
        if laser_delay is not None:
            laser.opo_shutter.move(1)
        pp.close()
        daq.stop()
        daq.disconnect()
        sys.exit()
