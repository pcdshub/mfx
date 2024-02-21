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

with safe_load('plans'):
    from mfx.plans import *

with safe_load('Mesh Voltage Control'):
    from pcdsdevices.analog_signals import Mesh
    mesh = Mesh('MFX:USR', 0, 1)

#
#
# preparation for fine timing beamline python.
#
#

with safe_load('FS45 lxt & lxt_ttc'):
    import logging
    logging.getLogger('pint').setLevel(logging.ERROR)

    from pcdsdevices.device import ObjectComponent as OCpt
    from pcdsdevices.lxe import LaserTiming
    from pcdsdevices.pseudopos import SyncAxis
    from pcdsdevices.device_types import DelayNewport
    # from xpp.db import xpp_txt

    lxt = LaserTiming('LAS:FS45', name='lxt')
    txt = DelayNewport('MFX:LAS:MMN:06', n_bounces=16, name='txt')
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
    # from xpp.db import xpp_txt as txt
    opa_comp = Newport('MFX:LAS:MMN:01', name='opa_comp') # linear motor for OPA compressor
                                                          # this is the timetool compensationn stage. You might want this one

    class las():
        opa_comp=opa_comp # waveplate for the main compressor
        # Time tool motors
        # initialize motors here for tab completion if wanted
        with safe_load('add more laser motors'):
            lasmot2 = Newport('MFX:LAS:MMN:02', name='lasmot2') # give descriptions later
            lasmot3 = Newport('MFX:LAS:MMN:03', name='lasmot3')
            lasmot4 = Newport('MFX:LAS:MMN:04', name='lasmot4')
            lasmot5 = Newport('MFX:LAS:MMN:05', name='lasmot5')
            lasmot6 = Newport('MFX:LAS:MMN:06', name='lasmot6')
            lasmot7 = Newport('MFX:LAS:MMN:07', name='lasmot7')
            lasmot8 = Newport('MFX:LAS:MMN:08', name='lasmot8')
            

        # timing virtual motors for x-ray laser delay adjustment
        lxt = lxt # virtual motor that moves the laser timing system phase shifter
        txt = txt
        lxt_ttc = lxt_ttc
        #txt=txt # virtual motor that moves the time tool white light delay stage
        #lxt_ttc=lxt_ttc # virtual motor that moves the LXT and TXT in a synchronous way so the TT signal stays at the center of the OPAL spectral window

