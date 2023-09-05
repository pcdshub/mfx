from subprocess import check_output

import json
import sys
import time
import os

import numpy as np
from ophyd import EpicsSignalRO
from ophyd import EpicsSignal
from bluesky import RunEngine
from bluesky.plans import scan
from bluesky.plans import listscan
from ophyd import Component as Cpt
from ophyd import Device
from pcdsdevices.interface import BaseInterface
from pcdsdevices.areadetector import plugins
from mfx.db import daq
from mfx.db import camviewer
from mfx.db import RE
from mfx.db import at2l0
#move this to beamline with the most typical detectors.
from pcdsdaq.ami import AmiDet

import sys
sys.path.append('/reg/neh/home/seaberg/Python/lcls_beamline_toolbox/')
from lcls_beamline_toolbox.xrayinteraction import interaction
from lcls_beamline_toolbox.xraybeamline2d import optics


class FEEAlign:
    def __init__(self, im1, im2, im3, im4, mr1, mr2):
        pass


class AT2L0:

    def __init__(self, att):
        self.att = att
        self.blades = {}
        self.blades[2] = {'material': 'diamond', 'thickness': 1280}
        self.blades[3] = {'material': 'diamond', 'thickness': 640}
        self.blades[4] = {'material': 'diamond', 'thickness': 320}
        self.blades[5] = {'material': 'diamond', 'thickness': 160}
        self.blades[6] = {'material': 'diamond', 'thickness': 80}
        self.blades[7] = {'material': 'diamond', 'thickness': 40}
        self.blades[8] = {'material': 'diamond', 'thickness': 20}
        self.blades[9] = {'material': 'diamond', 'thickness': 10}
        self.blades[10] = {'material': 'silicon', 'thickness': 10240}
        self.blades[11] = {'material': 'silicon', 'thickness': 5120}
        self.blades[12] = {'material': 'silicon', 'thickness': 2560}
        self.blades[13] = {'material': 'silicon', 'thickness': 1280}
        self.blades[14] = {'material': 'silicon', 'thickness': 640}
        self.blades[15] = {'material': 'silicon', 'thickness': 320}
        self.blades[16] = {'material': 'silicon', 'thickness': 160}
        self.blades[17] = {'material': 'silicon', 'thickness': 80}
        self.blades[18] = {'material': 'silicon', 'thickness': 40}
        self.blades[19] = {'material': 'silicon', 'thickness': 20}
        self.silicon = interaction.Device('silicon', range='HXR', material='Si', thickness=0)
        self.diamond = interaction.Device('diamond', range='HXR', material='CVD', thickness=0)

        self.max_diamond = 2550
        self.max_silicon = 20460

        self.blade_motors = {}
        for i in range(2,20):
            if i < 10:
                bladeNum = '0%d' % i
            else:
                bladeNum = '%d' % i
            blade = getattr(self.att, 'blade_%s' % bladeNum)

            self.blade_motors[i] = blade


    def get_diamond_thickness(self):

        total_thickness = 0

        for i in range(2, 10):
            # check if inserted

            if self.blade_motors[i]() < 1:
                total_thickness += self.blades[i]['thickness']

        return total_thickness

    def get_silicon_thickness(self):
        total_thickness = 0

        for i in range(10, 20):
            # check if inserted

            if self.blade_motors[i]() < 1:
                total_thickness += self.blades[i]['thickness']

        return total_thickness


    def _get_thickness_both(self, transmission, E):
        """
        Calculate silicon thickness in microns to achieve the desired transmission
        """
        diamond_thickness = self.diamond.get_thickness(transmission, E*1e3)*1e6
        if diamond_thickness > self.max_diamond:
            diamond_thickness = self.max_diamond

        Td = self.diamond.transmission(thickness=diamond_thickness*1e-6)

        energy = self.diamond.energy
        Td = np.interp(E*1e3, energy, Td)
        
        Ts = transmission / Td

        silicon_thickness = self.silicon.get_thickness(Ts, E*1e3)*1e6

        return diamond_thickness, silicon_thickness

    def _get_thickness(self, transmission, E):
        """
        Calculate silicon thickness in microns to achieve the desired transmission
        """
        thickness = self.silicon.get_thickness(transmission, E*1e3)*1e6

        return thickness

    def blade_insertions(self, transmission, E):
        d_thickness, s_thickness = self._get_thickness_both(transmission, E)

        # figure out binary representation of transmission with powers of 2
        d_multiplier = d_thickness/10
        d_multiplier = int(d_multiplier)
        print(np.binary_repr(int(d_multiplier), width=8))

        d_blade_insertions = np.binary_repr(d_multiplier, width=8)
        
        # figure out binary representation of transmission with powers of 2
        s_multiplier = s_thickness/20
        s_multiplier = int(s_multiplier)
        print(s_multiplier)
        print(np.binary_repr(int(s_multiplier), width=10))

        s_blade_insertions = np.binary_repr(s_multiplier, width=10)

        return d_blade_insertions, s_blade_insertions

    def set_silicon_thickness(self, thickness):
        """
        Insert silicon blades

        :param thickness: total thickness in microns
        """
        # figure out binary representation of transmission with powers of 2
        s_multiplier = thickness/20
        s_multiplier = int(s_multiplier)
        print(np.binary_repr(int(s_multiplier), width=10))
        print('closest available thickness: %d \u03BCm' % (s_multiplier*20))

        s_blade_insertions = np.binary_repr(s_multiplier, width=10)

        # insert silicon
        for i in range(10):
            index = i+10
            if s_blade_insertions[i] == '1':
                print('blade %s should be in' % index)
                self.blade_motors[index].user_offset_dir.set(0)
                self.blade_motors[index].user_offset.set(0)
                self.blade_motors[index].user_setpoint.set(0)
            else:
                self.blade_motors[index].user_offset_dir.set(0)
                self.blade_motors[index].user_offset.set(0)
                self.blade_motors[index].user_setpoint.set(24)
                print('blade %s should be out' % index)
            #if self.blade_motors[index]()>23:
            #    print('blade %s is out' % index)
            #elif self.blade_motors[index]()<1:
            #    print('blade %s is in' % index)

    def set_diamond_thickness(self, thickness):
        """
        Insert diamond blades

        :param thickness: total thickness in microns
        """

        # figure out binary representation of transmission with powers of 2
        d_multiplier = thickness/10
        d_multiplier = int(d_multiplier)
        print(np.binary_repr(int(d_multiplier), width=8))
        print('closest available thickness: %d \u03BCm' % (d_multiplier*10))

        d_blade_insertions = np.binary_repr(d_multiplier, width=8)
        
        # insert diamond
        for i in range(8):
            index = i+2
            if d_blade_insertions[i] == '1':
                print('blade %s should be in' % index)
                self.blade_motors[index].user_offset_dir.set(0)
                self.blade_motors[index].user_offset.set(0)
                self.blade_motors[index].user_setpoint.set(0)
            else:
                self.blade_motors[index].user_offset_dir.set(0)
                self.blade_motors[index].user_offset.set(0)
                self.blade_motors[index].user_setpoint.set(24)
                print('blade %s should be out' % index)
            #if self.blade_motors[index]()>23:
            #    print('blade %s is out' % index)
            #elif self.blade_motors[index]()<1:
            #    print('blade %s is in' % index)


    def set_transmission(self, transmission, E): 
        """
        Function to set the transmission of AT2L0 using both diamond and silicon
        """

        tic = time.perf_counter()
        d_thickness, s_thickness = self._get_thickness_both(transmission, E)

        # figure out binary representation of transmission with powers of 2
        d_multiplier = d_thickness/10
        d_multiplier = int(d_multiplier)
        print(np.binary_repr(int(d_multiplier), width=8))

        d_blade_insertions = np.binary_repr(d_multiplier, width=8)
        
        # figure out binary representation of transmission with powers of 2
        s_multiplier = s_thickness/20
        s_multiplier = int(s_multiplier)
        print(s_multiplier)
        print(np.binary_repr(int(s_multiplier), width=10))

        s_blade_insertions = np.binary_repr(s_multiplier, width=10)

        toc = time.perf_counter()
        print('took %.4f seconds to calculate configuration' % (toc-tic))

        # insert diamond
        for i in range(8):
            index = i+2
            if d_blade_insertions[i] == '1':
                print('blade %s should be in' % index)
                self.blade_motors[index].user_offset_dir.set(0)
                self.blade_motors[index].user_offset.set(0)
                self.blade_motors[index].user_setpoint.set(0)
            else:
                self.blade_motors[index].user_offset_dir.set(0)
                self.blade_motors[index].user_offset.set(0)
                self.blade_motors[index].user_setpoint.set(24)
                print('blade %s should be out' % index)
            #if self.blade_motors[index]()>23:
            #    print('blade %s is out' % index)
            #elif self.blade_motors[index]()<1:
            #    print('blade %s is in' % index)
        
        # insert silicon
        for i in range(10):
            index = i+10
            if s_blade_insertions[i] == '1':
                print('blade %s should be in' % index)
                self.blade_motors[index].user_offset_dir.set(0)
                self.blade_motors[index].user_offset.set(0)
                self.blade_motors[index].user_setpoint.set(0)
            else:
                self.blade_motors[index].user_offset_dir.set(0)
                self.blade_motors[index].user_offset.set(0)
                self.blade_motors[index].user_setpoint.set(24)
                print('blade %s should be out' % index)
            #if self.blade_motors[index]()>23:
            #    print('blade %s is out' % index)
            #elif self.blade_motors[index]()<1:
            #    print('blade %s is in' % index)

    def set_Si_transmission(self, transmission, E):
        """
        Function to set the transmission of AT2L0
        """
        thickness = self._get_thickness(transmission, E)

        # figure out binary representation of transmission with powers of 2
        multiplier = thickness/20
        multiplier = int(multiplier)
        print(np.binary_repr(int(multiplier), width=10))

        blade_insertions = np.binary_repr(multiplier, width=10)

        for i in range(10):
            index = i+10
            if blade_insertions[i] == '1':
                print('blade %s should be in' % index)
                self.blade_motors[index].user_offset_dir.set(0)
                self.blade_motors[index].user_offset.set(0)
                self.blade_motors[index].user_setpoint.set(0)
            else:
                self.blade_motors[index].user_offset_dir.set(0)
                self.blade_motors[index].user_offset.set(0)
                self.blade_motors[index].user_setpoint.set(24)
                print('blade %s should be out' % index)
            #if self.blade_motors[index]()>23:
            #    print('blade %s is out' % index)
            #elif self.blade_motors[index]()<1:
            #    print('blade %s is in' % index)

    def get_transmission(self, E):
        """
        total transmission through solid attenuator

        :param E: float
            photon energy to calculate for in keV
        :return transmission: float
            total transmission
        """
        # get silicon thickness
        total_silicon = self.get_silicon_thickness()
        # get diamond thickness
        total_diamond = self.get_diamond_thickness()

        Ts = self.silicon.transmission(thickness=total_silicon*1e-6)
        Td = self.diamond.transmission(thickness=total_diamond*1e-6)

        T = Ts*Td
        # get energy array
        energy = self.silicon.energy
        # interpolate
        T_E = np.interp(E*1e3, energy, T)
        T_2 = np.interp(E*1e3*2, energy, T)
        T_3 = np.interp(E*1e3*3, energy, T)

        print('Fundamental transmission: %.2e' % T_E)
        print('2nd harmonic transmission: %.2e' % T_2)
        print('3rd harmonic transmission: %.2e' % T_3)
        
        return T_E


class AT1L0(Device, BaseInterface):
    energy = EpicsSignalRO('SATT:FEE1:320:ETOA.E', kind='config')
    attenuation = EpicsSignalRO('SATT:FEE1:320:RACT', kind='hinted')
    transmission = EpicsSignalRO('SATT:FEE1:320:TACT', name='normal')
    r_des = EpicsSignal('SATT:FEE1:320:RDES', name='normal')
    r_floor = EpicsSignal('SATT:FEE1:320:R_FLOOR', name='omitted')
    r_ceiling = EpicsSignal('SATT:FEE1:320:R_CEIL', name='omitted')
    trans_floor = EpicsSignal('SATT:FEE1:320:T_FLOOR', name='omitted')
    trans_ceiling = EpicsSignal('SATT:FEE1:320:T_CEIL', name='omitted')
    go = EpicsSignal('SATT:FEE1:320:GO', name='omitted')
    
    def setR(self, att_des, ask=False, wait=True):
        self.att_des.put(att_des)
        if ask:
            print('possible ratios: %g (F) -  %g (C)'%(self.r_floor, self.r_ceiling))
            answer=raw_input('F/C? ')
        if answer=='C':
            self.go.put(2)
            if wait: time.sleep(5)
        else:
            self.go.put(3)
            if wait: time.sleep(5)        

class User():
    def __init__(self):
        try:
            self.at2l0 = AT2L0(at2l0)
        except:
            self.at2l0 = None
        self.at1l0 = AT1L0(name='at1l0')

    def takeRun(self, nEvents, record=True):
        daq.configure(events=120, record=record)
        daq.begin(events=nEvents)
        daq.wait()
        daq.end_run()

    def get_ascan(self, motor, start, end, nsteps, nEvents, record=True):
        daq.configure(nEvents, record=record, controls=[motor])
        return scan([daq], motor, start, end, nsteps)

    def get_dscan(self, motor, start, end, nsteps, nEvents, record=True):
        daq.configure(nEvents, record=record)
        currPos = motor.wm()
        return scan([daq], motor, currPos+start, currPos+end, nsteps)

    def ascan(self, motor, start, end, nsteps, nEvents, record=True):
        daq.configure(nEvents, record=record, controls=[motor])
        RE(scan([daq], motor, start, end, nsteps))

    def dscan(self, motor, start, end, nsteps, nEvents, record=True):
        daq.configure(nEvents, record=record, controls=[motor])
        currPos = motor.wm()
        RE(scan([daq], motor, currPos+start, currPos+end, nsteps))

    def listscan(self, motor, posList, nEvents, record=True):
        daq.configure(nEvents, record=record, controls=[motor])
        RE(list_scan([daq], motor, posList))


    #def a2scan(self, m1, a1, b1, m2, a2, b2, nsteps, nEvents, record=True):
    #    daq.configure(nEvents, record=record, controls=[m1, m2])
    #    RE(scan([daq], m1, a1, b1, m2, a2, b2, num=nsteps))

