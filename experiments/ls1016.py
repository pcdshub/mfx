import os
import time
import os.path
import logging
import subprocess

from mfx.devices import LaserShutter
from mfx.db import daq, elog
from pcdsdevices.sequencer import EventSequencer, EventStep
from pcdsdevices.evr import Trigger

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
evo_shutter2 = LaserShutter('MFX:USR:ao1:2', name='evo_shutter1')
evo_shutter3 = LaserShutter('MFX:USR:ao1:3', name='evo_shutter1')

# Sequencer object
sequencer = EventSequencer('ECS:SYS0:7', name='mfx_sequencer')

# Sequencer steps
seq_prefix = 'MFX:ECS:IOC:01'
seq_no = 7
seq_steps = [EventStep(seq_prefix, seq_no, step, name='step_{}'.format(step))
             for step in range(0, 20)]

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

    @property
    def current_rate(self):
        """Current configured EventSequencer rate"""
        return sequencer.sync_marker.get(as_string=True)

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

    def configure_sequencer(self, rate='10Hz'):
        """
        Setup laser triggers and EventSequencer

        Parameters
        ----------
        rate : str, optional
            "10Hz" or "30Hz"
        """
        logger.info("Configure EventSequencer ...")
        # Setup sequencer
        sequencer.sync_marker.put(rate)
        if rate == '10Hz':
            delta0 = 10
        elif rate == '30Hz':
            delta0 = 2
        else: 
            delta0 = 2

        sequencer.sequence_length.put(5)
        # Set sequence
        seq_steps[0].configure({'eventcode': 197, 'delta_beam': delta0,
                                'fiducial': 0, 'comment': 'PulsePicker'})
        seq_steps[1].configure({'eventcode': 212, 'delta_beam': 0,
                                'fiducial': 0, 'comment': 'Delay > 7 ms'})
        seq_steps[2].configure({'eventcode': 211, 'delta_beam': 1,
                                'fiducial': 0, 'comment': 'Delay > 160 us'})
        seq_steps[3].configure({'eventcode': 210, 'delta_beam': 1,
                                'fiducial': 0, 'comment': 'Delay < 160 us'})
        seq_steps[4].configure({'eventcode': 198, 'delta_beam': 0,
                                'fiducial': 0, 'comment': 'DAQ Readout'})
        # Clear other sequence steps 
        for i in range(5, 20):
            seq_steps[i].clear()

    def configure_evr(self):
        """
        Configure the Pacemaker and Inhibit EVR

        This handles setting the correct polarity and widths. However this
        **does not** handle configuring the delay between the two EVR triggers.
        """
        logger.debug("Configuring triggers to defaults ...")
        # Pacemaker Trigger
        pacemaker.configure({'eventcode': 40, 'polarity': 0,
                             'width': 50000.})
        pacemaker.enable()
        # Inhibit Trigger
        inhibit.configure({'polarity': 1, 'width': 2000000.})
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
        pacemaker.configure({"ns_delay": pacemaker_delay})
        logger.info("Setting pacemaker delay %s ns", pacemaker_delay)
        # Configure Inhibit pulse
        inhibit_delay = opo_time_zero - base_inhibit_delay + pulse_delay
        inhibit.configure({"ns_delay": inhibit_delay})
        logger.info("Setting inhibit delay %s ns", inhibit_delay)
        inhibit.configure({"eventcode": inhibit_ec})
        logger.info("Setting inhibit ec %s", inhibit_ec)
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
#        evo.configure({"eventcode": evo_ec, "ns_delay": evo_delay})

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
        # Stop the EventSequencer
        sequencer.stop()
        self.configure_sequencer(rate=rate)
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

