import sys
import numpy as np
import logging
import time
import os

from ophyd import EpicsSignal, EpicsSignalRO
from ophyd import Device, Component

from pcdsdevices.beam_stats import BeamEnergyRequest, BeamEnergyRequestACRWait

try:
    from xcs.db import elog
except:
    print("Cannot import elog for now. Perhaps run as opr?")
from xcs.db import xcs_pulsepicker as pp
from xcs.db import xcs_ccm as ccm
from xcs.db import daq,mr2l3_homs
from xcs.db import RE
from xcs.db import lxt_fast, lxt_fast_enc

sys.path.append('/cds/group/pcds/pyps/apps/hutch-python/xcs/experiments')
from lens_for_escan import CcmLens, lens_stack
import bluesky.plan_stubs as bps
from bluesky.plan_stubs import abs_set, trigger_and_read
from bluesky.plans import list_scan, count

class User:
    mirror={'pack3':109.620,'pack2':104.2}
    def set_mirror(pack):
        mr2l3_homs.pitch.mv(pack)

    acr_energy_v = BeamEnergyRequestACRWait(
        name='acr_energy',
        prefix='XCS',
        acr_status_suffix='AO805'
    ) # AO801 for SXR
    # Second ACR energy using the second set of PVs. Used for the Und K requests
    acr_energy_k = BeamEnergyRequestACRWait(
        name='acr_energy',
        prefix='XCS',
        acr_status_suffix='AO805', pv_index=2
    )

    # ############# LENS STACK  DEFINITION BEGIN #####################
    #ccm_lens = CcmLens(ccm, lens_stack, name='ccm_lens') # combined ccm and lens motion
    lens_stack = lens_stack
    """
    Comments on the lens stack usage:
    - The lens stack can be calibrated using lens_stack.align()
    - The energy (keV) used for the calculation can be set with: lens_stack.energy = <float>
    - A beam-size (m) at the sample location can be set using lens_stack.beam_size.move(<float>)
      This will move (x,y,z) of the lens stack, based on the calibration (align())
    - If an offset is need, one can play with the z_offset: lens_stack.z_offset
    - Calculated (x,y,z) postion for a given bemsize can be retrieved lens_stack.forward(beam_size=<float>)
      This is a good way to check that the desired position is attainable.
    """

    def prepare_lens_stack(self, lens_set=3):
        self.lens_stack.set_lens_set(lens_set)
        self.lens_stack.energy = ccm.E.get().readback
        return

    def lens_pos_for_energy(self, energy, beamsize):
        initial_e = self.lens_stack.energy
        self.lens_stack.energy = energy
        lens_pos = self.lens_stack.forward(beam_size=beamsize)
        self.lens_stack.energy = initial_e
        return lens_pos
    # ############# LENS STACK DEFINITION END #####################

    def long_escan(self,
                   energies=[],
                   k_stepsize=0.1,
                   record=False,
                   wait_time=0.2,
                   beam_size=None,
                   lens_stepsize=0.01,
                   use_l3t=False,
                   reverse=False,
                   min_k_keV=7.035,
                   k_offset=-0.015):
        """
        energies: list, np.ndarray
            Energies point to go over.
        k_stepsize: float
            Stepsize in keV for undulator K motion request.
        record: bool
            Record with the DAQ
        wait_time: float, list
            Time to wait at each energy step. If list must the same length as energies.
        beam_size: None or float
            If not None, will move the lens stack to the desired beamsize at each und K step.
        reverse: bool
            To tell the script you will be running from high energies to low energies for K direction consideration.

        Comment / questions:
            Do we want to move the lens at the same k_stepsize? That's probably
            the best way, unless we need to move the lens more often than that?
        """
        energy_start = ccm.energy_with_vernier.energy()
        k_energy_start = self.acr_energy_k.get().setpoint

        if isinstance(wait_time, float) or isinstance(wait_time, int):
            wait_time = [wait_time] * len(energies)

        if len(wait_time) != len(energies):
            print('Error: len(wait_time) is not equal to len(energies)')
            print('Please pass wait_time as a float or a list of the same length. Exit now.')
            return

        if isinstance(beam_size, float):
            beam_size = [beam_size] * len(energies)

        if beam_size is not None:
            if len(beam_size) != len(energies):
                print('Error: len(beam_size) is not equal to len(energies)')
                print('Please pass beam_size as a float or a list of the same length. Exit now.')
                return

        try:
            energy_0 = energies[0]  # energy at the beginning or after a und K step
            k_energy = (energy_0+k_offset ) * 1000
            if reverse:
                energies=energies[::-1]
                energy_0=energies[0]
                k_energy = (energy_0 - k_stepsize+k_offset) * 1000
                print('THE MODE IS REVERSED. FLIPPING ELIST, CLIST, and TLIST.')
                wait_time=wait_time[::-1]
                beam_size=beam_size[::-1]

            print(f"Moving k to initial energy for beginning of scan {k_energy:0.0f}")
            ccm.energy_with_vernier.move(energy_0)
            self.acr_energy_k.move(k_energy)


            if record == True:
                daq.configure(record=True, use_l3t=use_l3t)
                daq.begin(record=True, use_l3t=use_l3t)

            for ii, (energy, point_time) in enumerate(zip(energies, wait_time)):
                print(f"Energy: {energy:0.4f}")

                # move lens every lens_stepsize
                if beam_size is not None:
                    if np.abs(self.lens_stack.energy - energy) > lens_stepsize:
                        print(f"Move lens to beamsize={beam_size[ii]}")
                        self.lens_stack.energy = energy + lens_stepsize/2
                        lens_pos = self.lens_stack.forward(beam_size=beam_size[ii])
                        print(f"\nLens moving now to position: {lens_pos}")
                        self.lens_stack.beam_size.move(beam_size[ii])
                                                   #moved_cb=cb_open_beamstop)

                ccm.energy_with_vernier.move(energy)
		# if Vernier and ccm need different set point, customize this:
		#ccm.E.move(energy)
		#self.acr_energy_v.move(energy*1000)
                e_step = np.abs(energy - energy_0)

                # Move K every k_stepsize
                if e_step > k_stepsize:
                    if record == True:
                        daq.pause()
                    k_energy = (energy + k_offset) * 1000
                    if reverse:
                        k_energy = (energy - k_stepsize + k_offset) * 1000
                        if k_energy/1000 < min_k_keV:
                            k_energy = min_k_keV *1000 +1 #+1 just to be safe. ACR is quite strict on this minimum in seeded mode.


                    print(f"Moving k to {k_energy:0.0f}")
                    time.sleep(0.5)
                    self.acr_energy_k.move(k_energy)
                    energy_0 = energy

                    if record == True:
                        daq.begin(record=True,use_l3t=use_l3t)
                time.sleep(point_time)

            if record == True:
                daq.end_run()

        except Exception as err:
            print("Error: ")
            print(err)
            if record == True:
                daq.end_run()

        finally:
            print('Returning to initial position')
            ccm.energy_with_vernier.energy.move(energy_start)
            self.acr_energy_k.move(k_energy_start)
            daq.disconnect()
        return



    def continuous_ccmscan(self,
                           energies,
                           pointTime=1,
                           move_vernier=True,
                           wait_acr=False,
                           bidirectional=False,
                           is_daq=False,
                           initial_energy=None):
        """
        Scan the CCM

        Parameters
        ----------
        energies: list, np.ndarray
            Energies point to go over
        pointTime: float, default=1
            Time in second to spend at each point
        move_vernier: bool, default=True
            Does an energy request to ACR as the ccm is moved.
        wait_acr: bool, default=False
            Wait for ACR to return the done move status after an energy
            request change was made. Useful for slow motion (undulator)
        bidirectional: bool, default=False
        """
        if wait_acr:
            ccm_e = ccm.energy_with_acr_status
        elif move_vernier:
            ccm_e = ccm.energy_with_vernier
        else:
            ccm_e = ccm.energy

        if initial_energy is None:
            initial_energy = ccm_e.energy.position

        try:
            self.ccm_sweep(ccm_e, energies, pointTime)
            if bidirectional:
                energies = energies[::-1]
                self.ccm_sweep(ccm_e, energies, pointTime)

        except KeyboardInterrupt:
            # Handle pausing or stopping the ccm scan.
            inp = 'q'
            if is_daq:
                daq.pause()
                current_energy = ccm_e.energy.position
                print(f"\nKeyboardInterrupt received. Run is paused at energy {current_energy}.")
                inp = input("Type \"q\" to finish the run or \"r\" to resume acquisition\n")

            if inp == 'q':
                print('\nScan end signal received.')
                ccm_e.move(initial_energy)
            elif inp == 'r':
                idx = np.where( np.isclose(energies, current_energy, atol=5e-3) )[0][0]
                #idx = np.where(energies >= current_energy)[0]
                energies = energies[idx:]
                print(f"Resuming scan with energies: {energies}")
                daq.resume()
                self.continuous_ccmscan(
                    energies,
                    pointTime=pointTime,
                    move_vernier=move_vernier,
                    wait_acr=wait_acr,
                    bidirectional=bidirectional,
                    is_daq=is_daq,
                    initial_energy=initial_energy
                )

        finally:
            print(f'Returning ccm to energy before scan: {initial_energy}')
            ccm_e.move(initial_energy)
            time.sleep(pointTime)
        return


    @staticmethod
    def ccm_sweep(ccm_e, energies, pointTime):
        for E in energies:
            ccm_e.move(E)
            time.sleep(pointTime)
        return



    def cb_open_beamstop(self, obj):
        """
        Callback function to open the attenuator at the end of a move.
        If the atttenuator is used, this function assumes that the blade 9
        is used to block the beam.
        """
        if 'Attenuator' in lens_stack._att_obj.__class__.__name__:
            lens_stack._att_obj.filters[9].remove()
        elif 'PulsePicker' in lens_stack._att_obj.__class__.__name__:
            lens_stack._att_obj.open()
        return
 
    def lxt_fast_set_absolute_zero(self):
        currentpos = lxt_fast()
        currentenc = lxt_fast_enc.get()
        #elog.post('Set current stage position {}, encoder value {} to 0'.format(currentpos,currentenc.pos))
        print('Set current stage position {}, encoder value {} to 0'.format(currentpos,currentenc.pos))
        lxt_fast.set_current_position(0)
        lxt_fast_enc.set_zero()
        return

    def knife_edge(self,det,motor,start,stop,steps,n,guess): #n=#of measurements at each step
        from databroker import Broker
        import numpy as np
        from scipy.optimize import minimize
        import matplotlib.pyplot as plt
        from bluesky.preprocessors import run_decorator

        print("Doing knife edge laser scan on motor:", motor)
        ljh_jet_x=EpicsSignal('XCS:LJH:JET:X')
        labmax=EpicsSignal('XCS:LPW:01:DATA_PRI')


        #@run_decorator(md={})
        def labmax_range_scan(detector, motor, positions):
            #yield from bps.open_run()
            #try:
            for pos in positions:
                # Move motor to the next position
                yield from abs_set(ljh_jet_x, pos, wait=True)

                # Trigger the detector and read its value
                yield from count([detector])
                det_value = list(detector.read().values())[0]['value']

                # Apply conditional logic based on detector value using epics.caput                                     
                if det_value < 3e-06:
                    # Set labmax range
                    os.system('caput XCS:LPW:01:SETRANGE 3e-06') 
                else:
                    # Set labmax range
                    os.system('caput XCS:LPW:01:SETRANGE 3e-05')

                    # Read the detector again after setting change                                                     
                yield from count([detector]) 
            print("closing run")
            #yield from bps.close_run()
            #print("run closed")
        

        positions = np.repeat(np.linspace(start,stop,steps),n)
        print("positions",positions)
        db = Broker.named('temp')
        RE.subscribe(db.insert)
        uid,=RE(labmax_range_scan(labmax, motor, positions)) #motor                                                                                                              
        header = db[-1]
        t = header.table()

        print('ljh_jet_x',t['ljh_jet_x'])
        print('det',t['XCS:LPW:01:DATA_PRI'])
        
        def cauchy_loss(params, x, y, c):
            A, mu, sigma = params
            y_pred = A * np.exp(-(x - mu)**2 / (2 * sigma**2))
            residual = y - y_pred
            return np.log(1 + (residual / c)**2).sum()

        # Function to define the Gaussian function for curve fitting                                                                                                       
        def gauss(params, x):
            A, mu, sigma = params
            return A * np.exp(-(x - mu)**2 / (2 * sigma**2))

        # Objective function for optimization                                                                                                                              
        def objective(params, x, y, c):
            return cauchy_loss(params, x, y, c)

        # Initial guess for parameters                                                                                                                                     
        initial_guess = [0.01, np.mean(t['ljh_jet_x']), 0.001*guess]

        print("initial guess", initial_guess)

        power = header.data('XCS:LPW:01:DATA_PRI')
        position = header.data('ljh_jet_x')


        # Perform optimization                                                                                                                                             
        #result = minimize(objective, initial_guess, args=(power_arr, pos_arr, 1))                                                                                         
        result = minimize(objective, initial_guess, args=(t['ljh_jet_x'], t['XCS:LPW:01:DATA_PRI'], 1))

        # Extract optimized parameters                                                                                                                                     
        popt = result.x
        #print("popt", popt)                                                                                                                                               

        # Calculating the full width at half maximum (FWHM)                                                                                                                
        FWHM = 2 * np.sqrt(2 * np.log(2)) * popt[2]
        print("The FWHM is:", FWHM*1000, "um")

        # Plotting the data and the fit                                                                                                                                    
        fig2 = plt.figure("Knife Edge Scan")
        plt.plot(t['ljh_jet_x'], t['XCS:LPW:01:DATA_PRI'], 'b.', label='Measurement Data')
        plt.plot(t['ljh_jet_x'], gauss(popt, t['ljh_jet_x']), 'r-', label='Gaussian Fit')
        plt.xlabel('Position [mm]')
        plt.ylabel('Intensity [J]')
        plt.title('Edge Profile with Gaussian Fit (robust, Cauchy loss)')
        plt.legend()
        plt.show()
