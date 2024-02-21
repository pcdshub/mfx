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

#Commissioning Exp Number --> P10041 

class User():
    def __init__(self):
        pass 

    def StoringValue(self, x_motor, y_motor):
        print("Storing Starting Value")
        original_x = x_motor.position
        original_y = y_motor.position
        original_x_speed = x_motor.velocity.value
        print("-//-//-//-//-//-//-//-//-//-//-//-//")
        print("")
        return original_x,original_y,original_x_speed

    def RestoringValue(self, x_motor, y_motor, original_x, original_y, original_x_speed, verbose):
        print("-//-//-//-//-//-//-//-//-//-//-//-//")
        y_motor.umv(original_y, log=verbose)
        x_motor.umv(original_x, log=verbose)
        while (x_motor.moving or y_motor.moving):
            pass
        print("")
        print("Returned to original position")
        x_motor.velocity.set(original_x_speed)
        print("Resotred original velocity")

    def LineScan(self, x_motor, y_motor, x_start, y_start, **kwargs):
        """ 
        This funcion perform a scan over a line, moving only the x axis.
         --> x_motor     : Mo tor deisgned to move over X axis
         --> y_motor     : Motor deisgned to move over Y axis
         --> x_start [mm]: Start position for the X motor
         --> y_start [mm]: Start position for the Y motor
         # kwargs #
         --> x_speed [mm/s]: X Motor Speed                 -- DEFAULT = 20 mm/s
         --> x_stop  [mm]  : Stop position for the X motor -- DEFAULT = x_start + 18 mm 
         --> verbose       : Ture for verbosity            -- DEFAULT = FALSE
        """
        original_x, original_y, original_x_speed = self.StoringValue(x_motor, y_motor)

        x_stop = x_start + 18
        x_speed = 20
        verbose = False
        if kwargs.__contains__('x_speed'):
            x_speed = kwargs['x_speed']
            x_motor.velocity.set(x_speed)
        if kwargs.__contains__('x_stop'):
            x_stop = kwargs['x_stop']  
        if kwargs.__contains__('verbose'):
            verbose = kwargs['verbose']    
        
        x_motor.umv(x_start, log=verbose)
        y_motor.umv(y_start, log=verbose)
        while (x_motor.moving or y_motor.moving):
            pass
        print("Reached starting positions")
        print ("x:",x_start," - y:",y_start)
        print("")
    
        print("STARTING DAQ:")
        print("-------------")
        daq.connect()
        daq.begin()       
        print("-------------")
        print("")
        pp.open()
        x_motor.umv(x_stop, log=verbose)
        while (x_motor.moving):
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
        self.RestoringValue(x_motor, y_motor, original_x, original_y, original_x_speed, verbose)

    def MultipleLineScan(self, x_motor, y_motor, x_start, y_start, **kwargs):
        """ 
        This funcion perform a scan over a line, moving only the x axis.
         --> x_motor     : Motor deisgned to move over X axis
         --> y_motor     : Motor deisgned to move over Y axis
         --> x_start [mm]: Start position for the X motor
         --> y_start [mm]: Start position for the Y motor
         # kwargs #
         --> x_speed [mm/s] : X Motor Speed                        -- DEFAULT = 20 mm/s
         --> y_speed [mm/s] : Y Motor Speed                        -- DEFAULT = 20 mm/s
         --> x_stop  [mm]   : Stop position for the X motor        -- DEFAULT = x_start + 18 mm 
         --> n_windows      : Number of windows to be scanned over -- DEFAULT = 4
         --> verbose        : Ture for verbosity            -- DEFAULT = FALSE
        """
        original_x, original_y, original_x_speed = self.StoringValue(x_motor, y_motor)
        
        #ChipGeometry info
        window_gap = 2.35     
        window_size = 3.5
        n_windows = 4
        x_stop = x_start + 18 
        x_speed = 20
        y_speed = 20
        verbose = False
        if kwargs.__contains__('x_speed'):
            x_speed = kwargs['x_speed']
            x_motor.velocity.set(x_speed)
        if kwargs.__contains__('y_speed'):
            y_speed = kwargs['y_speed']  
            y_motor.velocity.set(y_speed)
        if kwargs.__contains__('x_stop'):
            x_stop = kwargs['x_stop']  
        if kwargs.__contains__('n_windows'):
            n_windows = kwargs['n_windows']    
        if kwargs.__contains__('verbose'):
            verbose = kwargs['verbose']  

        original_x = x_motor.position
        original_y = y_motor.position
        y_motor.umv(y_start, log=verbose)
        x_motor.umv(x_start, log=verbose)
        while (x_motor.moving or y_motor.moving):
            pass
        print("Reached starting positions")
        print ("x:",x_start," - y:",y_start)
        print("")

        print("STARTING DAQ:")
        print("-------------")
        daq.connect()
        daq.begin()       
        print("-------------")
        print("")       
        for j in range(n_windows):
            print("#################################")
            print('Starting windows number: %d' % (j+1))
            print("#################################")   
            pp.open()   
            x_motor.umv(x_stop,log=verbose)
            while (x_motor.moving):
                pass
            print("LINE SCANNED")
            print("")
            pp.close()
            y_start += window_gap + window_size
            y_motor.umv(y_start,log=verbose)
            x_motor.umv(x_start,log=verbose)
            while (x_motor.moving or y_motor.moving):
                pass
            sleep(2/30) 
        print("")
        print("STOPPING DAQ:")
        print("-------------")
        daq.end_run()
        daq.disconnect()
        print("-------------")
        print("")
        self.RestoringValue(x_motor, y_motor, original_x, original_y, original_x_speed, verbose)

    def WindowsScan(self, x_motor, y_motor, x_start, y_start, **kwargs):
        """
        This funcion perform a SnakeScan scan over the whole windows. 
         --> x_motor     : Motor deisgned to move over X axis
         --> y_motor     : Motor deisgned to move over Y axis        
         --> x_start [mm]: Start position for the X motor
         --> y_start [mm]: Start position for the Y motor
         # kwargs #
         --> y_speed [mm/s]: Y Motor Speed                 -- DEFAULT = 20 mm/s
         --> x_speed [mm/s]: X Motor Speed                 -- DEFAULT = 20 mm/s
         --> x_stop  [mm]  : Stop position for the X motor -- DEFAULT = x_start + 18 mm 
         --> verbose       : Ture for verbosity            -- DEFAULT = FALSE
        """
        original_x, original_y, original_x_speed = self.StoringValue(x_motor, y_motor)

        #ChipGeometry info
        window_size = 3.5
        x_stop = x_start + 18
        y_stop = y_start + window_size
        x_speed = 20
        y_speed = 20
        verbose = False
        if kwargs.__contains__('x_speed'):
            x_speed = kwargs['x_speed']
            x_motor.velocity.set(x_speed)
        if kwargs.__contains__('y_speed'):
            y_speed = kwargs['y_speed']  
        if kwargs.__contains__('x_stop'):
            x_stop = kwargs['x_stop']  
            y_motor.velocity.set(y_speed)
        if kwargs.__contains__('verbose'):
            verbose = kwargs['verbose']   

        y_motor.umv(y_start, log=verbose)
        x_motor.umv(x_start, log=verbose)
        while (x_motor.moving or y_motor.moving):
            pass
        print("Reached starting positions")
        print ("x:",x_start," - y:",y_start)
        print("")
        n_trips = round((window_size)/(y_speed*1/120))
        delta_y = (window_size)/n_trips
        print("STARTING DAQ:")
        print("-------------")
        daq.connect()
        daq.begin()       
        print("-------------")      
        print("")
        pp.open()
        for i in range(n_trips):
            y_motor.umv(y_start, log=verbose)
            while (y_motor.moving):
                pass
            print("---------------------------------")
            print('Starting trip number: %d' % (i+1))
            print("---------------------------------")            
            x_motor.umv(x_stop, log=verbose)
            while (x_motor.moving):
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
        self.RestoringValue(x_motor, y_motor, original_x, original_y, original_x_speed, verbose)


    def ChipScan(self, x_motor, y_motor, x_start, y_start, **kwargs):
        """
        This funcion perform a SnakeScan scan over the whole windows. 
         --> x_motor     : Motor deisgned to move over X axis
         --> y_motor     : Motor deisgned to move over Y axis        
         --> x_start [mm]: Start position for the X motor
         --> y_start [mm]: Start position for the Y motor
         # kwargs #
         --> x_speed [mm/s]: X Motor Speed                 -- DEFAULT = 20 mm/s
         --> y_speed [mm/s]: Y Motor Speed                 -- DEFAULT = 20 mm/s
         --> x_stop  [mm]  : Stop position for the X motor -- DEFAULT = x_start + 18 mm 
         --> n_windows     : Number of windows             -- DEFAULT = 4
         --> verbose       : Ture for verbosity            -- DEFAULT = FALSE
        """
        original_x, original_y, original_x_speed = self.StoringValue(x_motor, y_motor)

        #ChipGeometry info
        window_size = 3.5
        window_gap = 2.35        
        n_windows = 4
        x_stop = x_start + 18
        #y_stop = y_start + (window_size*n_windows) + (window_gap*(n_windows-1))
        verbose = False
        x_speed = 20
        y_speed = 20

        if kwargs.__contains__('x_speed'):
            x_speed = kwargs['x_speed']
            x_motor.velocity.set(x_speed)
        if kwargs.__contains__('y_speed'):
            y_speed = kwargs['y_speed']  
            y_motor.velocity.set(y_speed)
        if kwargs.__contains__('x_stop'):
            x_stop = kwargs['x_stop']    
        if kwargs.__contains__('n_windows'):
            n_windows = kwargs['n_windows']    
        if kwargs.__contains__('verbose'):
            verbose = kwargs['verbose']   

        y_motor.umv(y_start, log=verbose)
        x_motor.umv(x_start, log=verbose)
        while (x_motor.moving or y_motor.moving):
            pass
        print("Reached starting positions")
        print ("x:",x_start," - y:",y_start)
        print("")
        
        n_trips = round((window_size)/(y_speed*1/120))
        delta_y = (window_size/n_trips)
        print("STARTING DAQ:")
        print("-------------")
        daq.connect()
        daq.begin()       
        print("-------------")      
        print("")      
        for j in range(n_windows):
            print("#################################")
            print('Starting windows number: %d' % (j+1))
            print("#################################")   
            sleep(2/30) 
            pp.open()
            for i in range(n_trips):
                y_motor.umv(y_start, log=verbose)
                while (y_motor.moving):
                    pass
                print("---------------------------------")
                print('Starting trip number: %d' % (i+1))
                print("---------------------------------")
                x_motor.umv(x_stop, log=verbose)
                while (x_motor.moving):
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
        self.RestoringValue(x_motor, y_motor, original_x, original_y, original_x_speed, verbose)