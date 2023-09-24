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
# Removing wave8 dg1 until target positions have been fixed
#    w8 = mfx_dg1_wave8_motor.move(35, wait=False)
    dg1 = mfx_dg1_slits.move(6., wait=False)
    dg2 = mfx_dg2_ipm.target.remove()
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
# Removing dg1 wave8 movement for now, until wave8 target positions have been fixed
#    w8 = mfx_dg1_wave8_motor.move(5.5, wait=False)
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
        self.evt_code = {
            'wait':0,
            'pp_trig':197,
            'daq_readout':198,
            'laser_on':203,
            'laser_off':204,
            'ray_readout':210,
            'ray1':211,
            'ray2':212,
            'ray3':213,
        }
        self.sync_markers = {0.5:0, 1:1, 5:2, 10:3, 30:4, 60:5, 120:6, 360:7}
        self.sequence = []
    def _seq_step(self, evt_code_name=None, delta_beam=0):
        try:
            return [self.evt_code[evt_code_name], delta_beam, 0, 0]
        except:
            print('Error: event sequencer step not recognized.')
    def _seq_init(self, sync_mark=30):
        self.seq.sync_marker.put(self.sync_markers[sync_mark])
        sequence = []
        for ii in range(15):
            sequence.append(self._step('wait', 0))
        self.seq.sequence.put_seq(sequence)
        time.sleep(1)
    def _seq_put(self, steps):
        for step in steps:
            self.sequence.append(self._step(step[0], step[1]))
        self.seq.sequence.put_seq(self.sequence)
    def set_30hz(self):
        self._seq_init(sync_mark=30)
        steps = [['laser_on',0],
                 ['daq_readout',0],
                 ['ray3',1],
                 ['ray_readout',1],
                 ['pp_trigger',0],
                 ['ray1',1],
                 ['ray2', 1]]
        self._seq_put(steps)
        self.seq.start()
        return
    def set_30hz_laser(self, laser_evt_list=None):
        self._seq_init(sync_mark=30)
        steps = [['laser_on', 0],
                 ['daq_readout', 0],
                 ['ray3', 1],
                 ['ray_readout', 1],
                 ['pp_trigger', 0],
                 ['ray1', 1],
                 ['ray2', 1]]
        try:
            for laser_evt in laser_evt_list:
                block = steps
                block.append(laser_evt)
                self._seq_put(block)
        except:
            self._seq_put(steps)
        self.seq.start()
        print(self.sequence)
        return    
    def set_20hz(self):
        self._seq_init(sync_mark=60)
        steps = [['ray3',1],
                 ['ray2',1],
                 ['ray_readout',1],
                 ['pp_trig',1],
                 ['ray2',0],
                 ['ray1', 1],
                 ['ray_readout',1],
                 ['daq_readout',0]]
        self._seq_put(steps)
        self.seq.start()
        return
    def set_120hz(self):
        self._seq_init(sync_mark=60)
        steps = [['ray3', 1],
                 ['daq_readout',0],
                 ['ray2',1],
                 ['daq_readout',0],
                 ['ray1',1],
                 ['daq_readout',0],
                 ['ray_readout', 1],
                 ['daq_readout', 0]]
        self._seq_put(steps)
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


def autorun(sample='?', run_length=300, record=True, runs=5, inspire=False, delay=5):
    """
    Automate runs.... With optional quotes

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
            if record:
                if inspire:
                    elog.post(f"Running {sample}......{quote()['quote']}", run=(daq.run_number()))
                else:
                    elog.post(f"Running {sample}", run=(daq.run_number()))
            sleep(delay)
        pp.close()
        daq.end_run()
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

def focus_scan(camera, start=1, end=299, step=1):
    """
    Runs through transfocator Z to find the best focus

    Parameters
    ----------
    camera: str, required
        camera where you want to focus

    step: int, optional
	step size of transfocator movements

    start: int, optional
	starting transfocator position

    end: int, optional
	final transfocator position

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
    trf_pos = np.arange(start, end, step)
    trf_align.scan_transfocator(tfs.translation,trf_pos,1)
