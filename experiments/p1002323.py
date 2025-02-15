########################
#Author: Antonio Gilardi
#Date: October 2022 
#Update Jan 2025 for P-10030: updated motor PVs, changed from ePix to Rayonix (30 Hz)
########################

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

class User():
    def __init__(self):
        #Updated motor PV
        self.x_motor = Newport("MFX:DOD:MMN:02",name='x_motor')
        self.y_motor = Newport("MFX:DOD:MMN:03",name='y_motor')
        pass 

    def StoringValue(self):
        print("Storing Starting Value")
        original_x = self.x_motor.position
        original_y = self.y_motor.position
        original_x_speed = self.x_motor.velocity.value
        print("-//-//-//-//-//-//-//-//-//-//-//-//")
        print("")
        return original_x,original_y,original_x_speed

    def RestoringValue(self, original_x, original_y, original_x_speed, verbose):
        print("-//-//-//-//-//-//-//-//-//-//-//-//")
        self.y_motor.umv(original_y, log=verbose)
        self.x_motor.umv(original_x, log=verbose)
        while (self.x_motor.moving or self.y_motor.moving):
            pass
        print("")
        print("Returned to original position")
        self.x_motor.velocity.set(original_x_speed)
        print("Resotred original velocity")

    def WindowsScan(self, x_start, y_start, record=True, **kwargs):
        """
        This funcion perform a SnakeScan scan over the whole windows. 
         --> x_start [mm]: Start position for the X motor
         --> y_start [mm]: Start position for the Y motor
         --> record      : True for recording False for not-recording -- DEFAULT = True
         # kwargs #
         #Updated x_speed and y_speed based on 50 um step with 30 Hz
         --> y_speed     [mm/s]: Y Motor Speed                              -- DEFAULT = 1.5 mm/s
         --> x_speed     [mm/s]: X Motor Speed                              -- DEFAULT = 1.5 mm/s
         #Updated x_stop for small chip
         --> x_stop      [mm]  : Stop position for the X motor              -- DEFAULT = x_start + 4 mm 
         --> window_size [mm]  : Scanning range for the Y motor             -- DEFAULT = 3 mm 
         #False for 30 Hz with Rayonix
         --> palsp_picker      : True for open False for flipflop           -- DEFAULT = False
         --> verbose           : True for verbosity                         -- DEFAULT = False
        """
        original_x, original_y, original_x_speed = self.StoringValue()

        #ChipGeometry info
        window_size  = 3
        #Updated x_stop for small chip
        x_stop       = x_start + 4
        x_speed      = 1.5
        y_speed      = 1.5
        palsp_picker = False 
        verbose      = True
        if kwargs.__contains__('x_speed'):
            x_speed = kwargs['x_speed']
        if kwargs.__contains__('y_speed'):
            y_speed = kwargs['y_speed']  
        if kwargs.__contains__('x_stop'):
            x_stop = kwargs['x_stop'] 
        if kwargs.__contains__('window_size'):
            window_size = kwargs['window_size']  
        if kwargs.__contains__('palsp_picker'):
            palsp_picker = kwargs['palsp_picker']   
        if kwargs.__contains__('record'):
            record = kwargs['record']   
        if kwargs.__contains__('verbose'):
            verbose = kwargs['verbose']   

        self.x_motor.velocity.set(x_speed)
        self.y_motor.velocity.set(y_speed)
        sleep(3)

        self.y_motor.umv(y_start, log=verbose)
        self.x_motor.umv(x_start, log=verbose)
        while (self.x_motor.moving or self.y_motor.moving):
            pass
        print("Reached starting positions")
        print ("x:",x_start," - y:",y_start)
        print("")
        #Updated to 30 Hz for Rayonix
        n_trips = round((window_size)/(y_speed*1/30))
        delta_y = (window_size)/n_trips
        
        print("STARTING DAQ:")
        print("-------------")
        daq.connect()
        daq.begin(record=record)       
        print("-------------")      
        print("")
        if (palsp_picker):
            pp.open()
        else:
            pp.flipflop()
        for i in range(n_trips):
            self.y_motor.umv(y_start, log=verbose)
            while (self.y_motor.moving):
                pass
            print("---------------------------------")
            print('Starting trip number: %d' % (i+1))
            print("---------------------------------")            
            self.x_motor.umv(x_stop, log=verbose)
            while (self.x_motor.moving):
                pass
            comodo   = x_stop
            x_stop   = x_start
            x_start  = comodo
            y_start += delta_y
        pp.close()

        print("STOPPING DAQ:")
        print("-------------")
        daq.end_run()
        daq.disconnect()
        print("-------------")
        print("")
        self.RestoringValue(original_x, original_y, original_x_speed, verbose)
