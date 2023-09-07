from ophyd.status import wait as status_wait
from mfx.db import (mfx_reflaser,
                    mfx_dg1_slits,
                    mfx_dg1_wave8_motor,
                    mfx_dg2_upstream_slits,
                    mfx_dg2_midstream_slits,
                    mfx_dg2_downstream_slits)
import time
def laser_in(wait=False, timeout=10):
    """
    Insert the Reference Laser and clear the beampath

    Parameters
    ----------
    wait: bool, optional
        Wait and check that motion is properly completed

    timeout: float, optional
        Time to wait for motion completion if requested to do so

    Operations
    ----------
    * Insert the Reference Laser
    * Set the Wave8 out (35 mm)
    * Set the DG1 slits to 6 mm x 6 mm
    * Set the DG2 upstream slits to 6 mm x 6 mm
    * Set the DG2 midstream slits to 1 mm x 1 mm
    * Set the DG2 downstream slits to 1 mm x 1 mm
    """
    # Command motion and collect status objects
    ref = mfx_reflaser.insert(wait=False)
    w8 = mfx_dg1_wave8_motor.move(35, wait=False)
    dg1 = mfx_dg1_slits.move(6., wait=False)
    dg2_us = mfx_dg2_upstream_slits.move(6., wait=False)
    dg2_ms = mfx_dg2_midstream_slits.move(1., wait=False)
    dg2_ds = mfx_dg2_downstream_slits.move(1., wait=False)
    # Combine status and wait for completion
    if wait:
        status_wait(ref & w8 & dg1 & dg2_us & dg2_ms & dg2_ds,
                    timeout=timeout)


def laser_out(wait=False, timeout=10):
    """
    Remove the Reference Laser and configure the beamline

    Parameters
    ----------
    wait: bool, optional
        Wait and check that motion is properly completed

    timeout: float, optional
        Time to wait for motion completion if requested to do so

    Operations
    ----------
    * Remove the Reference Laser
    * Set the Wave8 Target 3 In (5.5 mm)
    * Set the DG1 slits to 0.7 mm x 0.7 mm
    * Set the DG2 upstream slits to 0.7 mm x 0.7 mm
    * Set the DG2 midstream slits to 0.7 mm x 0.7 mm
    * Set the DG2 downstream slits to 0.7 mm x 0.7 mm
    """
    # Command motion and collect status objects
    ref = mfx_reflaser.remove(wait=False)
    w8 = mfx_dg1_wave8_motor.move(5.5, wait=False)
    dg1 = mfx_dg1_slits.move(0.7, wait=False)
    dg2_us = mfx_dg2_upstream_slits.move(0.7, wait=False)
    dg2_ms = mfx_dg2_midstream_slits.move(0.7, wait=False)
    dg2_ds = mfx_dg2_downstream_slits.move(0.7, wait=False)
    # Combine status and wait for completion
    if wait:
        status_wait(ref & w8 & dg1 & dg2_us & dg2_ms & dg2_ds,
                    timeout=timeout)


def mfxslits(pos):
    """Set all the slits to specific position"""
    dg1 = mfx_dg1_slits.move(pos, wait=False)
    dg2_us = mfx_dg2_upstream_slits.move(pos, wait=False)
    dg2_ms = mfx_dg2_midstream_slits.move(pos, wait=False)
    dg2_ds = mfx_dg2_downstream_slits.move(pos, wait=False)

class MFX_Timing:
    def __init__(self,sequencer=None):
        if sequencer==None:
            from mfx.db import sequencer as seq
            self.seq=seq
        else:
            self.seq = sequencer
        self.evt_code_names = ['wait','pp_trig','daq_readout',
                               'laser_on','laser_off',
                               'ray_readout','ray1','ray2','ray3']
        self.evt_code_ids = [0,197,198,
                             203,204,
                             210,211,212,213]
        #self.ray3 = [213,1,0,0]
        #self.ray2 = [212,1,0,0]
        #self.ray1 = [211,1,0,0]
        #self.ray_readout = [210,1,0,0]
        #self.pp_trig = [197,0,0,0]
        #self.daq_readout = [198,0,0,0]
        #self.wait1 = [0,1,0,0]
        #self.zeros = [0,0,0,0]
        #self.laser_on = [203,0,0,0]
        #self.laser_off = [204,0,0,0]
        self.sync_markers = {0.5:0, 1:1, 5:2, 10:3, 30:4, 60:5, 120:6, 360:7}
    def _step(self, evt_code_name=None, delta_beam=0):
        try:
            evt_code_id = self.evt_code_ids[self.evt_code_names.index(evt_code_name)]
            return [evt_code_id, delta_beam, 0, 0]
        except:
            print('event sequencer step not recognized.')
    def set_30hz(self):
        sync_mark = self.sync_markers[30]
        self.seq.sync_marker.put(sync_mark)
        sequence = []
        for ii in range(15):
            sequence.append(self._step('wait',0))
        self.seq.sequence.put_seq(sequence)
        time.sleep(1)
        sequence = []
        sequence.append(self._step('laser_on',0))
        sequence.append(self._step('daq_readout',0))
        sequence.append(self._step('ray3',1))
        sequence.append(self._step('ray_readout',1))
        sequence.append(self._step('pp_trigger',0))
        sequence.append(self._step('ray1',1))
        sequence.append(self._step('ray2', 1))
        self.seq.sequence.put_seq(sequence)
        self.seq.start()
        return
    def set_30hz_laser(self, laser_evt_list=None):
        sync_mark = self.sync_markers[30]
        self.seq.sync_marker.put(sync_mark)
        sequence = []
        for ii in range(15):
            sequence.append(self._step('wait',0))
        self.seq.sequence.put_seq(sequence)
        time.sleep(1)
        sequence_block = []
        sequence_block.append(self._step('laser_on', 0))
        sequence_block.append(self._step('daq_readout', 0))
        sequence_block.append(self._step('ray3', 1))
        sequence_block.append(self._step('ray_readout', 1))
        sequence_block.append(self._step('pp_trigger', 0))
        sequence_block.append(self._step('ray1', 1))
        sequence_block.append(self._step('ray2', 1))
        try:
            sequence = []
            for evt in laser_evt_list:
                sequence.extend(sequence_block)
                sequence.append(evt)
        except:
            sequence = sequence_block
        self.seq.sequence.put_seq(sequence)
        self.seq.start()
        print(sequence)
        return    
    def set_20hz(self):
        sync_mark = self.sync_markers[60]
        self.seq.sync_marker.put(sync_mark)
        sequence = []
        for ii in range(15):
            sequence.append(self._step('wait',0))
        self.seq.sequence.put_seq(sequence)
        time.sleep(1)
        sequence = []
        sequence.append(self._step('ray3',1))
        sequence.append(self._step('ray2',1))
        sequence.append(self._step('ray_readout',1))
        sequence.append(self._step('pp_trig',1))
        sequence.append(self._step('ray2',0))
        sequence.append(self._step('ray1',1))
        sequence.append(self._step('ray_readout',1))
        sequence.append(self._step('daq_readout',0))
        self.seq.sequence.put_seq(sequence)
        self.seq.start()
        return 
    def set_120hz(self):
        sync_mark = self.sync_markers[60]
        self.seq.sync_marker.put(sync_mark)
        sequence = []
        for ii in range(15):
            sequence.append(self._step('wait',0))
        self.seq.sequence.put_seq(sequence)
        time.sleep(1)
        sequence = []
        sequence.append(self._step('ray3',1))
        sequence.append(self._step('daq_readout',0))
        sequence.append(self._step('ray2',1))
        sequence.append(self._step('daq_readout',0))
        sequence.append(self._step('ray1',1))
        sequence.append(self._step('daq_readout',0))
        sequence.append(self._step('ray_readout',1))
        sequence.append(self._step('daq_readout',0))
        self.seq.sequence.put_seq(sequence)
        self.seq.start()
        return


def quote():
    import json,random
    from os import path
    _path = path.dirname(__file__)
    _path = path.join(_path,"/cds/home/d/djr/scripts/quotes.json")
    _quotes = json.loads(open(_path, 'rb').read())
    _quote = _quotes[random.randint(0,len(_quotes)-1)]
    _res = {'quote':_quote['text'],"author":_quote['from']}
    return _res


def inspirational_autorun(sample='?', run_length=300, record=True, runs=5, inspire=False):
    """
    Try to automate runs.... With quotes

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

    Operations
    ----------

    """

    from time import sleep
    from mfx.db import daq, elog, pp
    import sys
    try:
        for i in range(runs):
            print(f"Run Number {daq.run_number() + 1} Running {sample}......{quote()['quote']}")
            daq.begin(duration = run_length, record = record, wait = True, end_run = True)
            if inspire:
                elog.post(f"Running {sample}......{quote()['quote']}", run=(daq.run_number()))
            else:
                elog.post(f"Running {sample}", run=(daq.run_number()))
            sleep(5)
        pp.close()
        daq.disconnect()

    except KeyboardInterrupt:
        print(f"[*] Stopping Run {daq.run_number()} and exiting...",'\n')
        pp.close()
        daq.disconnect()
        sys.exit()


def attenuator_scan_separate_runs(events=240, record=False, config=True, transmissions=[0.01,0.02,0.03]):
    """
    Runs through attenuator conditions and records each as an individual run

    Parameters
    ----------
    events: int, optional
        number of events. default 240

    record: bool, optional
        set True to record

    transmissions: list of floats, optional
        list of transmissions to run through. default [0.01,0.02,0.03]

    Operations
    ----------

    """
    from time import sleep
    from mfx.db import daq, att, pp

    pp.open()
    for i in transmissions:
        att(i)
        time.sleep(3)
        daq.begin(events=events,record=record,wait=True, use_l3t=False)
        daq.end_run()
    pp.close()
    daq.disconnect()


def attenuator_scan_single_run(events=240, record=False, transmissions=[0.01,0.02,0.03]):
    """
    Runs through attenuator conditions and records them all as one continuous run

    Parameters
    ----------
    events: int, optional
        number of events. default 240

    record: bool, optional
        set True to record

    transmissions: list of floats, optional
        list of transmissions to run through. default [0.01,0.02,0.03]

    Operations
    ----------

    """
    from time import sleep
    from mfx.db import daq, att, pp

    daq.end_run()
    daq.disconnect()
    try:
        pp.open()
        daq.configure(record=record)
        time.sleep(3)
        for i in transmissions:
            att(i,wait=True)
            time.sleep(3)
            daq.begin(events=events,record=record,wait=True, use_l3t=False)
    finally:
        daq.end_run()
        pp.close()
        daq.disconnect()

def focus_scan(camera):
    """
    Runs through transfocator Z to find the best focus

    Parameters
    ----------
    camera: str, required
        camera where you want to focus

    Examples:
    mfx dg1 yag is MFX:DG1:P6740
    mfx dg2 yag is MFX:DG2:P6740
    mfx dg3 yag is MFX:GIGE:02:IMAGE1

    Operations
    ----------

    """
    # cd /reg/g/pcds/pyps/apps/hutch-python/mfx/mfx
    # from mfx.transfocator_scan import *
    import transfocator_scan
    import numpy as np
    from mfx.db import tfs

    trf_align = transfocator_scan.transfocator_aligner(camera)
    trf_pos = np.arange(1,299,1)
    trf_align.scan_transfocator(tfs.translation,trf_pos,1)
