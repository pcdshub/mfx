########################
#Author: Antonio Gilardi
#Date: October 2022 
########################

from time import sleep

import numpy as np
from bluesky import RunEngine
from bluesky.plan_stubs import configure
from bluesky.plans import list_scan, scan
from mfx.db import RE, bp, bpp, bps, daq
from mfx.db import mfx_pulsepicker as pp
from mfx.db import sequencer as seq
from mfx.plans import serp_seq_scan
from ophyd import Component as Cpt
from ophyd import Device
from ophyd import FormattedComponent as FCpt
from pcdsdevices.areadetector import plugins
from pcdsdevices.device_types import Trigger
from pcdsdevices.epics_motor import Newport
from pcdsdevices.interface import BaseInterface

#Actual Exp Number --> P231 

class User():
    def __init__(self):
        self.x_motor = Newport("MFX:HRA:MMN:29", name='x_motor')
        self.y_motor = Newport("MFX:HRA:MMN:30", name='y_motor')
        pass 

    def StoringValue(self):
        print("Storing Starting Value")
        original_x = self.x_motor.position
        original_y = self.y_motor.position
        original_x_speed = self.x_motor.velocity.value
        original_y_speed = self.y_motor.velocity.value
        print("-//-//-//-//-//-//-//-//-//-//-//-//")
        print("")
        return original_x,original_y,original_x_speed,original_y_speed

    def RestoringValue(self, original_x, original_y, original_x_speed, original_y_speed, verbose):
        print("-//-//-//-//-//-//-//-//-//-//-//-//")
        self.y_motor.umv(original_y, log=verbose)
        self.x_motor.umv(original_x, log=verbose)
        while (self.x_motor.moving or self.y_motor.moving):
            pass
        print("")
        print("Returned to original position")
        self.x_motor.velocity.set(original_x_speed)
        self.y_motor.velocity.set(original_y_speed)
        print("Resotred original velocity")

    def LineScan(self, x_start, y_start, record=True, **kwargs):
        """ 
        This funcion perform a scan over a line, moving only the x axis.
         --> x_start [mm]: Start position for the X motor
         --> y_start [mm]: Start position for the Y motor
         --> record      : True for recording False for not-recording -- DEFAULT = True
         # kwargs #
         --> x_speed [mm/s]: X Motor Speed                 -- DEFAULT = 25 mm/s
         --> x_stop  [mm]  : Stop position for the X motor -- DEFAULT = x_start + 19 mm 
         --> verbose       : Ture for verbosity            -- DEFAULT = FALSE
        """
        original_x, original_y, original_x_speed,original_y_speed = self.StoringValue()

        x_stop = x_start + 19
        x_speed = 25
        verbose = False
        if kwargs.__contains__('x_speed'):
            x_speed = kwargs['x_speed']
        if kwargs.__contains__('x_stop'):
            x_stop = kwargs['x_stop']  
        if kwargs.__contains__('verbose'):
            verbose = kwargs['verbose']    
        self.x_motor.velocity.set(x_speed)
        sleep(1)

        self.x_motor.umv(x_start, log=verbose)
        self.y_motor.umv(y_start, log=verbose)
        while (self.x_motor.moving or self.y_motor.moving):
            pass
        print("Reached starting positions")
        print ("x:",x_start," - y:",y_start)
        print("")
    
        print("STARTING DAQ:")
        print("-------------")
        daq.connect()
        daq.begin(record=record)       
        print("-------------")
        print("")
        pp.open()
        self.x_motor.umv(x_stop, log=verbose)
        while (self.x_motor.moving):
            pass
        print("LINE SCANNED")
        print("")
        pp.close()
        print("STOPPING DAQ:")
        print("-------------")
        daq.end_run()
        daq.disconnect()
        print("-------------")
        print("")
        self.RestoringValue(original_x, original_y, original_x_speed, original_y_speed, verbose)

    def MultipleLineScan(self, x_start, y_start, record=True, **kwargs):
        """ 
        This funcion perform a scan over a line, moving only the x axis.
         --> x_motor     : Motor deisgned to move over X axis
         --> y_motor     : Motor deisgned to move over Y axis
         --> x_start [mm]: Start position for the X motor
         --> y_start [mm]: Start position for the Y motor
         --> record      : True for recording False for not-recording -- DEFAULT = True
         # kwargs #
         --> x_speed [mm/s] : X Motor Speed                        -- DEFAULT = 25 mm/s
         --> y_speed [mm/s] : Y Motor Speed                        -- DEFAULT = 25 mm/s
         --> x_stop  [mm]   : Stop position for the X motor        -- DEFAULT = x_start + 19 mm 
         --> n_windows      : Number of windows to be scanned over -- DEFAULT = 4
         --> verbose        : Ture for verbosity                   -- DEFAULT = FALSE
        """
        original_x, original_y, original_x_speed, original_y_speed = self.StoringValue()
        
        #ChipGeometry info
        window_gap = 2.35     
        window_size = 3.5
        n_windows = 4
        x_stop = x_start + 19
        x_speed = 25
        y_speed = 25
        verbose = False
        if kwargs.__contains__('x_speed'):
            x_speed = kwargs['x_speed']
        if kwargs.__contains__('y_speed'):
            y_speed = kwargs['y_speed']     
        if kwargs.__contains__('x_stop'):
            x_stop = kwargs['x_stop']  
        if kwargs.__contains__('n_windows'):
            n_windows = kwargs['n_windows']    
        if kwargs.__contains__('verbose'):
            verbose = kwargs['verbose']  
        self.y_motor.velocity.set(y_speed)
        self.x_motor.velocity.set(x_speed)
        sleep(1)

        original_x = self.x_motor.position
        original_y = self.y_motor.position
        self.y_motor.umv(y_start, log=verbose)
        self.x_motor.umv(x_start, log=verbose)
        while (self.x_motor.moving or self.y_motor.moving):
            pass
        print("Reached starting positions")
        print ("x:",x_start," - y:",y_start)
        print("")

        print("STARTING DAQ:")
        print("-------------")
        daq.connect()
        daq.begin(record=record)       
        print("-------------")
        print("")       
        for j in range(n_windows):
            print("#################################")
            print('Starting windows number: %d' % (j+1))
            print("#################################")   
            pp.open()   
            self.x_motor.umv(x_stop,log=verbose)
            while (x_motor.moving):
                pass
            print("LINE SCANNED")
            print("")
            pp.close()
            y_start += window_gap + window_size
            self.y_motor.umv(y_start,log=verbose)
            self.x_motor.umv(x_start,log=verbose)
            while (self.x_motor.moving or self.y_motor.moving):
                pass
            sleep(30/30) 
        print("")
        print("STOPPING DAQ:")
        print("-------------")
        daq.end_run()
        daq.disconnect()
        print("-------------")
        print("")
        self.RestoringValue(original_x, original_y, original_x_speed, original_y_speed, verbose)

    def WindowsScan(self, x_start, y_start, record=True, **kwargs):
        """
        This funcion perform a SnakeScan scan over the whole windows. 
         --> x_motor     : Motor deisgned to move over X axis
         --> y_motor     : Motor deisgned to move over Y axis        
         --> x_start [mm]: Start position for the X motor
         --> y_start [mm]: Start position for the Y motor
         --> record      : True for recording False for not-recording -- DEFAULT = True
         # kwargs #
         --> y_speed     [mm/s]: Y Motor Speed                 -- DEFAULT = 25 mm/s
         --> x_speed     [mm/s]: X Motor Speed                 -- DEFAULT = 25 mm/s
         --> x_stop      [mm]  : Stop position for the X motor -- DEFAULT = x_start + 19 mm 
         --> window_size [mm]  : Stop position for the Y motor -- DEFAULT = 3.5
         --> verbose           : Ture for verbosity            -- DEFAULT = FALSE
        """
        original_x, original_y, original_x_speed, original_y_speed = self.StoringValue()
    
        #ChipGeometry info
        window_size = 3.5
        x_stop = x_start + 19
        x_speed = 25
        y_speed = 25
        verbose = False
        if kwargs.__contains__('x_speed'):
            x_speed = kwargs['x_speed']
        if kwargs.__contains__('y_speed'):
            y_speed = kwargs['y_speed']  
        if kwargs.__contains__('x_stop'):
            x_stop = kwargs['x_stop']  
        if kwargs.__contains__('window_size'):
            window_size = kwargs['window_size']  
        if kwargs.__contains__('verbose'):
            verbose = kwargs['verbose']   
        self.x_motor.velocity.set(x_speed)
        self.y_motor.velocity.set(y_speed)
        sleep(1)

        self.y_motor.umv(y_start, log=verbose)
        self.x_motor.umv(x_start, log=verbose)
        while (self.x_motor.moving or self.y_motor.moving):
            pass
        print("Reached starting positions")
        print ("x:",x_start," - y:",y_start)
        print("")
        n_trips = round((window_size)/(y_speed*1/120))
        delta_y = (window_size)/n_trips
        print("STARTING DAQ:")
        print("-------------")
        daq.connect()
        daq.begin(record=record)       
        print("-------------")      
        print("")
        pp.open()
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
        self.RestoringValue(original_x, original_y, original_x_speed, original_y_speed, verbose)


    def ChipScan(self, x_start, y_start, record=True, **kwargs):
        """
        This funcion perform a SnakeScan scan over the whole windows. 
         --> x_motor     : Motor deisgned to move over X axis
         --> y_motor     : Motor deisgned to move over Y axis        
         --> x_start [mm]: Start position for the X motor
         --> y_start [mm]: Start position for the Y motor
         --> record      : True for recording False for not-recording -- DEFAULT = True
         # kwargs #
         --> x_speed [mm/s]: X Motor Speed                 -- DEFAULT = 25 mm/s
         --> y_speed [mm/s]: Y Motor Speed                 -- DEFAULT = 25 mm/s
         --> x_stop  [mm]  : Stop position for the X motor -- DEFAULT = x_start + 19 mm 
         --> n_windows     : Number of windows             -- DEFAULT = 4
         --> verbose       : Ture for verbosity            -- DEFAULT = FALSE
        """
        original_x, original_y, original_x_speed, original_y_speed = self.StoringValue()

        #ChipGeometry info
        window_size = 3.5
        window_gap = 2.35        
        n_windows = 4
        x_stop = x_start + 19
        verbose = False
        x_speed = 25
        y_speed = 25

        if kwargs.__contains__('x_speed'):
            x_speed = kwargs['x_speed']
        if kwargs.__contains__('y_speed'):
            y_speed = kwargs['y_speed']  
        if kwargs.__contains__('x_stop'):
            x_stop = kwargs['x_stop']    
        if kwargs.__contains__('n_windows'):
            n_windows = kwargs['n_windows']    
        if kwargs.__contains__('verbose'):
            verbose = kwargs['verbose']   
        self.y_motor.velocity.set(y_speed)
        self.x_motor.velocity.set(x_speed)
        sleep(1)
        self.y_motor.umv(y_start, log=verbose)
        self.x_motor.umv(x_start, log=verbose)
        while (self.x_motor.moving or self.y_motor.moving):
            pass
        print("Reached starting positions")
        print ("x:",x_start," - y:",y_start)
        print("")
        
        n_trips = round((window_size)/(y_speed*1/120))
        delta_y = (window_size/n_trips)
        print("STARTING DAQ:")
        print("-------------")
        daq.connect()
        daq.begin(record=record)       
        print("-------------")      
        print("")      
        for j in range(n_windows):
            print("#################################")
            print('Starting windows number: %d' % (j+1))
            print("#################################")   
            sleep(30/30) 
            pp.open()
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
                comodo = x_stop
                x_stop = x_start
                x_start = comodo
                y_start += delta_y
            pp.close()
            y_start += window_gap
        print("STOPPING DAQ:")
        print("-------------")
        daq.end_run()
        daq.disconnect()
        print("-------------")
        print("")
        self.RestoringValue(original_x, original_y, original_x_speed, original_y_speed, verbose)