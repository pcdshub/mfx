import logging

from hutch_python.utils import safe_load

logger = logging.getLogger(__name__)


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

with safe_load('beam_suspender'):
    from mfx.suspenders import BeamEnergySuspendFloor
    beam_suspender = BeamEnergySuspendFloor(0.6)

with safe_load('plans'):
    from mfx.plans import *
