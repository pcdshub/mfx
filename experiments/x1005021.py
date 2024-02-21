########################
#Author: Antonio Gilardi
#Date: October 2022 
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
from mfx.db import mfx_attenuator as att
from mfx.db import bp, bpp, bps
from mfx.plans import serp_seq_scan
import time

#Commissioning Exp Number --> X1005021 

class User():
    def __init__(self):
        self.x_motor = Newport("MFX:HRA:MMN:29",name='x_motor')
        self.y_motor = Newport("MFX:HRA:MMN:30",name='y_motor')
        pass 
    def attenuator_scan(self, events=240,record=False, config= True,transmissions=[0.01,0.02,0.03]):
        for i in transmissions:
            att(i)
            time.sleep(3)
            daq.begin(events=events,record=record,wait=True, use_l3t=False)
            daq.end_run()
        daq.disconnect()
    def attenuator_single_scan(self, events = 240, record = False, transmissions=[0.01,0.02,0.03]):
        daq.end_run()
        daq.disconnect()
        try:
            pp.open()
            daq.configure(record=record)
            time.sleep(3)
            for i in transmissions:
                att(i,wait=True)
                time.sleep(3)
                daq.begin(events=events,record=record,wait=True, use_l3t=False)
        finally:
            daq.end_run()
            daq.disconnect()
    def test_att_scan(self,events=240,record=True,transmissions=[0.01,0.02,0.03]):
        daq.end_run()
        daq.disconnect()
        daq.configure()
        for i in transmissions:
            att(i)
            time.sleep(3)
            daq.begin(events=events,record=record,wait=True,use_l3t=False)
        daq.end_run()

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

    def WindowsScan(self, x_start, y_start, **kwargs):
        """
        This funcion perform a SnakeScan scan over the whole windows. 
         --> x_motor     : Motor deisgned to move over X axis
         --> y_motor     : Motor deisgned to move over Y axis        
         --> x_start [mm]: Start position for the X motor
         --> y_start [mm]: Start position for the Y motor
         # kwargs #
         --> y_speed [mm/s]: Y Motor Speed                              -- DEFAULT = 20 mm/s
         --> x_speed [mm/s]: X Motor Speed                              -- DEFAULT = 20 mm/s
         --> x_stop  [mm]  : Stop position for the X motor              -- DEFAULT = x_start + 18 mm 
         --> palsp_picker  : True for open False for flipflop           -- DEFAULT = True
         --> record        : True for recording False for not-recording -- DEFAULT = True
         --> verbose       : True for verbosity                         -- DEFAULT = False
        """
        original_x, original_y, original_x_speed = self.StoringValue()

        #ChipGeometry info
        window_size  = 18
        x_stop       = x_start + 18
        y_stop       = y_start + window_size
        x_speed      = 20
        y_speed      = 20
        palsp_picker = True 
        record       = True
        verbose      = False
        if kwargs.__contains__('x_speed'):
            x_speed = kwargs['x_speed']
            self.x_motor.velocity.set(x_speed)
        if kwargs.__contains__('y_speed'):
            y_speed = kwargs['y_speed']  
        if kwargs.__contains__('x_stop'):
            x_stop = kwargs['x_stop']  
            self.y_motor.velocity.set(y_speed)
        if kwargs.__contains__('palsp_picker'):
            palsp_picker = kwargs['palsp_picker']   
        if kwargs.__contains__('record'):
            record = kwargs['record']   
        if kwargs.__contains__('verbose'):
            verbose = kwargs['verbose']   

        self.y_motor.umv(y_start, log=verbose)
        self.x_motor.umv(x_start, log=verbose)
        while (self.x_motor.moving or self.y_motor.moving):
            pass
        print("Reached starting positions")
        print ("x:",x_start," - y:",y_start)
        print("")
        n_trips = round((window_size)/(y_speed*1/120))
        delta_y = (window_size)/n_trips
        if (record):
            print("STARTING DAQ:")
            print("-------------")
            daq.connect()
            daq.begin()       
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

        if (record):
            print("STOPPING DAQ:")
            print("-------------")
            daq.end_run()
            daq.disconnect()
            print("-------------")
            print("")
        self.RestoringValue(original_x, original_y, original_x_speed, verbose)
