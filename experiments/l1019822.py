import logging
from time import sleep
import sys

from mfx.devices import LaserShutter
from mfx.db import daq, sequencer, elog, pp
from pcdsdevices.evr import Trigger
from mfx.autorun import quote

logger = logging.getLogger(__name__)

#######################
#  Object Declaration #
#######################

# Declare shutter objects
opo_shutter = LaserShutter('MFX:USR:ao1:6', name='opo_shutter')
evo_shutter1 = LaserShutter('MFX:USR:ao1:7', name='evo_shutter1')
evo_shutter2 = LaserShutter('MFX:USR:ao1:2', name='evo_shutter2')
evo_shutter3 = LaserShutter('MFX:USR:ao1:3', name='evo_shutter3')

# Trigger objects
opo = Trigger('MFX:LAS:EVR:01:TRIG6', name='opo_trigger')
evo = Trigger('MFX:LAS:EVR:01:TRIG5', name='evo_trigger')

# Laser parameter
opo_time_zero = 671765 # -230000-2000
#xfel_time_zero = 894857.1 # 894808
#base_inhibit_delay = 500000
#evo_time_zero = 800000
#min_evr_delay = 9280 #may depend on evr. min_evr_delay = 0 ticks for code 40
#diode_delay = xfel_time_zero - opo_time_zero

# Event code switch logic for longer delay
min_evr_delay = 671765
opo_ec_short = 212
opo_ec_long = 211
PP = 197
DAQ = 198
WATER = 211
SAMPLE = 212

rep_rate = 20

# Not-None sentinal for default value when None has a special meaning
# Indicates that the last configured value should be used
_CONFIG_VAL = object()

###########################
# Configuration Functions #
###########################

class User:
    """Generic User Object"""
    opo_shutter = opo_shutter
    evo_shutter1 = evo_shutter1
    evo_shutter2 = evo_shutter2
    evo_shutter3 = evo_shutter3
    sequencer = sequencer
    opo = opo


    def __init__(self):
        self.delay = None


    @property
    def shutter_status(self):
        """Show current shutter status"""
        status = []
        for shutter in (evo_shutter1, evo_shutter2,
                        evo_shutter3, opo_shutter):
            status.append(shutter.state.get())
        return status


    def configure_shutters(self, pulse1=False, pulse2=False, pulse3=False, free_space=None):
        """
        Configure all four laser shutters

        True means that the pulse will be used and the shutter is removed.
        False means that the pulse will be blocked and the shutter is inserted 
           - default for evo laser pulse1, pulse2, pulse3
        None means that the shutter will not be changed
           - default for opo laser

        Parameters
        ----------
        pulse1: bool
            Controls ``evo_shutter1``

        pulse2: bool
            Controls ``evo_shutter2``

        pulse3: bool
            Controls ``evo_shutter3``

        free_space: bool
            Controls ``opo_shutter``
        """
        for state, shutter in zip((pulse1, pulse2, pulse3, free_space),
                                  (self.evo_shutter1, self.evo_shutter2,
                                   self.evo_shutter3, opo_shutter)):
            if state is not None:
                if state == True or state == 'OUT' or state == 2:
                    shutter('OUT')
                else:
                    shutter('IN')
        #logger.info("Shutters set to pulse1=%s, pulse2=%s, pulse3=%s, free_space=%s", pulse1, pulse2, pulse3, free_space)
        sleep(1)
        return


    def pulse_0(self):
        return self.configure_shutters(pulse1=False, pulse2=False, pulse3=False, free_space=None)


    def pulse_1(self):
        return self.configure_shutters(pulse1=False, pulse2=False, pulse3=True, free_space=None)


    def pulse_2(self):
        return self.configure_shutters(pulse1=False, pulse2=True, pulse3=True, free_space=None)


    def pulse_3(self):
        return self.configure_shutters(pulse1=True, pulse2=True, pulse3=True, free_space=None)


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


    def _wrap_delay(self, delay, base_rate=120):
        """
        given a delay in units of nanoseconds, wrap the delay so that
        it is strictly less than the period of the base_rate
        """
        if delay*1E-9 > 1/base_rate:
            adjusted_delay = delay - (1/base_rate)*1E9
        else:
            adjusted_delay = delay
        return adjusted_delay 


    def set_delay(self, delay):
        """
        Set the delay

        Parameters
        ----------
        delay: float
            Requested laser delay in nanoseconds.
        """
        # Determine event code of inhibit pulse
        logger.info("Setting delay %s ns (%s us)", delay, delay/1000.)
        self.delay = delay
        opo_delay = opo_time_zero - delay
        opo_ec = opo_ec_short
        if delay > min_evr_delay:
            opo_delay += 1e9/120
            opo_ec = opo_ec_long

        opo.ns_delay.put(opo_delay)
        logger.info("Setting OPO delay %s ns", opo_delay)
        opo.eventcode.put(opo_ec)
        logger.info("Setting OPO ec %s", opo_ec)
        logger.info(self._delaystr)
        return


    def begin(self, events=_CONFIG_VAL, duration=_CONFIG_VAL,
              record=_CONFIG_VAL, use_l3t=_CONFIG_VAL, controls=_CONFIG_VAL,
              wait=False, end_run=False):
        """
        Start the daq and block until the daq has begun acquiring data.

        Optionally block with ``wait=True`` until the daq has finished aquiring
        data. If blocking, a ``ctrl+c`` will end the run and clean up.

        If omitted, any argument that is shared with `configure`
        will fall back to the configured value.

        Internally, this calls `kickoff` and manages its ``Status`` object.

        Parameters
        ----------
        events: ``int``, optional
            Number events to take in the daq.

        duration: ``int``, optional
            Time to run the daq in seconds, if ``events`` was not provided.

        record: ``bool``, optional
            If ``True``, we'll configure the daq to record data before this
            run.

        use_l3t: ``bool``, optional
            If ``True``, we'll run with the level 3 trigger. This means that
            if we specified a number of events, we will wait for that many
            "good" events as determined by the daq.

        controls: ``dict{name: device}`` or ``list[device...]``, optional
            If provided, values from these will make it into the DAQ data
            stream as variables. We will check ``device.position`` and
            ``device.value`` for quantities to use and we will update these
            values each time begin is called. To provide a list, all devices
            must have a ``name`` attribute.

        wait: ``bool``, optional
            If ``True``, wait for the daq to finish aquiring data. A
            ``KeyboardInterrupt`` (``ctrl+c``) during this wait will end the
            run and clean up.

        end_run: ``bool``, optional
            If ``True``, we'll end the run after the daq has stopped.
        """
        logger.debug(('Daq.begin(events=%s, duration=%s, record=%s, '
                      'use_l3t=%s, controls=%s, wait=%s)'),
                     events, duration, record, use_l3t, controls, wait)
        try:
            if record is not _CONFIG_VAL and record != daq.record:
                old_record = daq.record
                daq.preconfig(record=record, show_queued_cfg=False)
            begin_status = daq.kickoff(events=events, duration=duration,
                                        use_l3t=use_l3t, controls=controls)
            try:
                begin_status.wait(timeout=daq._begin_timeout)
            except (StatusTimeoutError, WaitTimeoutError):
                msg = (f'Timeout after {self._begin_timeout} seconds waiting '
                       'for daq to begin.')
                raise DaqTimeoutError(msg) from None

            # In some daq configurations the begin status returns very early,
            # so we allow the user to configure an emperically derived extra
            # sleep.
            time.sleep(daq.config['begin_sleep'])
            if wait:
                daq.wait()
                if end_run:
                    daq.end_run()
            if end_run and not wait:
                threading.Thread(target=self._ender_thread, args=()).start()
        except KeyboardInterrupt:
                pp.close()
                self.configure_shutters(pulse1=False, pulse2=False, pulse3=False, free_space=False)
                print(f"[*] Stopping Run {daq.run_number()} and exiting...",'\n')
                daq.stop()
                daq.disconnect()
                sys.exit()
        finally:
            try:
                daq.preconfig(record=old_record, show_queued_cfg=False)
            except NameError:
                pass


    ######################
    # Scanning Function #
    ######################
    def yano_run(self, sample='?', run_length=300, record=True, runs=5, inspire=False, daq_delay=5, picker=None, pulse=-1, free_space=None, laser_delay=None):
        """
        Perform a single run of the experiment

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

        daq_delay: int, optional
            delay time between runs. Default is 5 second but increase is the DAQ is being slow.

        picker: str, optional
            If 'open' it opens pp before run starts. If 'flip' it flipflops before run starts

        pulse: int, optional
            Number of laser pulses. Default is -1. See ``configure_shutters`` for more
            information

        free_space: bool, optional
            Sets the free_space laser shutter to Closed (False) or Open (True). Default is None.
        
        laser_delay: float
            Requested laser delay in nanoseconds.
        Note
        ----
        0: (pulse1=False, pulse2=False, pulse3=False)
        1: (pulse1=False, pulse2=False, pulse3=True)
        2: (pulse1=False, pulse2=True, pulse3=True)
        3: (pulse1=True, pulse2=True, pulse3=True)

        For alternative laser configurations either use ``configure_shutters`` to set parameters
        """
        # Configure the shutters
        if pulse == 0:
            self.pulse_0()
        elif pulse == 1:
            self.pulse_1()
        elif pulse == 2:
            self.pulse_2()
        elif pulse == 3:
            self.pulse_3()
        else:
            logger.warning("No proper pulse number set so defaulting to ``configure_shutters`` settings.")

        if free_space is not None:
            if free_space == True or str(free_space).lower()==str('out') or int(free_space) == 2 or str(free_space).lower()==str('open'):
                opo_shutter('OUT')
            else:
                opo_shutter('IN')

        if laser_delay is not None:
            self.set_delay(laser_delay)

        if sample.lower()=='water' or sample.lower()=='h2o':
            inspire=True
        if picker=='open':
            pp.open()
        if picker=='flip':
            pp.flipflop()

        for i in range(runs):
            try:
                print(f"Run Number {daq.run_number() + 1} Running {sample}......{quote()['quote']}")
                daq.begin(duration = run_length, record = record, wait = True, end_run = True)
                if record:
                    if inspire:
                        comment = f"Running {sample}......{quote()['quote']}"
                    else:
                        comment = f"Running {sample}"
                    info = [daq.run_number(), comment, self._delaystr]
                    info.extend(self.shutter_status)
                    post_msg = post_template.format(*info)
                    print('\n' + post_msg + '\n')
                    elog.post(msg=post_msg, run=(daq.run_number()))
                sleep(daq_delay)
            except KeyboardInterrupt:
                pp.close()
                self.configure_shutters(pulse1=False, pulse2=False, pulse3=False, free_space=False)
                print(f"[*] Stopping Run {daq.run_number()} and exiting...",'\n')
                daq.stop()
                daq.disconnect()
                sys.exit()
            finally:
                pp.close()
                self.configure_shutters(pulse1=False, pulse2=False, pulse3=False, free_space=False)
                daq.end_run()
                daq.disconnect()

post_template = """\
Run Number {}: {}

{}

While the laser shutters are:
EVO Pulse 1 ->  {}
EVO Pulse 2 ->  {}
EVO Pulse 3 ->  {}
OPO Shutter ->  {}
"""

