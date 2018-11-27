import os
import time
import os.path
import logging
import subprocess

import numpy as np

from mfx.devices import LaserShutter
from mfx.db import daq, elog, sequencer, rayonix
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
evo = Trigger('MFX:LAS:EVR:01:TRIG5', name='evo_trigger')
pacemaker = Trigger('MFX:LAS:EVR:01:TRIG4', name='pacemaker_trigger')
inhibit = Trigger('MFX:LAS:EVR:01:TRIG6', name='inhibit_trigger')

# Laser parameter
opo_time_zero = 748935
base_inhibit_delay = 500000
evo_time_zero = 800000

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
    inhibit = inhibit
    pacemaker = pacemaker
    evo = evo

    # Use our standard Rayonix sequences
    configure_sequencer = rayonix.configure_sequencer

    @property
    def current_rate(self):
        """Current configured EventSequencer rate"""
        return rayonix.current_rate

    @property
    def delay(self):
        """
        Laser delay in ns.
        """
        code = inhibit.eventcode.get()
        ipulse = {198: 0, 210: 0, 211:1, 212:2}.get(code)
        if ipulse is None:
            print('Inhibit event code {:} invalid'.format(code))

        return opo_time_zero+ipulse*1.e9/120. - pacemaker.ns_delay.get()

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

    def configure_evr(self):
        """
        Configure the Pacemaker and Inhibit EVR

        This handles setting the correct polarity and widths. However this
        **does not** handle configuring the delay between the two EVR triggers.
        """
        logger.debug("Configuring triggers to defaults ...")
        # Pacemaker Trigger
        pacemaker.eventcode.put(40)
        pacemaker.polarity.put(0)
        pacemaker.width.put(50000.)
        pacemaker.enable()
        # Inhibit Trigger
        inhibit.polarity.put(1)
        inhibit.width.put(2000000.)
        inhibit.enable()
        time.sleep(0.5)

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

    def set_delay(self, delay):
        """
        Set the relative delay between the pacemaker and inhibit triggers

        Parameters
        ----------
        delay: float
            Requested laser delay in nanoseconds. Must be less that 15.5 ms
        """
        # Determine event code of inhibit pulse
        logger.info("Setting delay %s ns (%s us)", delay, delay/1000.)
        if delay <= 0.16e6:
            if delay > 0 and delay < 1:
                logger.info("WARNING:  Read the doc string -- delay is in ns not sec") 
            logger.debug("Triggering on simultaneous event code")
            inhibit_ec = 210
            ipulse = 0
        elif delay <= 7.e6:
            logger.debug("Triggering on one event code prior")
            inhibit_ec = 211
            ipulse = 1
        elif delay <= 15.5e6:
            logger.debug("Triggering two event codes prior")
            inhibit_ec = 212
            ipulse = 2
        else:
            raise ValueError("Invalid input %s ns, must be < 15.5 ms")
        # Determine relative delays
        pulse_delay = ipulse*1.e9/120 - delay # Convert to ns
        # Conifgure Pacemaker pulse
        pacemaker_delay = opo_time_zero + pulse_delay
        pacemaker.ns_delay.put(pacemaker_delay)
        logger.info("Setting pacemaker delay %s ns", pacemaker_delay)
        # Configure Inhibit pulse
        inhibit_delay = opo_time_zero - base_inhibit_delay + pulse_delay
        inhibit.disable()
        time.sleep(0.1)
        inhibit.ns_delay.put(inhibit_delay)
        logger.info("Setting inhibit delay %s ns", inhibit_delay)
        inhibit.eventcode.put(inhibit_ec)
        logger.info("Setting inhibit ec %s", inhibit_ec)
        time.sleep(0.1)
        inhibit.enable()
        time.sleep(0.2)
        logger.info(self._delaystr)

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
        # Start recording
        logger.info("Starting DAQ run, -> record=%s", record)
        daq.begin(events=events, record=record)
        time.sleep(2)  # Wait for the DAQ to get spinnign before sending events
        logger.debug("Starting EventSequencer ...")
        sequencer.start()
        time.sleep(1)
        # Post to ELog if desired
        runnum = daq._control.runnumber()
        info = [runnum, comment, events, self.current_rate, self._delaystr]
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
        sequencer.stop()
        # allow short time after sequencer stops
        time.sleep(0.5) 


    def loop(self, delays=[], nruns=1, pulse1=False, pulse2=False,
             pulse3=False, light_events=3000, dark_events=None, rate='10Hz',
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

        rate : str, optional
            "10Hz" or "30Hz"

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
        sequencer.stop()
        #self.configure_sequencer(rate=rate)
        self.configure_evr()
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
            logger.info("Restarting the EventSequencer ...")
            sequencer.start()

    def take_pedestals(self, nevents, record=True):
        """
        Take a set of pedestals with the Jungfrau

        Parameters
        ----------
        nevents: int
            Number of events

        record: bool, optional
            Whether to record or not
        """
        # Create subprocess call
        cwd = '/reg/g/pcds/pyps/apps/hutch-python/mfx'
        script = os.path.join(cwd, 'scripts/jungfrau/take_pedestal.sh')
        args = [script, str(nevents)]
        if record:
            args.append('--record')
        # Execute
        subprocess.call(args)

post_template = """\
Run Number: {} {}

Acquiring {} events at {}

{}

While the laser shutters are:
EVO Pulse 1 ->  {}
EVO Pulse 2 ->  {}
EVO Pulse 3 ->  {}
OPO Shutter ->  {}
"""

