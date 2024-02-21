import os
import time
import os.path
import logging
import subprocess

import numpy as np

from mfx.db import daq, sequencer, rayonix
from pcdsdevices.sequencer import EventSequencer
from pcdsdevices.evr import Trigger

pp_trig = Trigger('XRT:EVR:R48:TRIG1', name='pp_trigger')


class User:
    """Generic User Object"""
    pp_trig = pp_trig

