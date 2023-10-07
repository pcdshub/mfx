import os
import time
import os.path
import logging
import subprocess

import numpy as np

from mfx.devices import LaserShutter
from mfx.db import daq, elog, sequencer, rayonix
from ophyd.status import wait as status_wait
from pcdsdevices.sequencer import EventSequencer
from pcdsdevices.evr import Trigger

# WAIT A WHILE FOR THE DAQ TO START
import pcdsdaq.daq
pcdsdaq.daq.BEGIN_TIMEOUT = 5

#########
# TODO  #
#########
# * elog
# * time estimations


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
    # inhibit = inhibit
    # pacemaker = pacemaker
    opo = opo
    evo = evo
    def __init__(self):
    	self.delay = None

    # Use our standard Rayonix sequences
    #configure_sequencer = rayonix.configure_sequencer

    #@property
    #def current_rate(self):
    #    """Current configured EventSequencer rate"""
    #    return rayonix.current_rate

    # @property
    # def delay(self):
    #     """
    #     Laser delay in ns.
    #     """
    #     code = inhibit.eventcode.get()
    #     ipulse = {198: 0, 210: 0, 211: 1, 212: 2, 40: 0}.get(code)
    #     # ipulse = {198: 0, 210: 0, 211: 1, 212: 2}.get(code)
    #     if ipulse is None:
    #         print('Inhibit event code {:} invalid'.format(code))

    #     return opo_time_zero + ipulse * 1.e9 / 120. - pacemaker.ns_delay.get()

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
                                  (evo_shutter1, evo_shutter2,
                                   evo_shutter3, opo_shutter)):
            if state is not None:
                logger.debug("Using %s : %s", shutter.name, state)
                shutter.move(int(state) + 1)

        time.sleep(1)

    #def configure_evr(self):
    #    """
    #    Configure the Pacemaker and Inhibit EVR
    #
    #    This handles setting the correct polarity and widths. However this
    #    **does not** handle configuring the delay between the two EVR triggers.
    #    """
    #    logger.debug("Configuring triggers to defaults ...")
        # Pacemaker Trigger
        # pacemaker.eventcode.put(40)
        # pacemaker.polarity.put(0)
        # pacemaker.width.put(50000.)
        # pacemaker.enable()
        # Inhibit Trigger
    #    inhibit.polarity.put(0)
        # inhibit.width.put(2000000.)
    #    inhibit.enable()
    #    time.sleep(0.5)

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

    def zero_flash(self):
        self.evo_shutter1('IN')
        self.evo_shutter2('IN')
        self.evo_shutter3('IN')

    def one_flash(self):
        self.evo_shutter1('IN')
        self.evo_shutter2('IN')
        self.evo_shutter3('OUT')

    def two_flash(self):
        self.evo_shutter1('IN')
        self.evo_shutter2('OUT')
        self.evo_shutter3('OUT')

    def three_flash(self):
        self.evo_shutter1('OUT')
        self.evo_shutter2('OUT')
        self.evo_shutter3('OUT') 


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
        #if delay > 0 and delay < 1:
        #        logger.info("WARNING:  Read the doc string -- delay is in ns not sec")
        #if delay < 0:
        #	raise ValueError("delay must be positive")
        #if  (1e9/120 + opo_time_zero - delay) >= min_evr_delay:
        #    logger.debug("Triggering on simultaneous event code")
        #    opo_ec = 211
        #    ipulse = 1
        #elif (2e9/120 + opo_time_zero - delay) >= min_evr_delay:
        #    logger.debug("Triggering on one event code prior")
        #    opo_ec = 212
        #    ipulse = 2
        #else:
        #    raise ValueError("Invalid input. Your delay is too big")

        # if delay <= (opo_time_zero - min_evr_delay): 
            # pacemaker_delay = opo_time_zero - delay
        # elif delay <= (1.e9/120 + opo_time_zero - min_evr_delay): 
            # pacemaker_delay = opo_time_zero + 1.e9/120 - delay
        # elif delay <= (2.e9/120 + opo_time_zero - min_evr_delay):
            # pacemaker_delay = opo_time_zero + 2.e9/120 - delay
        # else:
            # raise ValueError("Invalid input %s ns, must be < 15.5 ms")

#        # Determine relative delays
#        # pulse_delay = ipulse*1.e9/120 - delay # Convert to ns
#        # Conifgure Pacemaker pulse
#        # pacemaker_delay = opo_time_zero + pulse_delay
#        # pacemaker.ns_delay.put(pacemaker_delay)
#        # logger.info("Setting pacemaker delay %s ns", pacemaker_delay)
#        # Configure Inhibit pulse
        #opo_delay = ipulse*1.e9/120 + opo_time_zero - delay
        #opo.disable()
        #time.sleep(0.1)
        opo.ns_delay.put(opo_delay)
        logger.info("Setting OPO delay %s ns", opo_delay)
        opo.eventcode.put(opo_ec)
        logger.info("Setting OPO ec %s", opo_ec)
        #time.sleep(0.1)
        #opo.enable()
        #time.sleep(0.2)
        logger.info(self._delaystr)
#        # logger.info("The laser delay is set to %s ns (%s us)", delay, delay/1000.)
#
#    def set_evo_delay(self, delay):
#        """
#        Set the evolution laser triggers delay
#
#        Parameters
#        ----------
#        delay: float
#            Requested evo laser delay in nanoseconds. Must be less that 15.5 ms
#        """
#        # Determine event code of evo pulse
#        logger.info("Setting evo delay %s ns (%s us)", delay, delay/1000.)
#        if delay <= 0.16e6:
#            logger.debug("Triggering on simultaneous event code")
#            evo_ec = 210
#            ipulse = 0
#        elif delay <= 7.e6:
#            logger.debug("Triggering on one event code prior")
#            evo_ec = 211
#            ipulse = 1
#        elif delay <= 15.5e6:
#            logger.debug("Triggering two event codes prior")
#            evo_ec = 212
#            ipulse = 2
#        else:
#            raise ValueError("Invalid input %s ns, must be < 15.5 ms")
#        # Determine relative delay
#        pulse_delay = ipulse*1.e9/120 - delay # Convert to ns
#        # Configure Inhibit pulse
#        evo_delay = evo_time_zero + pulse_delay
#        evo.eventcode.put(evo_ec)
#        evo.ns_delay.put(evo_delay)
#
    ######################
    # Scanning Functions #
    ######################
    def perform_run(self, events, record=True, comment='', post=True,
                    **kwargs):
        """
        Perform a single run of the experiment

        Parameters
        ----------
        events: int
            Number of events to include in run

        record: bool, optional
            Whether to record the run

        comment : str, optional
            Comment for ELog

        post: bool, optional
            Whether to post to the experimental ELog or not. Will not post if
            not recording

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
        # time.sleep(3) / a leftover from original script
        # Create descriptive message
        comment = comment or ''
        # Setup Event Sequencer
        #sequencer.stop()
        #sequencer.rep_count.put(events)
        #sequencer.play_mode.put(1)  # Run N Times
        # Start recording
        logger.info("Starting DAQ run, -> record=%s", record)
        daq.begin(events=events, record=record)
        #time.sleep(5)  # Wait for the DAQ to get spinnign before sending events
        #logger.debug("Starting EventSequencer ...")
        #sequencer.kickoff()
        time.sleep(1)
        # Post to ELog if desired
        runnum = daq._control.runnumber()
        info = [runnum, comment, events, rep_rate, self._delaystr]
        info.extend(self.shutter_status)
        post_msg = post_template.format(*info)
        print(post_msg)
        if post and record:
            elog.post(post_msg, run=runnum)
        # Wait for the DAQ to finish
        logger.info("Waiting or DAQ to complete %s events ...", events)
        daq.wait()
        logger.info("Run complete!")
        daq.end_run()
        logger.debug("Stopping Sequencer ...")
        #sequencer.stop()
        #logger.info("Waiting for Sequencer to complete")
        #status_wait(sequencer.complete())
        #logger.info("Run complete!")
        #logger.debug("Stopping DAQ")
        #daq.end_run()
        # allow short time after sequencer stops
        time.sleep(0.5)


    def loop(self, delays=[], nruns=1, pulse1=False, pulse2=False,
             pulse3=False, light_events=3000, dark_events=None,
             record=True, comment='', post=True):
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
        """
        # Accept a single int or float
        if isinstance(delays, (float, int)):
            delays = [delays]
        # Stop the EventSequencer
        #sequencer.stop()
        #self.configure_sequencer(rate=rate)
        #self.configure_evr()
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
            logger.info("Disconnecting from DAQ ...")
            daq.disconnect()
            logger.info("Closing all laser shutters ...")
            self.configure_shutters(pulse1=False, pulse2=False, pulse3=False, opo=False)
#            logger.info("Restarting the EventSequencer ...")
#            sequencer.play_mode.put(2)  # Run Forever!
#            sequencer.start()


post_template = """\
Run Number: {} {}

Acquiring {} events at {} Hz

{}

While the laser shutters are:
EVO Pulse 1 ->  {}
EVO Pulse 2 ->  {}
EVO Pulse 3 ->  {}
OPO Shutter ->  {}
"""

