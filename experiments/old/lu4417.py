import os
import time
import os.path
import logging
import subprocess
import epics

from ophyd import (FormattedComponent as FCpt, EpicsSignal, EpicsSignalRO,
                   Device, Component as Cpt)
from hutch_python.utils import safe_load
from mfx.devices import LaserShutter
from mfx.db import daq
import pcdsdevices.utils as key_press

with safe_load('elog'):
    from mfx.db import elog

from pcdsdevices.sequencer import EventSequencer

#########
# TODO  #
#########
# * elog
# * time estimations

logger = logging.getLogger(__name__)

#######################
#  Object Declaration #
#######################


class EventStep(Device):
    """
    Individual configurable step in EventSequence
    """
    eventcode = FCpt(EpicsSignal,
                     '{self.prefix}:EC_{self._seq_no}:{self.step}')
    delta_beam = FCpt(EpicsSignal,
                     '{self.prefix}:BD_{self._seq_no}:{self.step}')
    fiducial = FCpt(EpicsSignal,
                    '{self.prefix}:FD_{self._seq_no}:{self.step}')
    comment = FCpt(EpicsSignal,
                   '{self.prefix}:EC_{self._seq_no}:{self.step}.DESC')

    _default_configuration_attrs = ('eventcode', 'delta_beam', 'fiducial',
                                    'comment')

    def __init__(self, prefix, seq_no, step, **kwargs):
        # Store both prefix and step number
        self.step = str(step).zfill(2)
        self._seq_no = seq_no
        super().__init__(prefix, **kwargs)

    def clear(self):
        """Clear all step information"""
        self.configure({'eventcode': 0, 'delta_beam': 0,
                        'fiducial': 0, 'comment': ''})

# Sequencer object
sequencer = EventSequencer('ECS:SYS0:7', name='mfx_sequencer')

# Sequencer steps
seq_prefix = 'MFX:ECS:IOC:01'
seq_no = 7
seq_steps = [EventStep(seq_prefix, seq_no, step, name='step_{}'.format(step))
             for step in range(0, 20)]


###########################
# Configuration Functions #
###########################

class User:
    SCALE = 1000.0
    """Generic User Object"""
    sequencer = sequencer

    def __init__(self):
        self.mesh_raw = EpicsSignal(name='mesh_raw',
                                    read_pv='MFX:USR:ai1:0',
                                    write_pv='MFX:USR:ao1:0')

    @property
    def current_rate(self):
        """Current configured EventSequencer rate"""
        return sequencer.sync_marker.get(as_string=True)

    def configure_sequencer(self, rate='30Hz', readout_all=False):
        """
        Setup EventSequencer (30Hz default) with event codes to tag
        the Rayonix readout and each of the preceeding 3 shots.

        Parameters
        ----------
        rate : str, optional
            default is "30Hz", or optionally "10Hz"

        readout_all : bool, optional
            Readout all events with ec198 if True
            otherwise readout only ec198 at same time as Rayonix ec210

        """
        logger.info("Configure EventSequencer ...")
        # Setup sequencer
        sequencer.sync_marker.put(rate)
        if rate == '10Hz':
            delta0 = 120/10
        elif rate == '30Hz':
            delta0 = 120/30
        else: 
            delta0 = 120/30

        # Set sequence
        #   delta0 is the number of shots until the next event code
        #   for the desired rate, e.g., ec42 for 30 Hz and ec43 for 10 Hz
        #
        seqstep = 0
        seq_steps[seqstep].configure({'eventcode': 213, 'delta_beam': delta0-3,
                                'fiducial': 0, 'comment': 'Rayonix-3'})
        seqstep += 1
        seq_steps[seqstep].configure({'eventcode': 197, 'delta_beam': 1,
                                'fiducial': 0, 'comment': 'PulsePicker'})
        if readout_all:
            seqstep += 1
            seq_steps[seqstep].configure({'eventcode': 198, 'delta_beam': 0,
                                    'fiducial': 0, 'comment': 'DAQ Readout'})
        
        seqstep += 1
        seq_steps[seqstep].configure({'eventcode': 212, 'delta_beam': 0,
                                'fiducial': 0, 'comment': 'Rayonix-2'})
        if readout_all:
            seqstep += 1
            seq_steps[seqstep].configure({'eventcode': 198, 'delta_beam': 0,
                                    'fiducial': 0, 'comment': 'DAQ Readout'})
        
        seqstep += 1
        seq_steps[seqstep].configure({'eventcode': 211, 'delta_beam': 1,
                                'fiducial': 0, 'comment': 'Rayonix-1'})
        if readout_all:
            seqstep += 1
            seq_steps[seqstep].configure({'eventcode': 198, 'delta_beam': 0,
                                    'fiducial': 0, 'comment': 'DAQ Readout'})
        
        seqstep += 1
        seq_steps[seqstep].configure({'eventcode': 210, 'delta_beam': 1,
                                'fiducial': 0, 'comment': 'Rayonix'})
        if readout_all:
            seqstep += 1
            seq_steps[seqstep].configure({'eventcode': 198, 'delta_beam': 0,
                                    'fiducial': 0, 'comment': 'DAQ Readout'})
        
        seqstep += 1
        seq_steps[seqstep].configure({'eventcode': 198, 'delta_beam': 0,
                                'fiducial': 0, 'comment': 'DAQ Readout'})
        # Clear other sequence steps 
        seqstep += 1
        sequencer.sequence_length.put(seqstep)
        for i in range(seqstep, 20):
            seq_steps[i].clear()

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

        """
        # time.sleep(3) / a leftover from original script
        # Create descriptive message
        comment = comment or ''
        # Start recording
        try:
            logger.info("Starting DAQ run, -> record=%s", record)
            daq.begin(events=events, record=record)
            time.sleep(2)  # Wait for the DAQ to get spinnign before sending events
            logger.debug("Starting EventSequencer ...")
            sequencer.start()
            time.sleep(1)
            # Post to ELog if desired
            runnum = daq._control.runnumber()
            info = [runnum, comment, events, self.current_rate]
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

    def get_mesh_voltage(self):
        """
        Get the current power supply voltage
        """
        return self.mesh_raw.get()

    def set_mesh_voltage(self, sigIn, wait=True, do_print=True):
        """
        Set voltage on power supply to an absolute value

        Parameters
        ----------
        sigIn: int or float
            Power supply voltage in Volts
        """
        if do_print:
            print('Setting voltage...')
        sigInScaled = sigIn / self.SCALE # in V
        self.mesh_raw.put(sigInScaled)
        if wait:
            time.sleep(2.5)
        finalVolt = self.mesh_raw.get()
        finalVoltSupply = finalVolt*self.SCALE
        if do_print:
            print('Power Supply Setpoint: %s V' % sigIn)
            print('Power Supply Voltage: %s V' % finalVoltSupply)

    def set_rel_mesh_voltage(self, deltaVolt, wait=True, do_print=True):
        """
        Increase/decrease power supply voltage by a specified amount

        Parameters
        ----------
        deltaVolt: int or float
            Amount to increase/decrease voltage (in Volts) from
            its current value. Use positive value to increase
            and negative value to decrease
        """
        if do_print:
            print('Setting voltage...')
        curr_set = self.mesh_raw.get_setpoint()
        curr_set_supply = curr_set * self.SCALE
        if do_print:
            print('Previous Power Supply Setpoint: %s V' % curr_set_supply)
        new_voltage = round(curr_set_supply + deltaVolt)
        self.set_mesh_voltage(new_voltage, wait=wait, do_print=do_print)

    def tweak_mesh_voltage(self, deltaVolt):
        """
        Continuously Increase/decrease power supply voltage by
        specifed amount using arrow keys

        Parameters
        ----------
        deltaVolt: int or float
            Amount to change voltage (in Volts) from its current value at
            each step. After calling with specified step size, use arrow keys
            to keep changing
        ^C:
            exits tweak mode
        """
        print('Use arrow keys (left, right) to step voltage (-, +)')
        while True:
            key = key_press.get_input()
            if key in ('q', None):
                return
            elif key == key_press.arrow_right:
                self.set_rel_mesh_voltage(deltaVolt, wait=False,
                                          do_print=False)
            elif key == key_press.arrow_left:
                self.set_rel_mesh_voltage(-deltaVolt, wait=False,
                                          do_print=False)


post_template = """\
Run Number: {} {}

Acquiring {} events at {}

"""

