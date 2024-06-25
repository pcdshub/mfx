import logging
from hutch_python.utils import safe_load

logger = logging.getLogger(__name__)

with safe_load('quiet errors'):
    from IPython import get_ipython
    ip = get_ipython()
    ip.InteractiveTB.set_mode(mode="Minimal")

with safe_load('sequencer'):
    from pcdsdevices.sequencer import EventSequencer
    sequencer = EventSequencer('ECS:SYS0:7', name='mfx_sequencer')
    mfx_sequencer = sequencer

with safe_load('rayonix utils'):
    from mfx.rayonix import Rayonix
    rayonix = Rayonix(mfx_sequencer)
    mfx_rayonix = rayonix

with safe_load('transfocator'):
    from transfocate import Transfocator
    tfs = Transfocator("MFX:LENS", name='MFX Transfocator')
    mfx_tfs = tfs

with safe_load('mfx_prefocus'):
    from .devices import XFLS
    mfx_prefocus = XFLS('MFX:DIA:XFLS', name='mfx_prefocus')

with safe_load('Scan PVs'):
    from mfx.db import scan_pvs
    scan_pvs.enable()

with safe_load('beam_suspender'):
    from mfx.suspenders import BeamEnergySuspendFloor
    beam_suspender = BeamEnergySuspendFloor(0.6)

with safe_load('macros'):
    from mfx.macros import *
    mfx_timing = MFX_Timing(sequencer)

with safe_load('Droplet_on_Demand'):
    # from mfx.mfxDOD import *
    from mfx.mfx_dod import *

with safe_load('delay_scan'):
    from mfx.delay_scan import *

with safe_load('autorun'):
    from mfx.autorun import *

with safe_load('attenuator_scan'):
    from mfx.attenuator_scan import *

with safe_load('focus_scan'):
    from mfx.focus_scan import *

with safe_load('plans'):
    from mfx.plans import *

with safe_load('Mesh Voltage Control'):
    from pcdsdevices.analog_signals import Mesh
    mesh = Mesh('MFX:USR', 0, 1)

with safe_load('transfocator_scan'):
    from mfx.transfocator_scan import *

with safe_load('detector_image'):
    from mfx.detector_image import *

with safe_load("drift_correct"):
    from mfx.timetool import *

with safe_load('bash_utilities'):
    from mfx.bash_utilities import *
    cl = cl()

with safe_load('cctbx'):
    from mfx.cctbx import *
    cctbx = cctbx()

with safe_load('yano-kern_code'):
    from mfx.yano import *
    yano = yano()

with safe_load("laser wp power"):
    from pcdsdevices.lxe import LaserEnergyPositioner
    from hutch_python.utils import get_current_experiment
    from pcdsdevices.device import Component as Cpt
    from pcdsdevices.epics_motor import Newport

    # Hack the LXE class to make it work with Newports
    class LXE(LaserEnergyPositioner):
        motor = Cpt(Newport, "")

    lxe_calib_file = (
        f"/reg/neh/operator/mfxopr/experiments/{get_current_experiment('mfx')}/wpcalib"
    )
    try:
        lxe = LXE("MFX:LAS:MMN:08", calibration_file=lxe_calib_file, name="lxe")
    except OSError:
        print(f"Could not load file: {lxe_calib_file}")
        raise FileNotFoundError

with safe_load('FS45 lxt & lxt_ttc'):
    import logging
    logging.getLogger('pint').setLevel(logging.ERROR)

    from pcdsdevices.device import ObjectComponent as OCpt
    from pcdsdevices.lxe import LaserTiming
    from pcdsdevices.pseudopos import SyncAxis
    from pcdsdevices.device_types import DelayNewport
    from mfx.db import mfx_txt

    lxt = LaserTiming('LAS:FS45', name='lxt')
    txt = mfx_txt
    # <we are missibng the compensation 'motor'>

    class LXTTTC(SyncAxis):
        lxt = OCpt(lxt)
        txt = OCpt(txt)

        tab_component_names = True
        scales = {'txt': -1}
        warn_deadband = 5e-14
        fix_sync_keep_still = 'lxt'
        sync_limits = (-10e-6, 10e-6)

    lxt_ttc = LXTTTC('', name='lxt_ttc')

with safe_load('add laser motor groups'):
    from pcdsdevices.device_types import Newport
    from pcdsdevices.device_types import DelayNewport
    from pcdsdevices.usb_encoder import UsDigitalUsbEncoder
    from mfx.db import mfx_lxt_fast1
    lxt_fast=mfx_lxt_fast1

    #opa_comp = Newport('MFX:LAS:MMN:01', name='opa_comp') # linear motor for OPA compressor
                                                          # this is the timetool compensationn stage. You might want this one
    class las():
        #opa_comp = opa_comp # waveplate for the main compressor
        # Time tool motors
        # initialize motors here for tab completion if wanted
        with safe_load('add more laser motors'):
            lasmot2 = Newport('MFX:LAS:MMN:02', name='lasmot2') # give descriptions later
            lasmot3 = Newport('MFX:LAS:MMN:03', name='lasmot3')
            lasmot4 = Newport('MFX:LAS:MMN:04', name='lasmot4')
            lasmot5 = Newport('MFX:LAS:MMN:05', name='lasmot5')
            lasmot7 = Newport('MFX:LAS:MMN:07', name='lasmot7')
            lasmot8 = Newport('MFX:LAS:MMN:08', name='lasmot8')
            lens_v = Newport('MFX:LAS:MMN:09', name='lens_v')
            lens_f = Newport('MFX:LAS:MMN:10', name='lens_f')
            lens_h = Newport('MFX:LAS:MMN:11', name='lens_h')
            lens_g = Newport('MFX:LAS:MMN:12', name='lens_g')

        with safe_load('Fast delay encoders'):
            lxt_fast1_enc = UsDigitalUsbEncoder('MFX:USDUSB4:01:CH0', name='lxt_fast_enc1', linked_axis=mfx_lxt_fast1)

        # timing virtual motors for x-ray laser delay adjustment
        lxt = lxt # virtual motor that moves the laser timing system phase shifter
        txt = txt
        lxt_ttc = lxt_ttc
        lxt_fast1 = mfx_lxt_fast1

#aliases added by Leland 071523
with safe_load('Make Aliases'):
    from mfx.db import mfx_attenuator as att
    from mfx.db import mfx_dg1_slits as s1
    from mfx.db import mfx_dg2_upstream_slits as s2
    from mfx.db import mfx_dg2_midstream_slits as s3
    from mfx.db import mfx_dg2_downstream_slits as s4
    from mfx.db import mfx_dia_pim as yag0
    from mfx.db import mfx_dg1_pim as yag1
    from mfx.db import mfx_dg2_pim as yag2
    from mfx.db import at1l0 as fat1
    from mfx.db import at2l0 as fat2
    from mfx.db import mec_yag0_mfx as mec_yag0
    from mfx.db import mfx_dia_ipm as ipm0
    from mfx.db import mfx_dg1_ipm as ipm1
    from mfx.db import mfx_dg2_ipm as ipm2
    from mfx.db import mfx_pulsepicker as pp
    #from mfx.db import mfx_prefocus as crl1
    crl1=mfx_prefocus
    from mfx.db import mfx_tfs as tfs
    from mfx.db import um6_ipm as xcs_yag1
    from mfx.db import hx2_slits as xpp_s1
    from mfx.db import mfx_von_hamos_6crystal as vh
    import numpy as np
    from importlib import reload
    from mfx.transfocator_scan import *
    from mfx.db import mfx_atm as tt
    lens_v=las.lens_v
    lens_h=las.lens_h
    lens_f=las.lens_f
