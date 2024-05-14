import logging
from time import sleep
import sys

from mfx.devices import LaserShutter
from mfx.db import daq, sequencer, elog, pp
from pcdsdevices.evr import Trigger
from mfx.autorun import quote

from pcdsdevices.lasers.shutters import LaserShutter

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
opo = Trigger('MFX:LAS:EVR:01:TRIG8', name='opo_trigger')
evo = Trigger('MFX:LAS:EVR:01:TRIG6', name='evo_trigger')

# Laser parameter
opo_time_zero = 671740 # -230000-2000
#xfel_time_zero = 894857.1 # 894808
#base_inhibit_delay = 500000
#evo_time_zero = 800000
#min_evr_delay = 9280 #may depend on evr. min_evr_delay = 0 ticks for code 40
#diode_delay = xfel_time_zero - opo_time_zero

# Event code switch logic for longer delay
min_evr_delay = 669800
opo_ec_short = 211
opo_ec_long  = 212
PP = 197
DAQ = 198
WATER = 190
SAMPLE = 191

rep_rate = 20


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
    evo = evo


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


    def configure_shutters(self, pulse1=False, pulse2=False, pulse3=False, opo=None):
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

        opo: bool
            Controls ``opo_shutter``
        """
        for state, shutter in zip((pulse1, pulse2, pulse3, opo),
                                  (self.evo_shutter1, self.evo_shutter2,
                                   self.evo_shutter3, opo_shutter)):
            if state is not None:
                if state == True or state == 'OUT' or state == 2:
                    shutter('OUT')
                else:
                    shutter('IN')
        logger.info("Shutters set to pulse1=%s, pulse2=%s, pulse3=%s, opo=%s", pulse1, pulse2, pulse3, opo)
                #logger.debug("Using %s : %s", shutter.name, state)
                #shutter.move(int(state) + 1)
        sleep(1)
        return


    def zero_flash(self):
        return configure_shutters(pulse1=False, pulse2=False, pulse3=False, opo=None)


    def one_flash(self):
        return configure_shutters(pulse1=False, pulse2=False, pulse3=True, opo=None)


    def two_flash(self):
        return configure_shutters(pulse1=False, pulse2=True, pulse3=True, opo=None)


    def three_flash(self):
        return configure_shutters(pulse1=True, pulse2=True, pulse3=True, opo=None)


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
            Requested laser delay in nanoseconds. Must be less that 15.5 ms
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


    ######################
    # Scanning Functions #
    ######################
    def perform_run(self, sample='?', run_length=300, record=True, runs=5, inspire=False, delay=5, picker=None,
                    **kwargs):
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

        delay: int, optional
            delay time between runs. Default is 5 second but increase is the DAQ is being slow.

        picker: str, optional
            If 'open' it opens pp before run starts. If 'flip' it flipflops before run starts

        kwargs:
            Used to control the laser shutters. See ``configure_shutters`` for more
            information

        Note
        ----
        This does not configure the laser parameters. Either use ``loop`` or
        ``configure_evr`` and ``configure_sequencer`` to set these parameters
        """
        # Configure the shutters
        self.configure_shutters(**kwargs)

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
            pp.close()
            self.configure_shutters(pulse1=False, pulse2=False, pulse3=False, opo=False)
            daq.end_run()
            daq.disconnect()

        except KeyboardInterrupt:
            print(f"[*] Stopping Run {daq.run_number()} and exiting...",'\n')
            pp.close()
            self.configure_shutters(pulse1=False, pulse2=False, pulse3=False, opo=False)
            daq.stop()
            daq.disconnect()
            sys.exit()


    def loop(self, delays=[], nruns=1, pulse1=False, pulse2=False,
             pulse3=False, light_events=3000, dark_events=None,
             record=True, comment='', post=True, picker=None):
        """
        Loop through a number of delays a number of times while running the DAQ

        Parameters
        ----------
        delays: list, optional
            Requested laser delays in nanoseconds
            close opo_shutter if False or None, 
            i.e., delays=[None, 1000, 1e6, 1e7] loop through:
            - close opo shutter
            - 1 us delay
            - 1 ms delay
            - 10 ms delay

        nruns: int, optional
            Number of iterations to run requested delays

        pulse1: bool, optional
            Include the first pulse

        pulse2: bool, optional
            Include the second pulse

        pulse3: bool, optional
            Include the third pulse

        light_events: int, optional
            Number of events to sample with requested laser pulses

        dark_events: int, optional
            Number of events to sample with all lasers shuttered

        record: bool, optional
            Choice to record or not

        comment: str, optional
            Comment for ELog

        post : bool, optional
            Whether to post to ELog or not. Will not post if not recording.
        
        picker: str, optional
            If 'open' it opens pp before run starts. If 'flip' it flipflops before run starts
        """
        # Accept a single int or float
        if isinstance(delays, (float, int)):
            delays = [delays]

        # Preserve the original state of DAQ
        logger.info("Running delays %r, %s times ...", delays, nruns)
        delays = delays or [False]

        # Estimated time for completion
        try:
            for irun in range(nruns):
                run = irun+1
                logger.info("Beginning run %s of %s", run, nruns)
                for delay in delays:
                    if light_events:
                        # Set the laser delay if it exists
                        if delay is None or delay is False:
                            logger.info("Beginning light events with opo shutter closed")
                            # Close state = 1
                            opo_shutter.move(1)
                        else:
                            logger.info("Beginning light events using delay %s", delay)
                            # Open state = 2
                            opo_shutter.move(2)
                            self.set_delay(delay)

                        # Perform the light run
                        if picker=='open':
                            pp.open()
                        if picker=='flip':
                            pp.flipflop()
                        self.perform_run(light_events, pulse1=pulse1,
                                         pulse2=pulse2, pulse3=pulse3,
                                         record=record,
                                         post=post, comment=comment)
                    # Estimated time for completion
                    # Perform the dark run
                    # No shutter information means all closed!
                    if dark_events:
                        opo_shutter.move(1)
                        self.perform_run(events=dark_events, record=record,
                                         post=post, comment=comment)
            logger.info("All requested scans completed!")
        except KeyboardInterrupt:
            logger.warning("Scan interrupted by user request!")
            logger.info("Stopping DAQ ...")
            daq.stop()

        # Return the DAQ to the original state
        finally:
            logger.info("Closing pulse picker ...")
            pp.close()
            logger.info("Disconnecting from DAQ ...")
            daq.disconnect()
            logger.info("Closing all laser shutters ...")
            self.configure_shutters(pulse1=False, pulse2=False, pulse3=False, opo=False)

