from ophyd.status import wait as status_wait
from mfx.db import (mfx_reflaser,
                    mfx_tfs,
                    mfx_dg1_ipm,
                    mfx_dg2_ipm,
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
    tfs = mfx_tfs.remove_all()
    dg1_ipm=mfx_dg1_ipm.target.remove()
    dg2_ipm=mfx_dg2_ipm.target.remove()
    dg1 = mfx_dg1_slits.move(6., wait=False)
    dg2_us = mfx_dg2_upstream_slits.move(6., wait=False)
    dg2_ms = mfx_dg2_midstream_slits.move(1., wait=False)
#    dg2_ds = mfx_dg2_downstream_slits.move(1., wait=False)
    # Combine status and wait for completion
    if wait:
        status_wait(ref & dg1 & dg2_us & dg2_ms,
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
#    dg2_ds = mfx_dg2_downstream_slits.move(0.7, wait=False)
    # Combine status and wait for completion
    if wait:
        status_wait(ref & w8 & dg1 & dg2_us & dg2_ms ,
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
        self.sequence = []
        sequence = []
        for ii in range(15):
            sequence.append(self._seq_step('wait', 0))
        self.seq.sequence.put_seq(sequence)
        time.sleep(1)
    
    def _seq_put(self, steps):
        for step in steps:
            self.sequence.append(self._seq_step(step[0], step[1]))
        self.seq.sequence.put_seq(self.sequence)

    def _seq_30hz(self):
        # make sure daq_readout is penultimate event (set_30hz_laser assumes it)
        steps = [['ray1', 1],
                 ['pp_trig', 0],
                 ['ray2', 1],
                 ['ray_readout', 1],
                 ['daq_readout', 0],
                 ['ray3', 1]]
        return steps

    def _seq_20hz(self):
        steps = [['ray3', 1],
                 ['pp_trig', 0],
                 ['ray2', 1],
                 ['ray1', 1],
                 ['daq_readout', 0],
                 ['ray_readout', 3]]
        return steps
    
    def set_30hz(self):
        self._seq_init(sync_mark=30)
        self._seq_put(self._seq_30hz())
        self.seq.start()
        return
    
    def set_30hz_laser(self, laser_evt_list=None):
        self._seq_init(sync_mark=30)
        try:
            for laser_evt in laser_evt_list:
                sequence = self._seq_30hz()
                block = sequence[:-1]
                block.append(laser_evt)
                block.append(sequence[-1])
                self._seq_put(block)
        except:
            self._seq_put(self._seq_30hz())
        self.seq.start()
        print(self.sequence)
        return    
    
    def set_20hz(self):
        self._seq_init(sync_mark=60)
        self._seq_put(self._seq_20hz())
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


def get_exp():
    import requests
    ws_url = "https://pswww.slac.stanford.edu/ws/lgbk"
    resp = requests.get(
        ws_url + "/lgbk/ws/activeexperiment_for_instrument_station",
        {"instrument_name": 'mfx', "station": 0})
    exp = resp.json().get("value", {}).get("name")
    return exp
