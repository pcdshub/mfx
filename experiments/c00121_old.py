from subprocess import check_output

import json
import sys
import time
import os

import numpy as np
from hutch_python.utils import safe_load
from ophyd import EpicsSignalRO
from ophyd import EpicsSignal
from ophyd import Component as Cpt
from ophyd import FormattedComponent as FCpt
from bluesky import RunEngine
from bluesky.plans import scan
from bluesky.plans import list_scan
from bluesky.plan_stubs import configure

#from bluesky.plans import list_grid_scan
from ophyd import Component as Cpt
from ophyd import Device
from pcdsdevices.epics_motor import Motor, Newport, IMS
from pcdsdevices.sim import SlowMotor
from pcdsdevices.interface import BaseInterface
from pcdsdevices.device_types import Trigger
from pcdsdevices.areadetector import plugins
from mfx.db import daq
from mfx.db import camviewer
from mfx.db import RE
from mfx.db import mfx_pulsepicker as pp
from mfx.db import bp, bpp, bps
from mfx.plans import serp_seq_scan
from time import sleep

#grabbed from cxic00120

class User():
    def __init__(self):
        pass
#        self._sync_markers = {0.5:0, 1:1, 5:2, 10:3, 30:4, 60:5, 120:6, 360:7}
#        self.evr_pp = Trigger('CXI:R48:EVR:41:TRIG0',name='evr_pp')
        # Simulated motors for testing
        self.m1 = SlowMotor()
        self.m2 = SlowMotor()

    def dumbSnake(self, xmotor, ymotor, xStart, xEnd, yDelta, nRoundTrips, sweepTime):
        """ 
        Simple rastering for running at 120Hz with shutter open/close before
        and after motion stop.
         
        Need some testing how to deal with intermittent motion errors.
        X is fly.
        """
        xmotor.umv(xStart)
        daq.connect()
        daq.begin()
        sleep(2)
        print('Reached horizontal start position')
        # looping through n round trips
        for i in range(nRoundTrips):
            try:
                print('starting round trip %d' % (i+1))
                xmotor.mv(xEnd)
                sleep(0.1)
                pp.open()
                sleep(sweepTime)
                pp.close()
                xmotor.wait()
                ymotor.mvr(yDelta)
                sleep(1.2)#original was 1
                xmotor.mv(xStart)
                sleep(0.1)
                pp.open()
                sleep(sweepTime)
                pp.close()
                xmotor.wait()
                ymotor.mvr(yDelta)
                print('ypos',ymotor.wm())
                sleep(1.2)#original was 1
            except:
                print('round trip %d didn not end happily' % i)
        daq.end_run()
        daq.disconnect()


    class Chip(Device):
        x = FCpt(Motor, '{x_prefix}')
        y = FCpt(Motor, '{y_prefix}')

        begin_x = None

        def __init__(self, *args, x_prefix=None, y_prefix=None, **kwargs):
            self.x_prefix = x_prefix
            self.y_prefix = y_prefix

            super().__init__(*args, **kwargs)
            
        def scan_rows(self, n_rows=10):
            pass

        def scan_window(self):
            pass

        def scan_chip(self):
            pass


    class SimChip(Chip):
        x = FCpt(SlowMotor, 'x')
        y = FCpt(SlowMotor, 'y')
