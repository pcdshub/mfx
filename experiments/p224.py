import numpy as np
from ophyd import Component as Cpt
from ophyd import FormattedComponent as FCpt
from bluesky import RunEngine
from bluesky.plans import scan
from bluesky.plans import list_scan
from bluesky.plan_stubs import configure
from time import sleep
from ophyd import Device
from pcdsdevices.epics_motor import Newport
from pcdsdevices.interface import BaseInterface
from pcdsdevices.device_types import Trigger
from pcdsdevices.areadetector import plugins
from mfx.db import daq
from mfx.db import RE
from mfx.db import mfx_pulsepicker as pp
from mfx.db import bp, bpp, bps
from mfx.plans import serp_seq_scan

#from pcdsdevices.sim import SlowMotor


class User():
    def __init__(self):
        pass 

    
    def LineScan(self, xmotor, ymotor, xStart, yStart, xStop, yStop, sweepTime):
        """ 
        # This funcion perform a scan over the x axis while the y axis is also moving.
        # if yStart == yStop this if for a DumbSnakeScan otherwise for a ZigZagScan
        """
        xmotor.umv(xStart)
        ymotor.umv(yStart)
        sleep(2)
        daq.connect()
        daq.begin()        
        sleep(2)

        ymotor.mvr(yStop) 
        sleep(0.1)
        pp.open()
        xmotor.mv(xStop)
        sleep(sweepTime)
        pp.close()                                

        daq.end_run()
        daq.disconnect()

    def ZigZagScan(self, xmotor, ymotor, xStart, yStart, xStop, yStop, nRoundTrips, sweepTime):
        """ 
        Performs a zigzag scan as a series of "LineScan" autoupdating the y position 
        """
        for i in range(nRoundTrips):
            print('Starting round trip number: %d' % (i+1))
            yStopPartial = (yStop/nRoundTrips)*(i+1)
            self.LineScan(self, xmotor, ymotor, xStart, yStart, xStop, yStopPartial, sweepTime)
            comodo =  xStart
            xStart = xStop
            xStop = comodo
            yStart = yStopPartial

    def DumbSnakeScan(self, xmotor, ymotor, xStart, yStart, xStop, yStop, nRoundTrips, sweepTime):
        """ 
        Performs a snake scan as a series of "LineScan" autoupdating the y position 

        """
        for i in range(nRoundTrips):
            print('Starting round trip number: %d' % (i+1))
            self.LineScan(self, xmotor, ymotor, xStart, yStart, xStop, yStart, sweepTime)
            yStart = (yStop/nRoundTrips)*(i+1)
            ymotor.mvr(yStart) 
            comodo =  xStart
            xStart = xStop
            xStop = comodo

########################################################
    class Chip(Device):
        #x = FCpt(Motor, '{x_prefix}')
        #y = FCpt(Motor, '{y_prefix}')
        def __init__(self, *args, x_prefix=None, y_prefix=None, xStart=None, yStart=None, xStop=None, yStop=None, safeGap=None ,**kwargs):
            self.x_prefix = x_prefix
            self.y_prefix = y_prefix
            self.xStart = xStart
            self.xStop = xStop
            self.yStop = yStop
            self.yStart = yStart
            self.safeGap = safeGap
            
            self.x = SlowMotor()
            self.y = SlowMotor()

            super().__init__(*args, **kwargs)
            
        def scan_chip(self, scan_type = "None", nRoundTrips=None, sweepTime=None, x_StepSize=None, y_StepSize=None, waitingTime=None):
            if (scan_type == "DumbSnakeScan"):
                print("Starting Dumb Snake Scan")
                self.DumbSnakeScan(self.x, self.y, xStart=self.xStart, yStart=self.yStart, xStop=self.xStop, yStop=self.yStop, safeGap=self.safeGap, nRoundTrips=nRoundTrips, sweepTime=sweepTime)
            elif (scan_type == "ZigZagScan"):
                print("Starting Zig Zag Scan")
                self.ZigZagScan(self.x, self.y, xStart=self.xStart, yStart=self.yStart, xStop=self.xStop, yStop=self.yStop, safeGap=self.safeGap, nRoundTrips=nRoundTrips, sweepTime=sweepTime)
            elif (scan_type == "SnakeScan"):
                print("Starting Snake Scan")
                self.SnakeScan(self.x, self.y, xStart=self.xStart, yStart=self.yStart, xStop=self.xStop, yStop=self.yStop, safeGap=self.safeGap, x_StepSize=x_StepSize, y_StepSize=y_StepSize,  waitingTime=waitingTime)
            else:
                print("Scan type not coded")

########################################################  
    class Windows(Device):
        def __init__(self, *args, x_prefix=None, y_prefix=None, xStart=None, yStart=None, xStop=None, yStop=None, n_windows=None, windows_dist=None, raw_dist, safeGap=None, **kwargs):
            self.x_prefix = x_prefix
            self.y_prefix = y_prefix
            self.xStart = xStart
            self.xStop = xStop
            self.yStop = yStop
            self.yStart = yStart
            self.n_windows = n_windows 
            self.windows_dist = windows_dist
            self.raw_dist = raw_dist
            self.safeGap = safeGap

        def scan_rows(self, n_rows=None, sweepTime=None):
            for i in range(n_rows):
                yStart = self.yStart + (self.raw_dist * i) 
                for j in range(self.n_windows):
                    yStart += self.windows_dist * j
                    self.LineScan(self.x, self.y, xStart=self.xStart, yStart=yStart, xStop=self.xStop, yStop=yStart, sweepTime=sweepTime)

        def scan_windows(self, scan_type = "None", nRoundTrips=None, sweepTime=None, x_StepSize=None, y_StepSize=None, waitingTime=None):
            for i in range(self.n_windows):
                yStart = self.yStart + (self.windows_dist * i)
                yStop = self.yStop + (self.windows_dist * i)
                self.SnakeScan(self.x, self.y, xStart=self.xStart, yStart=yStart, xStop=self.xStop, yStop=yStop, safeGap=self.safeGap, x_StepSize=x_StepSize, y_StepSize=y_StepSize,  waitingTime=waitingTime)
 
