import sys
from time import sleep
import os
import numpy as np

from epics import caget
from epics import caput
from ophyd import Device
from pcdsdevices.epics_motor import Newport

class User():
    def __init__(self):
        pass
    def muovi(self, motore, size):
        motore.move(size)

    class Chip(Device):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            pass
        def definition(self, Nome='None', size = 0):
            test = Newport(Nome, name='test')
            self.muovi(test,size)

# import sys
# sys.path.append("/cds/group/pcds/pyps/apps/hutch-python/mfx/experiments")
# import test
# a = test.User()
# a.definition(MFX:HRA:MMN:25, 5)


#from importlib import reload
#set_engineering_mode(0)

#MFX:HRA:MMN:25

