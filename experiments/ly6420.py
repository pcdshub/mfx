import sys
import time
import os
import socket
import logging

import numpy as np
import elog
from hutch_python.utils import safe_load
from ophyd import EpicsSignalRO
from ophyd import EpicsSignal
from bluesky import RunEngine
from bluesky.plans import scan
from bluesky.plans import list_scan
from ophyd import Component as Cpt
from ophyd import Device
from pcdsdevices.interface import BaseInterface
from pcdsdevices.areadetector import plugins
from pcdsdevices.device_types import Newport, IMS
from pcdsdevices.device_types import Trigger

#os.environ['EPICS_CA_ADDR_LIST']="172.21.87.255 172.21.46.255"

class User():
    def __init__(self):
        #########################################################################
        #            Add the axes
        #########################################################################
        with safe_load('Polycapillary System'):
            from pcdsdevices.epics_motor import EpicsMotorInterface
            from ophyd.device import Device, Component as Cpt 
            from ophyd.signal import Signal

            class MMC(EpicsMotorInterface):
                direction_of_travel = Cpt(Signal, kind='omitted')
            class Polycap(Device):
                m1 = Cpt(MMC, ':MOTOR1', name='motor1')    
                m2 = Cpt(MMC, ':MOTOR2', name='motor2')
                m3 = Cpt(MMC, ':MOTOR3', name='motor3')
                m4 = Cpt(MMC, ':MOTOR4', name='motor4')
                m5 = Cpt(MMC, ':MOTOR5', name='motor5')
                m6 = Cpt(MMC, ':MOTOR6', name='motor6')
                m7 = Cpt(MMC, ':MOTOR7', name='motor7')
                m8 = Cpt(MMC, ':MOTOR8', name='motor8')
            self.downstream_spec = Polycap('BL152:MC1', name='polycapillary')

