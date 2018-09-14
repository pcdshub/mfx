import logging

from .devices import XFLS

from hutch_python.utils import safe_load
from mfx.suspenders import BeamEnergySuspendFloor

logger = logging.getLogger(__name__)



with safe_load('transfocator'):
    from transfocate import Transfocator
    tfs = Transfocator("MFX:LENS", name='MFX Transfocator')

with safe_load('mfx_prefocus'):
    mfx_prefocus = XFLS('MFX:DIA:XFLS', name='mfx_prefocus')

with safe_load('beam_suspender'):
    beam_suspender = BeamEnergySuspendFloor(0.6)

with safe_load('plans'):
    from mfx.plans import *
