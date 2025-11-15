import logging
import numpy as np
import os
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
from hutch_python.utils import safe_load
with safe_load('DCCM'):
    from mfx.dccm import DCCM
    dccm = DCCM(name='DCCM')

def continuous_dccmscan(energies, pointTime=1, move_vernier=False, bidirectional=False):
    initial_energy=dccm.energy.wm()
    try:
        for E in energies:
            if move_vernier:
                dccm.energy_with_vernier(E)
                print(f'Moving DCCM with vernier to {E}')
            else:
                dccm.energy(E)
                print(f'Moving DCCM to {E}')
        time.sleep(pointTime)
        if bidirectional:
            for E in energies[::-1]:
                if move_vernier:
                    dccm.energy_with_vernier(E)
                    print(f'Moving DCCM with vernier to {E}')
                else:
                    dccm.energy(E)
                    print(f'Moving DCCM to {E}')
        time.sleep(pointTime)

    except KeyboardInterrupt:
        print(f'Scan end signal received. Returning ccm to energy before scan: {initial_energy}')
        dccm_e_vernier(initial_energy)
        print(f'Moving ccm.E_Vernier to {initial_energy}')
    finally:
        if move_vernier:
            dccm.energy_with_vernier(initial_energy)
            print(f'Moving back initial energy to {initial_energy}')
        else:
            dccm.energy(initial_energy)
            print(f'Moving back initial energy to {initial_energy}')
        time.sleep(pointTime)

def run_dccmscan(energies, record=True,  pointTime=1,  move_vernier=True,bidirectional=False,**kwargs):
        logger.info("Starting DAQ run, -> record=%s", record)
        daq.configure()
        try:
            #start DAQ, then start scanning
            daq.begin_infinite(record=record) #note we do not specify # of events, so it records until we stop
            runnum = daq._control.runnumber()
            time.sleep(1) # give DAQ a second
            continuous_dccmscan(energies, pointTime=pointTime, move_vernier=move_vernier,bidirectional=bidirectional)
        except KeyboardInterrupt:
            print('Interrupt signal received. Stopping run and DAQ')
        finally:
            daq.end_run()
            logger.info("Run complete!")
            #daq.disconnect()

