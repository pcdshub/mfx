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
    sequencer2 = EventSequencer('ECS:SYS0:12', name='mfx_sequencer_spare')
    mfx_sequencer_spare = sequencer2

# with safe_load('rayonix utils'):
#     from mfx.rayonix import Rayonix
#     rayonix = Rayonix(mfx_sequencer)
#     mfx_rayonix = rayonix

with safe_load('mfx_transfocator'):
    from tfs.transfocator import Transfocator
    tfs = Transfocator("MFX:LENS", name='MFX Transfocator')
    from tfs import utils as tfs_utils
    from tfs.transfocator_scan import *
    from tfs import tfs_plots

with safe_load('mfx_prefocus'):
    from .devices import XFLS
    mfx_prefocus = XFLS('MFX:DIA:XFLS', name='mfx_prefocus')

with safe_load('Scan PVs'):
    from mfx.db import scan_pvs
    scan_pvs.enable()

# with safe_load('beam_suspender'):
#     from mfx.suspenders import BeamEnergySuspendFloor
#     beam_suspender = BeamEnergySuspendFloor(0.6)

with safe_load('macros'):
    from mfx.macros import *

with safe_load('MFX_Timing'):
    from mfx.mfx_timing import *
    mfx_timing = MFXTiming(sequencer)

with safe_load('delay_scan'):
    from mfx.delay_scan import *

with safe_load('autorun'):
    from mfx.autorun import *

with safe_load('attenuator_scan'):
    from mfx.attenuator_scan import *

# with safe_load('focus_scan'):
#     from mfx.focus_scan import *

with safe_load('plans'):
    from mfx.plans import *

with safe_load('Mesh Voltage Control'):
    from pcdsdevices.analog_signals import Mesh
    mesh = Mesh('MFX:USR', 0, 1)

# with safe_load('detector_image'):
#     from mfx.detector_image import *

with safe_load("drift_correct"):
    from mfx.timetool import *

with safe_load('bash_utilities'):
    from mfx.bash_utilities import *
    bs = BashUtilities()

with safe_load('cctbx'):
    from mfx.cctbx import *
    cctbx = cctbx()

with safe_load('OM'):
    from mfx.om import *
    om = OM()

with safe_load('xas'):
    import mfx.xas as xas

with safe_load('optimize'):
    from mfx.optimize.errors import *
    from mfx.optimize.plots import *
    from mfx.optimize.type_checking import *
    from mfx.optimize.user_select import *
    from mfx.optimize.constraints import *
    from mfx.optimize.beam import *
    from mfx.optimize.vernier_calibration import *
    beam = Beam()
    vernier_calib = VernierCalibration()

with safe_load('vernier'):
    from mfx.vernier import *
    vernier = Vernier()

with safe_load('beam_status'):
    from mfx.optimize.beam_status import *
    beam_status = BeamCheck()

with safe_load('yano-kern_code'):
    from mfx.yano import *
    yano = Yano()

with safe_load('Droplet_on_Demand_Colliding_Droplets'):
    from dod.codi import *
    codi = CoDI()

with safe_load('Droplet_on_Demand'):
    from dod.dod import *
    dod = DoD(modules = 'codi')

with safe_load('Debugging Scripts'):
    from mfx.debug import *
    debug = Debug()

with safe_load('XLJ'):
    from pcdsdevices.jet import BeckhoffJet
    xlj = BeckhoffJet('MFX:LJH', name='xlj')

with safe_load('XLJ_Fast'):
    from mfx.xlj_fast import *
    from pcdsdevices.epics_motor import IMS
    xlj_fast_rx = IMS("MFX:HRA:MMS:02", name="xlj_fast_rx")
    xlj_fast_ry = IMS("MFX:HRA:MMS:04", name="xlj_fast_ry")
    xlj_fast_rz = IMS("MFX:HRA:MMS:03", name="xlj_fast_rz")
    xlj_fast_x = BypassPositionCheck("MFX:LJH:JET:X", name="xlj_fast_x")
    xlj_fast_y = BypassPositionCheck("MFX:LJH:JET:Y", name="xlj_fast_y")
    xlj_fast_z = BypassPositionCheck("MFX:LJH:JET:Z", name="xlj_fast_z")

with safe_load('DCCM'):
    from mfx.dccm import DCCM
    dccm = DCCM(name='DCCM')

with safe_load('Notch_Scan'):
    from mfx.notch_scan import *
    notch = NotchScan()

with safe_load('Compact_Spectrometer'):
    from mfx.vonhamos import DeterministicVonHamos6Crystal
    spec = DeterministicVonHamos6Crystal("MFX:SPEC", name="dvh")

with safe_load('Undulator_Pointing'):
    from mfx.optimize.undpoint import UndPointAbs2DMFX
    und_abs=UndPointAbs2DMFX()
    und_del=und_abs.dxy

with safe_load('RE_Scans'):
    from mfx.scan import *
    scan = Scan()

with safe_load('Find_PV'):
    from mfx.find import *
    find = Find()

with safe_load('Get_Info'):
    from scripts.get_info import *

with safe_load('Wire_Scan'):
    from mfx.wire import *
    wire = Wire()

with safe_load('EXAFS'):
    from mfx.exafs import *
    exafs = Exafs()

with safe_load('EXAFS_Builder'):
    from mfx.exafs import EXAFSEnergyRangeBuilder
    exafs_energy_range_builder = EXAFSEnergyRangeBuilder()

with safe_load("laser wp power"):
    from pcdsdevices.lxe import LaserEnergyPositioner
    from hutch_python.utils import get_current_experiment
    from pcdsdevices.device import Component as Cpt
    from pcdsdevices.epics_motor import Newport

    # Hack the LXE class to make it work with Newports
    class LXE(LaserEnergyPositioner):
        motor = Cpt(Newport, "")

    lxe_calib_file = (f"/reg/neh/operator/mfxopr/experiments/{get_current_experiment('mfx')}/wpcalib")
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
            lens_v = Newport('MFX:LAS:MMN:12', name='lens_v')
            lens_f = Newport('MFX:LAS:MMN:09', name='lens_f')
            lens_h = Newport('MFX:LAS:MMN:11', name='lens_h')
            #lens_g = Newport('MFX:LAS:MMN:12', name='lens_g')

        with safe_load('Fast delay encoders'):
            lxt_fast1_enc = UsDigitalUsbEncoder('MFX:USDUSB4:01:CH0', name='lxt_fast_enc1', linked_axis=mfx_lxt_fast1)

        # timing virtual motors for x-ray laser delay adjustment
        lxt = lxt # virtual motor that moves the laser timing system phase shifter
        txt = txt
        lxt_ttc = lxt_ttc
        lxt_fast1 = mfx_lxt_fast1

def mfx_reload(module_name):
    import importlib
    import sys
    importlib.reload(sys.modules[module_name])

    if module_name == 'mfx.exafs':
        from mfx.exafs import Exafs, EXAFSEnergyRangeBuilder
        exafs = Exafs()
        exafs_energy_range_builder = EXAFSEnergyRangeBuilder()

    if module_name == 'mfx.optimize.verner_calibration':
        from mfx.optimize.vernier_calibration import VernierCalibration
        vernier_calib = VernierCalibration()

    if module_name == 'mfx.optimize.beam_status':
        from mfx.optimize.beam_status import BeamCheck
        beam_status = BeamCheck()

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
    from mfx.db import um6_pim as xcs_yag1
    from mfx.db import hx2_slits as xpp_s1
    from mfx.db import mfx_von_hamos_6crystal as vh
    import numpy as np
    from importlib import reload
    from mfx.db import mfx_atm as tt
    lens_v=las.lens_v
    lens_h=las.lens_h
    lens_f=las.lens_f
