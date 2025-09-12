class Exafs:
    from pcdsdevices.beam_stats import BeamEnergyRequest, BeamEnergyRequestACRWait
    # mirror={'pack3':109.620,'pack2':104.2}
    def set_mirror(pos):
        from mfx.db import mr1l4_homs
        mr1l4_homs.pitch.mv(pos)

    acr_energy_v = BeamEnergyRequestACRWait(
        name='acr_energy',
        prefix='MFX',
        acr_status_suffix='AO805'
    )
    # Second ACR energy using the second set of PVs. Used for the Und K requests
    acr_energy_k = BeamEnergyRequestACRWait(
        name='acr_energy',
        prefix='MFX',
        acr_status_suffix='AO805', pv_index=2
    )

    # ############# LENS STACK  DEFINITION BEGIN #####################
    # sys.path.append('/cds/group/pcds/pyps/apps/hutch-python/mfx/experiments')
    # from lens_for_escan import CcmLens, lens_stack
    #ccm_lens = CcmLens(ccm, lens_stack, name='ccm_lens') # combined ccm and lens motion
    # lens_stack = lens_stack
    # """
    # Comments on the lens stack usage:
    # - The lens stack can be calibrated using lens_stack.align()
    # - The energy (keV) used for the calculation can be set with: lens_stack.energy = <float>
    # - A beam-size (m) at the sample location can be set using lens_stack.beam_size.move(<float>)
    #   This will move (x,y,z) of the lens stack, based on the calibration (align())
    # - If an offset is need, one can play with the z_offset: lens_stack.z_offset
    # - Calculated (x,y,z) postion for a given bemsize can be retrieved lens_stack.forward(beam_size=<float>)
    #   This is a good way to check that the desired position is attainable.
    # """

    # def prepare_lens_stack(self, lens_set=3):
    #     self.lens_stack.set_lens_set(lens_set)
    #     self.lens_stack.energy = ccm.E.get().readback
    #     return

    # def lens_pos_for_energy(self, energy, beamsize):
    #     initial_e = self.lens_stack.energy
    #     self.lens_stack.energy = energy
    #     lens_pos = self.lens_stack.forward(beam_size=beamsize)
    #     self.lens_stack.energy = initial_e
    #     return lens_pos
    # ############# LENS STACK DEFINITION END #####################


    def long_escan(
            self,
            start_eV: float = 0.0,
            end_eV: float = 0.0,
            custom_energies_list=[],
            element: str = 'Fe',
            tag: str = None,
            picker: str = None,
            inspire: bool = False,
            daq_delay: int = 5,
            record: bool = False,
            runs: int = 1,
            k_stepsize: int = 120,
            wait_time: float = 0.2,
            beam_size: bool = None,
            lens_stepsize: float = 0.01,
            reverse: bool = False,
            min_k_keV: float = 7.035,
            k_offset: int = -15,
            debug: bool = False):
        """Perform EXAFS scan.

        Parameters:
            start_eV (float): 
                Photon energy (in eV) to start the scan at.

            end_eV (float): 
                Photon energy (in eV) to end the scan at.

            custom_energies_list: list
                Instead of calculating the energy list you can input a custom one.

            tag: str, optional
                Run group tag/sample name

            picker: str, optional
                If 'open' it opens pp before run starts. If 'flip' it flipflops before run starts

            inspire: bool, optional
                Set false by default because it makes Sandra sad. Set True to inspire

            daq_delay: int, optional
                delay time between runs. Default is 5 second but increase is the DAQ is being slow.

            record (bool): 
                whether to record the scan or not. Optional. Default: False.

            k_stepsize: float
                Stepsize in eV for undulator K motion request.

            wait_time: float, list
                Time to wait at each energy step. If list must the same length as energies.

            beam_size: None or float
                If not None, will move the lens stack to the desired beamsize at each und K step.

            reverse: bool
                To tell the script you will be running from high energies to low energies for K direction consideration.

            k_offset: float
                Offset in eV for undulator K motion request.
        """
        import numpy as np
        import logging
        logger = logging.getLogger(__name__)

        import time
        import os

        from ophyd import EpicsSignal, EpicsSignalRO
        from ophyd import Device, Component

        from pcdsdevices.beam_stats import BeamEnergyRequest, BeamEnergyRequestACRWait
        from pcdsdevices.ccm import CCM as ccm
        from mfx.db import lxt_fast, pp, daq, RE, mr1l4_homs, elog

        import bluesky.plan_stubs as bps
        from bluesky.plan_stubs import abs_set, trigger_and_read
        from bluesky.plans import list_scan, count

        from mfx.autorun import post

        if len(custom_energies_list) == 0:
            from mfx.exafs_energy_range_builder import build_energy_range
            foil_energies = {'Sc': 4492.8, 'Ti': 4966.4, 'V': 5465.1, 'Cr': 5989.2, 'Mn': 6539.0, 'Fe': 7111.2,
                    'Co': 7708.9, 'Ni': 8332.8, 'Cu': 8978.9, 'Zn': 9658.6}

            preedge_end = foil_energies[element] + 7

            calc_energy_range, time_range, energy_K_range, K_values = build_energy_range(
                min_before_pre_edge=start_eV,
                max_before_pre_edge=start_eV + 70,
                preedge_end=preedge_end,
                preedge_eV_increment=0.5,
                max_before_edge=start_eV + 10,
                min_K_value=2.0,
                max_K_value=12.0,
                before_edge_eV_increment=5.0,
                edge_eV_increment=1.0,
                K_spacing=k_stepsize / 1000,
                time_before_edge=0.5,
                time_in_edge = 1,
                time_in_preedge=1.5,
                min_time_EXAFS = 0.5, 
                max_time_EXAFS = 10,
                debug=debug
                )

            energies = calc_energy_range

        else:
            energies = custom_energies_list

        energy_start = ccm.energy_with_vernier.energy()
        k_energy_start = self.acr_energy_k.get().setpoint

        if isinstance(wait_time, float) or isinstance(wait_time, int):
            wait_time = [wait_time] * len(energies)

        if len(wait_time) != len(energies):
            logger.error('Error: len(wait_time) is not equal to len(energies)')
            logger.info('Please pass wait_time as a float or a list of the same length. Exit now.')
            return

        if isinstance(beam_size, float):
            beam_size = [beam_size] * len(energies)

        if beam_size is not None:
            if len(beam_size) != len(energies):
                logger.error('Error: len(beam_size) is not equal to len(energies)')
                logger.info('Please pass beam_size as a float or a list of the same length. Exit now.')
                return

        try:
            energy_0 = energies[0]  # energy at the beginning or after a und K step
            k_energy = energy_0+k_offset
            if reverse:
                energies=energies[::-1]
                energy_0=energies[0]
                k_energy = energy_0 - k_stepsize+k_offset
                logger.info('THE MODE IS REVERSED. FLIPPING ELIST, CLIST, and TLIST.')
                wait_time=wait_time[::-1]
                beam_size=beam_size[::-1]

            logger.info(f"Moving k to initial energy for beginning of scan {k_energy:0.0f}")
            ccm.energy_with_vernier.move(energy_0)
            self.acr_energy_k.move(k_energy)

            for i in range(runs):
                run_number = get_run(station=0) + 1
                from psdaq.control.DaqControl import DaqControl  # NOQA
                daq.control = DaqControl(
                    host=daq.control.host,
                    platform=daq.control.platform,
                    timeout=10000,
                )
                instr = daq.control.getInstrument()
                if instr is None:
                    logger.error('Failed to connect to LCLS-II DAQ')
                    break
                start_state = daq.control.getState()
                if start_state == 'error':
                    logger.error('DAQ is in an error state.')
                    break

                logger.info(f"Run Number {run_number} Running {sample}......{quote()['quote']}")

                daq.control.setState("configured")
                while daq.control.getState() != "configured":
                    ...
                if record:
                    daq.control.setRecord(True)
                else:
                    daq.control.setRecord(False)

                daq.control.setState("running")
                while daq.control.getState() != "running":
                    ...
                start_time = time()
                end_time = start_time + run_length

                for ii, (energy, point_time) in enumerate(zip(energies, wait_time)):
                    logger.info(f"Energy: {energy:0.4f}")

                    # move lens every lens_stepsize
                    if beam_size is not None:
                        if np.abs(self.lens_stack.energy - energy) > lens_stepsize:
                            logger.info(f"Move lens to beamsize={beam_size[ii]}")
                            self.lens_stack.energy = energy + lens_stepsize/2
                            lens_pos = self.lens_stack.forward(beam_size=beam_size[ii])
                            logger.info(f"\nLens moving now to position: {lens_pos}")
                            self.lens_stack.beam_size.move(beam_size[ii])
                                                    #moved_cb=cb_open_beamstop)

                    ccm.energy_with_vernier.move(energy)
                    # if Vernier and ccm need different set point, customize this:
                    #ccm.E.move(energy)
                    #self.acr_energy_v.move(energy*1000)
                    e_step = np.abs(energy - energy_0)

                    # Move K every k_stepsize
                    if e_step > k_stepsize:
                        # if record == True:
                        #     daq.pause()
                        k_energy = energy + k_offset
                        if reverse:
                            k_energy = energy - k_stepsize + k_offset
                            if k_energy/1000 < min_k_keV:
                                k_energy = min_k_keV *1000 +1 #+1 just to be safe. ACR is quite strict on this minimum in seeded mode.

                        logger.info(f"Moving k to {k_energy:0.0f}")
                        time.sleep(0.5)
                        self.acr_energy_k.move(k_energy)
                        energy_0 = energy

                        # if record == True:
                        #     daq.begin(record=True,use_l3t=use_l3t)
                    time.sleep(point_time)

                    daq.control.setState("configured")
                    while daq.control.getState() != "configured":
                        ...

                    if record:
                        post(
                            sample=sample, 
                            tag=tag, 
                            run_number=run_number, 
                            post=record, 
                            inspire=inspire,
                            daq_num=daq_num,)
                    sleep(daq_delay)

        except KeyboardInterrupt:
            daq.control.setState("configured")
            while daq.control.getState() != "configured":
                ...
            daq.control.setRecord(False)
            daq.control.setState("running")
            pp.close()
            if record:
                post(
                    sample=sample, 
                    tag=tag, 
                    run_number=run_number, 
                    post=record, 
                    inspire=inspire,
                    daq_num=daq_num,
                    add_note='Run ended prematurely. Probably sample delivery problem')
            logger.warning("[*] Stopping Run and exiting???...")
            logger.info('Returning to initial position')
            ccm.energy_with_vernier.energy.move(energy_start)
            self.acr_energy_k.move(k_energy_start)
            logger.warning('Run ended prematurely. Probably sample delivery problem')

        pp.close()
        logger.info('Returning to initial position')
        ccm.energy_with_vernier.energy.move(energy_start)
        self.acr_energy_k.move(k_energy_start)
        daq.control.setState("configured")
        while daq.control.getState() != "configured":
            ...
        daq.control.setRecord(False)
        daq.control.setState("running")
        logger.warning('Finished with all runs thank you for choosing the MFX beamline!\n')
        return


    def continuous_ccmscan(
            self,
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
        import time
        from pcdsdevices.ccm import CCM as ccm
        from mfx.db import daq
        import logging
        logger = logging.getLogger(__name__)

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
                logger.error(f"\nKeyboardInterrupt received. Run is paused at energy {current_energy}.")
                inp = input("Type \"q\" to finish the run or \"r\" to resume acquisition\n")

            if inp == 'q':
                logger.info('\nScan end signal received.')
                ccm_e.move(initial_energy)
            elif inp == 'r':
                idx = np.where( np.isclose(energies, current_energy, atol=5e-3) )[0][0]
                #idx = np.where(energies >= current_energy)[0]
                energies = energies[idx:]
                logger.info(f"Resuming scan with energies: {energies}")
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
            logger.info(f'Returning ccm to energy before scan: {initial_energy}')
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
        logger.info('Set current stage position {}, encoder value {} to 0'.format(currentpos,currentenc.pos))
        lxt_fast.set_current_position(0)
        lxt_fast_enc.set_zero()
        return
