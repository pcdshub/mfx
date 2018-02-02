import logging
import warnings
from contextlib import contextmanager

from .devices import XFLS, Piezo
from pcdsdevices.epics_motor import EpicsMotor

from hutch_python import hutch

warnings.filterwarnings('ignore')
from mfx.suspenders import BeamEnergySuspendFloor
warnings.filterwarnings('default')

logger = logging.getLogger(__name__)

@contextmanager
def safe_load(name):
    try:
        yield
        logger.info("Loaded device %s! \033[32mSUCCESS\033[0m", name)
    except Exception:
        logger.exception('Error loading %s! \033[31mFAILED\033[0m', name)


with safe_load('transfocator'):
    from transfocate.config import mfx_transfocator as transfocator

with safe_load('tfs_trans'):
    tfs_trans = EpicsMotor('MFX:TFS:MMS:21', name='tfs_trans')

with safe_load('mfx_prefocus'):
    mfx_prefocus = XFLS('MFX:DIA:XFLS', name='mfx_prefocus')

with safe_load('beam_suspender'):
    beam_suspender = BeamEnergySuspendFloor(0.6)
    hutch.RE.install_suspender(beam_suspender)

with safe_load('inj_z'):
    inj_x = Piezo('MFX:USR:PIZ:01', name='inj_z')

with safe_load('shield_z'):
    inj_y = Piezo('MFX:USR:PIZ:02', name='shield_z')
