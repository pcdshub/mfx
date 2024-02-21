import os
import time
import os.path
import logging
import subprocess

import numpy as np

from mfx.db import daq, sequencer, rayonix
from pcdsdevices.sequencer import EventSequencer
from pcdsdevices.evr import Trigger

from mfx.db import sequencer


ray3 = [213,1,0,0]
ray2 = [212,1,0,0]
ray1 = [211,1,0,0]
ray_readout = [210,1,0,0]
pp_trig = [197,0,0,0]
daq_readout = [198,0,0,0]
wait1 = [0,1,0,0]
zeros = [0,0,0,0]
laser_on = [203,0,0,0]
laser_off = [204,0,0,0]

_sync_markers = {0.5:0, 1:1, 5:2, 10:3, 30:4, 60:5, 120:6, 360:7}

class User:
    """Generic User Object"""
    seq = sequencer
    #seq = EventSequencer('ECS:SYS0:9')

    def set_30Hz(self):
        sync_mark = _sync_markers[60]
        self.seq.sync_marker.put(sync_mark)
        
        sequence = []
        for ii in range(15):
            sequence.append(zeros)
        self.seq.sequence.put_seq(sequence)
        time.sleep(1)

        sequence = []
        sequence.append(ray3)
        sequence.append(ray2)
        sequence.append(pp_trig)
        sequence.append(ray1)
        sequence.append(ray_readout)
        sequence.append(daq_readout)
        
        self.seq.sequence.put_seq(sequence)
        return

    def set_120Hz(self):
        sync_mark = _sync_markers[60]
        self.seq.sync_marker.put(sync_mark)
        
        sequence = []
        for ii in range(15):
            sequence.append(zeros)
        self.seq.sequence.put_seq(sequence)
        time.sleep(1)

        sequence = []
        sequence.append(ray3)
        sequence.append(daq_readout)
        sequence.append(ray2)
        sequence.append(daq_readout)
        sequence.append(ray1)
        sequence.append(daq_readout)
        sequence.append(ray_readout)
        sequence.append(daq_readout)

        self.seq.sequence.put_seq(sequence)
        return

    def set_30Hz_laser(self, on=1, off=1):
        sync_mark = _sync_markers[60]
        self.seq.sync_marker.put(sync_mark)
        
        sequence = []
        for ii in range(500):
            sequence.append(zeros)
        self.seq.sequence.put_seq(sequence)
        time.sleep(1)
        
        sequence = []
        for ii in range(on):
            sequence.append(ray3)
            sequence.append(laser_off)
            sequence.append(ray2)
            sequence.append(laser_off)
            sequence.append(pp_trig)
            sequence.append(laser_off)
            sequence.append(ray1)
            sequence.append(laser_off)
            sequence.append(ray_readout)
            sequence.append(laser_on)
            sequence.append(daq_readout)

        for ii in range(off):
            sequence.append(ray3)
            sequence.append(laser_off)
            sequence.append(ray2)
            sequence.append(laser_off)
            sequence.append(pp_trig)
            sequence.append(laser_off)
            sequence.append(ray1)
            sequence.append(laser_off)
            sequence.append(ray_readout)
            sequence.append(laser_off)
            sequence.append(daq_readout)

        self.seq.sequence.put_seq(sequence)
        return

    def set_120Hz_laser(self, on=1, off=1):
        sync_mark = _sync_markers[60]
        self.seq.sync_marker.put(sync_mark)
        
        sequence = []
        for ii in range(500):
            sequence.append(zeros)
        self.seq.sequence.put_seq(sequence)
        time.sleep(1)

        sequence = []
        for ii in range(on):
            sequence.append(ray3)
            sequence.append(laser_on)
            sequence.append(daq_readout)
            sequence.append(ray2)
            sequence.append(laser_on)
            sequence.append(daq_readout)
            sequence.append(ray1)
            sequence.append(laser_on)
            sequence.append(daq_readout)
            sequence.append(ray_readout)
            sequence.append(laser_on)
            sequence.append(daq_readout)

        for ii in range(off):
            sequence.append(ray3)
            sequence.append(laser_off)
            sequence.append(daq_readout)
            sequence.append(ray2)
            sequence.append(laser_off)
            sequence.append(daq_readout)
            sequence.append(ray1)
            sequence.append(laser_off)
            sequence.append(daq_readout)
            sequence.append(ray_readout)
            sequence.append(laser_off)
            sequence.append(daq_readout)
        
        self.seq.sequence.put_seq(sequence)
        return
