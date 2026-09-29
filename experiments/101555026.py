import os
import time
import os.path
import logging
import subprocess

import numpy as np

from mfx.devices import LaserShutter
from mfx.db import daq, sequencer
from ophyd.status import wait as status_wait
from pcdsdevices.sequencer import EventSequencer
# WAIT A WHILE FOR THE DAQ TO START

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
#opo_shutter = LaserShutter('MFX:USR:ao1:6', name='opo_shutter')

# Trigger objects
#pacemaker = Trigger('MFX:LAS:EVR:01:TRIG4', name='pacemaker_trigger')
#inhibit = Trigger('MFX:LAS:EVR:01:TRIG6', name='inhibit_trigger')
# pacemaker = Trigger('MFX:DG2:BMMON:EVR:TRIG4', name='pacemaker_trigger')
# inhibit = Trigger('MFX:DG2:BMMON:EVR:TRIG6', name='inhibit_trigger')

# Laser parameter
opo_time_zero = 743935+460
base_inhibit_delay = 500000
min_evr_delay = 9280 #may depend on evr. min_evr_delay = 0 ticks for code 40

###########################
# Configuration Functions #
###########################

class User:
    """Generic User Object"""
#    opo_shutter = opo_shutter
#    evo_shutter1 = evo_shutter1#    evo_shutter2 = evo_shutter2
#    evo_shutter3 = evo_shutter3
#    sequencer = sequencer
#    inhibit = inhibit
#    pacemaker = pacemaker
#    evo = evo
    def __init__(self):
        self.delay = None
        self.sync_markers = {
            0.5: 0,
            1: 1,
            5: 2,
            10: 3,
            30: 4,
            60: 5,
            120: 6,
            360: 7
            }
    def int_to_bool_array(self,n, length=4):
        return [bool((n >> i) & 1) for i in range(length)]

    def set_arbitrary_laser(self, number_of_shots=11, sync_marker=10):
        seq = EventSequencer('ECS:SYS0:7', name='mfx_sequencer')
        shot_label_evts = [205, 206, 207, 208, 209, 210, 211, 212]
        sequencer_steps = [[203, 1, 0, 0, 'inhibit_off']]
    
        for idx in range(number_of_shots):
            sequencer_steps.append([204,1,0,0,f'shot_{idx}'])
            shot_label_idx = self.int_to_bool_array(idx, length=8)  # Get boolean array
        
            for i, is_active in enumerate(shot_label_idx):
                if is_active:  # Only add if this bit is set
                    sequencer_steps.append([shot_label_evts[i],0,0,0])
        seq.sync_marker.put(self.sync_markers[sync_marker])
        seq.sequence.put_seq(sequencer_steps)
        seq.start()

        return 
