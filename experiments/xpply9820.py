import os
import time
import os.path
import logging
import subprocess

import numpy as np
from ophyd import EpicsSignalRO
from bluesky import RunEngine
from hutch_python.utils import safe_load
from bluesky.plans import scan
from bluesky.plans import list_scan
from ophyd import Component as Cpt
from ophyd import Device, EpicsSignal
from pcdsdevices.interface import BaseInterface
from pcdsdevices.lasers.shutters import LaserShutter, LaserShutterMPOD
from pcdsdevices.mpod import MPODChannel
from xpp.db import daq, seq, elog
from ophyd.status import wait as status_wait
from pcdsdevices.sequencer import EventSequencer
from pcdsdevices.evr import Trigger
from xpp.db import cp
from xpp.db import lp
from xpp.db import xpp_pulsepicker as pp
from xpp.db import xpp_ccm as ccm
#from xpp.db import vh_rot
from xpp.evosequence import Evosequence
from pcdsdevices.device_types import Newport, IMS
from xpp.db import ao_2, ao_3, ao_4
from xpp.db import trig, fs_diode, fs_qswitch
# WAIT A WHILE FOR THE DAQ TO START
import pcdsdaq.daq
pcdsdaq.daq.BEGIN_TIMEOUT = 5

#########
# TODO  #
#########

logger = logging.getLogger(__name__)


#######################
#  Object Declaration #
#######################
# Declare shutter 
evo_shutter1 = LaserShutterMPOD('XPP:R39:MPD:CH:0', name='evo_shutter1')
evo_shutter2 = LaserShutterMPOD('XPP:R39:MPD:CH:1', name='evo_shutter2')
evo_shutter3 = LaserShutterMPOD('XPP:R39:MPD:CH:2', name='evo_shutter3')

fs_shutter  = lp

# Trigger objects - created from questionnaire

# Laser parameter
fs_t0 = 9230000 #881935 # ns
evo_t0 = 800000
fs_fix_dl = 1131000
min_evr_delay = 9280 #may depend on evr. min_evr_delay = 0 ticks for code 40

# event code
ec_sample = 0
ec_water = 0

evosequence = Evosequence(seq)

#####
# XPP event code
#####
# 94 PP      (MFX: 197)
# 95 DAQ     (MFX: 198)
# 190 WATER
# 191 SAMPLE 


class analog_switch(object):
    def __init__(self, ao, val):
        self.ao = ao
        self.val = val
        self._status = 'undefined'
        return

    def on(self):
        self.ao.set(self.val)
        self._status = 'on'
        return

    def off(self):
        self.ao.set(0)
        self._status = 'off'
        return

    @property
    def status(self):
        print(self._status)
        return





class User:
    """Generic User Object"""
    fs_shutter = fs_shutter
    _evo_shutter1 = evo_shutter1
    _evo_shutter2 = evo_shutter2
    _evo_shutter3 = evo_shutter3
    sequencer = seq
    evosequence = evosequence

    fs_t0 = fs_t0

    LED = analog_switch(ao_2, 3)
    sol1 =  analog_switch(ao_3, 3.5)
    sol2 =  analog_switch(ao_4, 3.5)

    with safe_load('Rowland'):
        row_chi = EpicsSignal('ROW:DMX:02.RBV', write_pv='ROW:DMX:02.VAL', tolerance=0.01, name='row_chi')
        row_theta = EpicsSignal('ROW:DMX:03.RBV', write_pv='ROW:DMX:03.VAL', tolerance=0.01, name='row_theta')

    # ccmE = ccm.calc

    #evr_pp = Trigger('XPP:USR:EVR:TRIG5', name='evr_pp')
    #evr_R30E28B = Trigger('XPP:R30:EVR:28:TRIGB', name='evr_R30E28B')
    #evr_pp = evr_R30E28B

    def __init__(self):
        self.delay = None
  
        with safe_load('knife'):
            self.wire_x = Newport('XPP:USR:MMN:41', name='wire_x')
            self.wire_y = Newport('XPP:USR:MMN:44', name='wire_y')


    @property
    def shutter_status(self):
        """Show current shutter status"""
        status = []
        for shutter in (self._evo_shutter1, self._evo_shutter2,
                        self._evo_shutter3, self.fs_shutter):
            status.append(shutter.state.get())
        return status


    def configure_shutters(self, pulse1=False, pulse2=False, pulse3=False):
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
        """
        for state, shutter in zip((pulse1, pulse2, pulse3),
                                  (self.evo_shutter1, self.evo_shutter2,
                                   self.evo_shutter3)):
            if state == True or state == 'OUT' or state == 2:
                shutter('OUT')
            else:
                shutter('IN')
        time.sleep(1)
        return


    def configure_sequencer(self):
        """
        EMPTY: used to clean up sequence and make GUI more readable
        DAQ: every pulse (120 Hz)
        WATER / SAMPLE: 60 Hz each, out-of-phase.

        The laser trigger is fired on the WATER slot. Make sure the laser triggers are
        on event code 190
        """
        EMPTY = [0,0,0,0]
        DAQ = [95,0,0,0]
        WATER = [190,1,0,0]
        SAMPLE = [191,1,0,0]
        sequence = [WATER, DAQ, SAMPLE, DAQ]

        self.sequencer.sequence.put_seq([EMPTY for ii in range(25)])
        time.sleep(3)
        self.sequencer.sequence.put_seq(sequence)
        self.sequencer.sync_marker.put(5)
        self.sequencer.sequence_length.put(4)
        time.sleep(1)
        return


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
        Free-sspace laser delay string
        """

        delay = self.delay
        if self.fs_shutter.state.get() == 'IN':
            return 'No free-space laser.'
        elif delay==None:
            return 'Delay not set.'
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
        Set the trigger delay for the free-space laser.
        The delay between the Q-switch and the diode flash triggers is constant.

        Parameters
        ----------
        delay: float
            Requested laser in nanoseconds. Must be less than X ms.
        """
        logger.info("Setting delay %s ns (%s us)", delay, delay/1000.)

        self.delay = delay
        fs_qswitch_delay = self.fs_t0 - delay
        fs_diode_delay = fs_qswitch_delay - fs_fix_dl

        print(f"Q-switch delay: {fs_qswitch_delay}")
        print(f"Diode delay: {fs_diode_delay}")

        fs_qswitch.ns_delay.put(fs_qswitch_delay)
        fs_diode.ns_delay.put(fs_diode_delay)
        return


    def evo_shutter1(self, state):
        if state == 'IN':
##LBG: changed evo commands here as it seems the evo_shutter methods have changed?
           # self._evo_shutter1.off()
            self._evo_shutter1.insert()
        elif state == 'OUT':
           # self._evo_shutter1.on()
            self._evo_shutter1.remove()
        else:
            raise ValueError(f'expected state \'IN\' or \'OUT\', but got {state}')

    def evo_shutter2(self, state):
        if state == 'IN':
           # self._evo_shutter2.off()
            self._evo_shutter2.insert()
        elif state == 'OUT':
           # self._evo_shutter2.on()
            self._evo_shutter2.remove()
        else:
            raise ValueError(f'expected state \'IN\' or \'OUT\', but got {state}')

    def evo_shutter3(self, state):
        if state == 'IN':
           # self._evo_shutter3.off()
            self._evo_shutter3.insert()
        elif state == 'OUT': 
           # self._evo_shutter3.on()
            self._evo_shutter3.remove()
        else:
            raise ValueError(f'expected state \'IN\' or \'OUT\', but got {state}')

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
        #raise ValueError('fiber 3 is busted, cannot do')
         self.evo_shutter1('OUT')
         self.evo_shutter2('OUT')
         self.evo_shutter3('OUT') 



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

        comment = comment or ''
        # Start recording
        logger.info("Starting DAQ run, -> record=%s", record)
        daq.begin(events=events, record=record)
        time.sleep(1)
        # Post to ELog if desired
        runnum = daq._control.runnumber()
        info = [runnum, comment, events, self._delaystr]
        info.extend(self.shutter_status)
        post_msg = post_template.format(*info)
        print(post_msg)
        if post and record:
            elog(msg=post_msg, run=runnum)

        # Wait for the DAQ to finish
        logger.info("Waiting or DAQ to complete %s events ...", events)
        daq.wait()
        logger.info("Run complete!")
        daq.end_run()
        time.sleep(0.5)
        return


    def continuous_ccmscan(self,energies, pointTime=1, move_vernier=True, bidirectional=False, kill=True):
    #Set to go up an down once.
        initial_energy=ccm.E_Vernier.position
        try:
            for E in energies:
                if move_vernier:
                    ccm.E_Vernier.move(E, kill=kill)
                else:
                    ccm.E.move(E, kill=kill)
                time.sleep(pointTime)
            if bidirectional:
                for E in energies[::-1]:
                    if move_vernier:
                        ccm.E_Vernier.move(E, kill=kill)
                    else:
                        ccm.E.move(E, kill=kill)
                    time.sleep(pointTime)
        except KeyboardInterrupt:
                print(f'Scan end signal received. Returning ccm to energy before scan: {initial_energy}')
                ccm.E_Vernier.move(initial_energy, kill=False)
        finally:
            if move_vernier:
                ccm.E_Vernier.move(initial_energy, kill=kill)
            else:
                ccm.E.move(initial_energy, kill=kill)
            time.sleep(pointTime)


    def perform_run_with_escan(self, energies, record=True, comment='', pointTime=1,
                                 post=True, move_vernier=True,bidirectional=False,
                    **kwargs):
        """
        Perform a single run of the experiment

        Parameters
        ----------
        energies: List[float] a list of energies to scan over

        record: bool, optional
            Whether to record the run

        comment : str, optional
            Comment for ELog

        pointTime : int, optional
            how long in seconds to wait at a given energy before moving

        post: bool, optional
            Whether to post to the experimental ELog or not. Will not post if
            not recording

        move_vernier: bool, optional
            Whether or not to move the vernier while scanning the channel cut mono.

        kwargs:
            Used to control the laser shutters. See ``configure_shutters`` for more
            information

        Note
        ----
        This does not configure the laser parameters. Either use ``loop`` or
        ``configure_evr`` and ``configure_sequencer`` to set these parameters
        """
        # MS added
        # configure the shutters
        self.configure_shutters(**kwargs)        

        # Create descriptive message
        comment = comment or ''
        logger.info("Starting DAQ run, -> record=%s", record)
        daq.disconnect()
        daq.configure()
        try:
            #start DAQ, then start scanning
            daq.begin(record=record) #note we do not specify # of events, so it records until we stop
            # Post to ELog if desired
            runnum = daq._control.runnumber()
            info = [runnum, comment, self._delaystr, min(energies), max(energies)]
            info.extend(self.shutter_status)
            post_msg = post_template_escan.format(*info)
            time.sleep(1) # give DAQ a second
            print(post_msg)
            if post and record:
                elog.post(msg=post_msg, run=runnum)
            #now start scanning
            self.continuous_ccmscan(energies, pointTime=pointTime, move_vernier=move_vernier,bidirectional=bidirectional)
        except KeyboardInterrupt:
            print('Interrupt signal received. Stopping run and DAQ')
        finally: 
            daq.end_run()
            logger.info("Run complete!")
            daq.disconnect()
        
        

    def loop(self, delays=[], nruns=1, pulse1=False, pulse2=False,
            pulse3=False, light_events=3000, dark_events=None,
            record=True, comment='', post=True):
        """
        Loop through a number of delays a number of times while running the DAQ
        Parameters
        ----------
        delays: list, optional
            Requested laser delays in nanoseconds
            close fs_shutter if False or None, 
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
        # Preserve the original state of DAQ
        logger.info("Running delays %r, %s times ...", delays, nruns)
        delays = delays or [False]
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
                            #self.fs_shutter('IN') OPO DOES NOT EXIST FOR THIS EXPERIMENT
                        else:
                            logger.info("Beginning light events using delay %s", delay)
                            # Open state = 2
                            #self.fs_shutter('OUT') OPO DOES NOT EXIST FOR THIS EXPERIMENT
                            self.set_delay(delay)

                        # Perform the light run
                        self.perform_run(light_events, pulse1=pulse1,
                                         pulse2=pulse2, pulse3=pulse3,
                                         record=record,
                                         post=post, comment=comment)

                    # Perform the dark run
                    # No shutter information means all closed!
                    if dark_events:
                        #fs_shutter.move(1)
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
            self.configure_shutters(pulse1=False, pulse2=False, pulse3=False)
            #self.fs_shutter('IN')
        return


    def loop_escan(self, energies, delays=[], nruns=1, pulse1=False, pulse2=False,
            pulse3=False, record=True, comment='', post=True, pointTime = 1, move_vernier=True):
        """
        Loop through a number of delays a number of times while running the DAQ
        Parameters
        ----------
        delays: list, optional
            Requested laser delays in nanoseconds
            close fs_shutter if False or None, 
            i.e., delays=[None, 1000, 1e6, 1e7] loop through:
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
        record: bool, optional
            Whether to record the run or not
        comment: str, optional
           Comment for ELog
        post : bool, optional
           Whether to post to ELog or not. Will not post if not recording.
        pointTime: positive Number, optional
           time in seconds to dwell at a given energy before moving
        move_vernier: bool, optional
            whether to have vernier track CCM motion or not
        """
        # Accept a single int or float
        if isinstance(delays, (float, int)):
            delays = [delays]
        # Preserve the original state of DAQ
        logger.info("Running delays %r, %s times ...", delays, nruns)
        delays = delays or [False]
        try:
            for irun in range(nruns):
                run = irun+1
                logger.info("Beginning run %s of %s", run, nruns)
                for delay in delays:
                    # Set the laser delay if it exists
                    if delay is None or delay is False:
                        logger.info("No delay set for this run.")
                        # Close state = 1
                        #fs_shutter('IN')
                    else:
                        logger.info("Beginning light events using delay %s", delay)
                        # Open state = 2
                        #fs_shutter('OUT')
                        self.set_delay(delay)

                    # Perform the run
                    self.perform_run_with_escan(energies,
                                 pulse1=pulse1,
                                 pulse2=pulse2, 
                                 pulse3=pulse3,
                                 record=record,
                                 post=post,
                                 comment=comment,
                                 pointTime=pointTime,
                                 move_vernier=move_vernier)
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
            self.configure_shutters(pulse1=False, pulse2=False, pulse3=False)
            #self.fs_shutter('IN')
        return

    def dummy_daq_test(self, events=360, sleep=3, record=False):
        daq.connect()
        while 1:
            daq.begin(events=events, record=record)
            daq.wait()
            daq.end_run()
            time.sleep(sleep)
            print(time.ctime(time.time()))
        return

    def ccm_many(self, elist, pointTime=1, nRepeat=10, kill=True):
        for ii in range(nRepeat):
            print(f'Start scan {ii}')
            self.continuous_ccmscan(elist, pointTime=pointTime, kill=kill)
        return


post_template = """\
Run Number: {} {}

Acquiring {} events

{}

While the laser shutters are:
EVO Pulse 1 ->  {}
EVO Pulse 2 ->  {}
EVO Pulse 3 ->  {}
OPO Shutter ->  {}
"""


post_template_escan = """\
Run Number: {} {}

{}
Minimum photon_energy -> {}
Maximum photon_energy -> {}

While the laser shutters are:
EVO Pulse 1 ->  {}
EVO Pulse 2 ->  {}
EVO Pulse 3 ->  {}
OPO Shutter ->  {}
"""
