class Exafs:
    from pcdsdevices.beam_stats import BeamEnergyRequest, BeamEnergyRequestACRWait
    from ophyd import EpicsSignalRO
    from hutch_python import sim

    def __init__(self):
        self.exafs_energy_range_builder = EXAFSEnergyRangeBuilder()

    sim = sim.get_hw()
    # DG1 IPM SUM PV (read-only)
    ipm_sum = EpicsSignalRO("MFX:DG1:W8:01:SUM", name="dg1_sum")

    best = {"i0": float("-inf"), "eV": None}

    def on_event(self, name, doc):
        if name != "event":
            return
        data = doc.get("data", {})
        if "mcc" not in data:
            return
        eV = data["mcc"]  # vernier setpoint (eV) at this step
        i0 = float(ipm_sum.get())  # <-- reads MFX:DG1:W8:01:SUM
        if i0 > best["i0"]:
            best["i0"] = i0
            best["eV"] = eV

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


    def _build_energy_and_wait_time(self, energies_list, wait_time_list, start_eV, end_eV, min_k, max_k, element, debug):
        """Build energy and wait time lists for EXAFS scan."""
        import numpy as np
        import logging
        logger = logging.getLogger(__name__)
        import sys
        
        if len(energies_list) == 0 or len(wait_time_list) == 0:
            #from mfx.exafs_energy_range_builder import EXAFSEnergyRangeBuilder
            EXAFSEnergyRangeBuilder = self.exafs_energy_range_builder #EXAFSEnergyRangeBuilder()
            foil_energies = {'Sc': 4492.8, 'Ti': 4966.4, 'V': 5465.1, 'Cr': 5989.2, 'Mn': 6539.0, 'Fe': 7111.2,
                    'Co': 7708.9, 'Ni': 8332.8, 'Cu': 8978.9, 'Zn': 9658.6}
            threshold_energies = {'Ti': 4985.00, 'Sc': 4510.00, 'V': 5485.00, 'Cr': 6010.00, 'Mn': 6560.00,
                    'Fe': 7130.00, 'Co': 7730.00, 'Ni': 8350.00, 'Cu': 9000.00, 'Zn': 9680.00}

            preedge_end = foil_energies[element] + 7
            if end_eV is not None:
                if end_eV <= threshold_energies[element]:
                    min_k = max_k = 0.0
                if end_eV > threshold_energies[element]:
                    max_k = (0.2625 * (end_eV - threshold_energies[element]))**0.5

            energies, wait_time, energy_K_range, K_values = EXAFSEnergyRangeBuilder.build_energy_range(
                min_before_pre_edge=start_eV,
                max_before_pre_edge=start_eV + 70,
                preedge_end=preedge_end,
                preedge_eV_increment=0.5,
                max_before_edge=start_eV + 10,
                min_K_value=min_k,
                max_K_value=max_k,
                before_edge_eV_increment=5.0,
                edge_eV_increment=1.0,
                K_spacing=0.1,
                time_before_edge=0.5,
                time_in_edge = 1,
                time_in_preedge=1.5,
                min_time_EXAFS = 0.5, 
                max_time_EXAFS = 10,
                debug=debug
                )
            if debug:
                logging.warning(f"Would you like to continue?")
                answer = input("(y/n)? ")

                if answer.lower() == "n":
                    logging.error(f"Fine. Exiting...")
                    sys.exit()
        else:
            energies = energies_list
            wait_time = wait_time_list

        if len(wait_time) != len(energies):
            logger.error('Error: len(wait_time) is not equal to len(energies)')
            logger.info('Please pass wait_time as a float or a list of the same length. Exit now.')
            raise ValueError('len(wait_time) is not equal to len(energies)')

        return energies, wait_time

    def _initialize_energies_and_move(self, energies, wait_time, reverse, k_offset, k_stepsize, simulate):
        """Initialize energy values for the scan."""
        import logging
        logger = logging.getLogger(__name__)
        from hutch_python import sim
        from mfx.dccm import DCCM
        
        energy_0 = energies[0]/1000.0  # energy at the beginning or after a und K step
        k_energy = energy_0 * 1000.0 + k_offset
        if reverse:
            energies=energies[::-1]
            energy_0=energies[0]/1000.0
            k_energy = energy_0 * 1000.0 - k_stepsize + k_offset
            logger.info('THE MODE IS REVERSED. FLIPPING ELIST, CLIST, and TLIST.')
            wait_time=wait_time[::-1]
        
        sim_hw = sim.get_hw()
        dccm = DCCM(name='DCCM')
        
        # Move energy motor
        if simulate:
            sim_hw.fast_motor1.mv(energy_0)
        else: 
            dccm.energy_with_vernier(energy_0)
            
        # Move K motor
        logger.info(f"Moving k to initial energy for beginning of scan {k_energy:0.0f}")
        if round(k_energy, 1) != round(self.acr_energy_k.get().setpoint, 1):
            if simulate: 
                sim_hw.slow_motor1.mv(k_energy)
            else: 
                self.acr_energy_k.move(k_energy)
            
        return energies, energy_0, k_energy, wait_time

    def _setup_daq_and_start_recording(self, sample, picker, inspire, record, simulate, run_index):
        """Setup DAQ and start recording."""
        import logging
        logger = logging.getLogger(__name__)
        
        if simulate:
            # In simulation mode, just return a run number
            run_number = run_index + 1
            return run_number, True
        
        # Real mode - setup DAQ
        from mfx.db import daq, pp
        from mfx.macros import get_run
        from mfx.autorun import quote
        from psdaq.control.DaqControl import DaqControl
        
        run_number = get_run(station=0) + 1
        daq.control = DaqControl(
            host=daq.control.host,
            platform=daq.control.platform,
            timeout=10000,
        )
        instr = daq.control.getInstrument()
        if instr is None:
            logger.error('Failed to connect to LCLS-II DAQ')
            return None, False
        start_state = daq.control.getState()
        if start_state == 'error':
            logger.error('DAQ is in an error state.')
            return None, False

        logger.info(f"Run Number {run_number} Running {sample}......{quote()['quote']}")
        if sample.lower()=='water' or sample.lower()=='h2o':
            inspire=True
        if picker=='open':
            pp.open()
        if picker=='flip':
            pp.flipflop()

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
            
        return run_number, True

    def _move_energy_simulation_or_real(self, energy, simulate):
        """Move energy either in simulation or real mode."""
        from hutch_python import sim
        from mfx.dccm import DCCM
        
        sim_hw = sim.get_hw()
        dccm = DCCM(name='DCCM')
        
        if simulate:
            sim_hw.fast_motor1.mv(energy)
        else:
            dccm.energy_with_vernier(energy)

    def _perform_vernier_alignment_OLD(self, energy, tchk, simulate, inspire):
        """
        OLD METHOD - PRESERVED FOR REFERENCE
        Perform Vernier alignment with DCCM (tchk functionality).
        This method is kept for reference but is no longer used.
        Use the new VernierCalibration system instead.
        """
        import logging
        logger = logging.getLogger(__name__)
        from mfx.db import RE
        from ophyd import EpicsSignal
        from pcdsdevices.pv_positioner import OnePVMotor
        from hutch_python import sim
        
        sim_hw = sim.get_hw()
        
        if tchk:
            sid = RE.subscribe(self.on_event)
            try:
                if simulate:
                    sim_hw.fast_motor2.mv(energy)  ## Changed to fast_motor2 to differentiate Vernier from DCCM
                else:
                    self.vernier_scan(
                        energy_scan_start_eV=energy * 1000.0 - 5,
                        energy_scan_end_eV=energy * 1000.0 + 5,
                        energy_scan_steps=11,  # 5 left, center, 5 right
                        tchk = tchk,
                        inspire = inspire,
                        events_per_step=12,
                        record=False,
                        mcc="vernier")
            finally:
                RE.unsubscribe(sid)
            if self.best["eV"] is not None:
                OnePVMotor("MFX:USER:MCC:EPHOT:SET1", name="mcc").move(self.best["eV"]).wait()
                self.best = {"i0": float("-inf"), "eV": None}

    def _move_k_if_necessary(self, energy, k_energy, energy_0, k_stepsize, k_offset, reverse, min_k_keV, simulate):
        """Move K if necessary and manage DAQ state."""
        import numpy as np
        import logging
        from time import sleep
        import copy
        logger = logging.getLogger(__name__)
        from mfx.db import daq
        from hutch_python import sim
        
        prev_k_energy = copy.copy(k_energy)
        e_step = np.abs(energy - energy_0) * 1000
        sim_hw = sim.get_hw()
        
        # Move K every k_stepsize
        if e_step > k_stepsize:
            # Calculate new k_energy (same logic for both simulation and real)
            k_energy = energy * 1000.0 + k_offset
            if reverse:
                k_energy = energy * 1000.0 - k_stepsize + k_offset
                if k_energy/1000 < min_k_keV:
                    k_energy = min_k_keV * 1000 + 1 #+1 just to be safe. ACR is quite strict on this minimum in seeded mode.

            if simulate:
                if round(k_energy, 1) != round(prev_k_energy, 1):
                    sim_hw.slow_motor1.mv(k_energy)
                energy_0 = energy

            else:
                daq.control.setState("paused")
                while daq.control.getState() != "paused":
                    ...
                logger.info(f"Moving k to {k_energy:0.0f}")
                sleep(0.5)
                if round(k_energy, 1) != round(self.acr_energy_k.get().setpoint, 1):
                    self.acr_energy_k.move(k_energy)
                energy_0 = energy

                daq.control.setState("running")
                while daq.control.getState() != "running":
                    ...
                
        return energy_0, k_energy

    def _handle_keyboard_interrupt_and_cleanup(self, sample, tag, run_number, record, inspire, energy_start, k_energy_start, simulate):
        """Handle KeyboardInterrupt and perform cleanup operations."""
        import logging
        logger = logging.getLogger(__name__)
        
        if simulate:
            # In simulation mode, just log and return
            logger.warning("[*] Stopping Run and exiting???...")
            logger.warning('Run ended prematurely. Probably sample delivery problem')
            return
        
        # Real mode - perform full cleanup
        from mfx.db import daq, pp
        from mfx.autorun import post
        from mfx.dccm import DCCM
        
        dccm = DCCM(name='DCCM')
        
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
                daq_num=2,
                add_note='Run ended prematurely. Probably sample delivery problem')
        logger.warning("[*] Stopping Run and exiting???...")
        logger.info('Returning to initial position')
        dccm.energy_with_vernier(energy_start)
        if round(k_energy_start, 1) != round(self.acr_energy_k.get().setpoint, 1):
            self.acr_energy_k.move(k_energy_start)
        logger.warning('Run ended prematurely. Probably sample delivery problem')

    def _finalize_scan(self, energy_start, k_energy_start):
        """Finalize scan and return to initial positions."""
        import logging
        logger = logging.getLogger(__name__)
        from mfx.db import daq, pp
        from mfx.dccm import DCCM
        
        dccm = DCCM(name='DCCM')
        
        pp.close()
        logger.info('Returning to initial position')
        dccm.energy_with_vernier(energy_start)
        if round(k_energy_start, 1) != round(self.acr_energy_k.get().setpoint, 1):
            self.acr_energy_k.move(k_energy_start)
        daq.control.setState("configured")
        while daq.control.getState() != "configured":
            ...
        daq.control.setRecord(False)
        daq.control.setState("running")
        logger.warning('Finished with all runs thank you for choosing the MFX beamline!\n')

    def long_escan(
            self,
            simulate: bool = False,
            start_eV: float = 0.0,
            end_eV: float = None,
            min_k: float = 2.0,
            max_k: float = 12.0,
            energies_list=[],
            wait_time_list = [],
            element: str = 'Fe',
            sample='?',
            tag: str = None,
            picker: str = None,
            inspire: bool = False,
            daq_delay: int = 5,
            record: bool = False,
            runs: int = 1,
            k_stepsize: int = 120,
            lens_stepsize: float = 0.01,
            reverse: bool = False,
            min_k_keV: float = 7.035,
            k_offset: int = 0,
            tchk = False,
            debug: bool = False):
        """Perform EXAFS scan.

        Parameters:
            start_eV (float): 
                Photon energy (in eV) to start the scan at.

            end_eV (float): 
                Photon energy (in eV) to end the scan at.

            min_k (float):
                Minimum wavenumber value in reciprocal angstroms (K) for the linear region.
        
            max_k (float):
                Maximum wavenumber value in reciprocal angstroms (K) for the K-to-eV conversion.

            energies_list: list
                Instead of calculating the energy list you can input a custom one.
            
            wait_time_list: float, list
                Time to wait at each energy step. If list must the same length as energies.

            sample: str, optional
                Sample Name

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

            reverse: bool
                To tell the script you will be running from high energies to low energies for K direction consideration.

            k_offset: float
                Offset in eV for undulator K motion request.
        """
        import numpy as np
        import logging
        logger = logging.getLogger(__name__)
        from time import sleep
        import os
        from mfx.autorun import post
        from mfx.dccm import DCCM
        from mfx.vernier import Vernier
        
        dccm = DCCM(name='DCCM')
        vernier = Vernier()  ## Why is this here?

        # Build energy and wait time lists
        try:
            energies, wait_time = self._build_energy_and_wait_time(
                energies_list, wait_time_list, start_eV, end_eV, min_k, max_k, element, debug)
        except ValueError:
            return
            
        logger.info(f"Energy list: {energies}; Wait time list: {wait_time}")

        energy_start = dccm.energy_with_vernier.energy()
        k_energy_start = self.acr_energy_k.get().setpoint

        try:
            for i in range(runs):
                # Initialize energies
            
                energies, energy_0, k_energy, wait_time = self._initialize_energies_and_move(
                    energies, wait_time, reverse, k_offset, k_stepsize, simulate)

                # Setup DAQ and start recording (or simulate run number)
                run_number, daq_success = self._setup_daq_and_start_recording(sample, picker, inspire, record, simulate, i)
                if not daq_success:
                    break

                for ii, (energy, point_time) in enumerate(zip(energies, wait_time)):
                    logger.info(f"Energy: {energy:0.4f}, Time: {point_time}")
                    energy = energy / 1000.0
                    
                    # Move energy (simulation or real)
                    self._move_energy_simulation_or_real(energy, simulate)
                    
                    # Perform Vernier alignment if needed
                    # OLD METHOD - COMMENTED OUT FOR NEW CALIBRATION SYSTEM
                    # self._perform_vernier_alignment(energy, tchk, simulate, inspire)
                    
                    # NEW METHOD - Using VernierCalibration system
                    if tchk and not simulate:
                        from vernier_calibration import VernierCalibration
                        vernier_calib = VernierCalibration()
                        # Use intensity-based alignment with calibration if available
                        # Will NOT interrupt scan to perform calibration - only uses existing fresh calibration
                        success = vernier_calib.align_to_dccm(
                            target_energy_eV=energy * 1000.0,
                            use_calibration=True,  # Only uses calibration if it exists and is fresh
                            energy_range_eV=10.0,
                            energy_steps=11,
                            events_per_step=12
                        )
                        if not success:
                            logger.warning(f"Vernier alignment failed at energy {energy:.4f} keV")

                    # Move K if necessary
                    energy_0, k_energy = self._move_k_if_necessary(energy, k_energy, energy_0, k_stepsize, k_offset, reverse, min_k_keV, simulate)
                    
                    if np.isnan(point_time):
                        point_time=0.1
                    sleep(point_time)

                if record:
                    post(
                        sample=sample, 
                        tag=tag, 
                        run_number=run_number, 
                        post=record, 
                        inspire=inspire,
                        daq_num=2)
                sleep(daq_delay)

        except KeyboardInterrupt:
            self._handle_keyboard_interrupt_and_cleanup(sample, tag, run_number, record, inspire, energy_start, k_energy_start, simulate)
        
        if not simulate:
            self._finalize_scan(energy_start, k_energy_start)
        return


    def vernier_scan(
            self,
            energy_scan_start_eV: float,
            energy_scan_end_eV: float,
            energy_scan_steps: int,
            tchk = False,
            inspire: bool = False,
            events_per_step: int = 120,
            record: bool = False,
            mcc: str = None):
        """Perform Vernier scan.

        Parameters:
            energy_scan_start_eV (float): 
                Photon energy (in eV) to start the scan at.

            energy_scan_end_eV (float): 
                Photon energy (in eV) to end the scan at.

            energy_scan_steps (int): 
                Number of steps in scan.

            events_per_step (int): 
                Number of events per step. Optional. Default: 120.

            mcc (str): 
                PV type either 'vernier' or 'k'
        

        """
        from ophyd import EpicsSignal
        from pcdsdevices.pv_positioner import OnePVMotor
        import sys
        import logging
        logger = logging.getLogger(__name__)
        try:
            from mfx.db import RE, pp, daq
            from mfx.autorun import quote, post
            from mfx.macros import get_exp, get_run
            import bluesky.plans as bp
        except ImportError:
            from bluesky import RunEngine
            RE = RunEngine({})
        from nabs.plans import daq_scan

        if mcc.lower() == 'vernier':
            mcc_pv = 'MFX:USER:MCC:EPHOT:SET1'
        elif mcc.lower() == 'k':
            mcc_pv = 'MFX:USER:MCC:EPHOT:SET2'
        else:
            logger.error('Please enter spread type of vernier or k only')
            sys.exit()

        mcc_pv_motor = OnePVMotor(mcc_pv, name="mcc")
        mcc_pv_motor.setpoint.kind = "hinted"
        daq.configure(
            motors=[mcc_pv_motor],
            group_mask=0x1,
            events=events_per_step,
            record=record)

        RE(bp.scan(
            [daq],
            mcc_pv_motor,
            energy_scan_start_eV,
            energy_scan_end_eV,
            energy_scan_steps))

        if record:
            run_number = get_run(station=0) + 1
            logger.info(f"Run Number {run_number} Running {tchk}......{quote()['quote']}")
            post(
                sample=tchk, 
                tag=tchk, 
                run_number=run_number, 
                post=record, 
                inspire=inspire,
                daq_num=2,
                add_note=f'Energy range:{energy_scan_start_eV}-{energy_scan_end_eV}eV, steps:{energy_scan_steps}eV @ {events_per_step} events per step')
        logger.warning('Finished with all runs thank you for choosing the MFX beamline!\n')

    def calibrate_vernier(self, energy_start_eV: float, energy_end_eV: float, 
                         energy_steps: int = 10, events_per_step: int = 120):
        """
        Perform vernier calibration to determine energy-vernier offset relationship.
        
        Parameters
        ----------
        energy_start_eV : float
            Starting energy for calibration scan
        energy_end_eV : float
            Ending energy for calibration scan
        energy_steps : int
            Number of energy steps in calibration scan
        events_per_step : int
            Number of events per step
        """
        from vernier_calibration import VernierCalibration
        vernier_calib = VernierCalibration()
        return vernier_calib.calibrate(
            energy_start_eV=energy_start_eV,
            energy_end_eV=energy_end_eV,
            energy_steps=energy_steps,
            events_per_step=events_per_step
        )


    def continuous_dccmscan(
            self,
            energies,
            pointTime=1,
            move_vernier=True,
            wait_acr=False,
            bidirectional=False,
            is_daq=False,
            initial_energy=None):
        """
        Scan the DCCM

        Parameters
        ----------
        energies: list, np.ndarray
            Energies point to go over
        pointTime: float, default=1
            Time in second to spend at each point
        move_vernier: bool, default=True
            Does an energy request to ACR as the dccm is moved.
        wait_acr: bool, default=False
            Wait for ACR to return the done move status after an energy
            request change was made. Useful for slow motion (undulator)
        bidirectional: bool, default=False
        """
        import time
        import numpy as np
        from mfx.dccm import DCCM as dccm
        from mfx.db import daq, pp
        import logging
        logger = logging.getLogger(__name__)

        if wait_acr:
            dccm_e = dccm.energy_with_acr_status
        elif move_vernier:
            dccm_e = dccm.energy_with_vernier
        else:
            dccm_e = dccm.energy

        if initial_energy is None:
            initial_energy = dccm_e.energy.position

        try:
            self.dccm_sweep(dccm_e, energies, pointTime)
            if bidirectional:
                energies = energies[::-1]
                self.dccm_sweep(dccm_e, energies, pointTime)

        except KeyboardInterrupt:
            # Handle pausing or stopping the dccm scan.
            from psdaq.control.DaqControl import DaqControl  # NOQA
            daq.control = DaqControl(
                host=daq.control.host,
                platform=daq.control.platform,
                timeout=10000,
            )
            instr = daq.control.getInstrument()
            if instr is None:
                logger.error('Failed to connect to LCLS-II DAQ')

            start_state = daq.control.getState()
            if start_state == 'error':
                logger.error('DAQ is in an error state.')

            inp = 'q'
            if is_daq:
                daq.control.setState("pause")
                while daq.control.getState() != "pause":
                    ...
                current_energy = dccm_e.energy.position
                logger.error(f"\nKeyboardInterrupt received. Run is paused at energy {current_energy}.")
                inp = input("Type \"q\" to finish the run or \"r\" to resume acquisition\n")

            if inp == 'q':
                logger.info('\nScan end signal received.')
                daq.control.setState("configured")
                while daq.control.getState() != "configured":
                    ...
                daq.control.setRecord(False)
                daq.control.setState("running")
                pp.close()
                dccm_e.move(initial_energy)
            elif inp == 'r':
                idx = np.where( np.isclose(energies, current_energy, atol=5e-3) )[0][0]
                energies = energies[idx:]
                logger.info(f"Resuming scan with energies: {energies}")
                daq.control.setState("running")
                while daq.control.getState() != "running":
                    ...
                self.continuous_dccmscan(
                    energies,
                    pointTime=pointTime,
                    move_vernier=move_vernier,
                    wait_acr=wait_acr,
                    bidirectional=bidirectional,
                    is_daq=is_daq,
                    initial_energy=initial_energy
                )

        finally:
            logger.info(f'Returning dccm to energy before scan: {initial_energy}')
            dccm_e.move(initial_energy)
            time.sleep(pointTime)
        return


    @staticmethod
    def dccm_sweep(dccm_e, energies, pointTime):
        import time
        for E in energies:
            dccm_e.move(E)
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
        import logging
        logger = logging.getLogger(__name__)
        from mfx.db import lxt_fast, lxt_fast_enc
        currentpos = lxt_fast()
        currentenc = lxt_fast_enc.get()
        #elog.post('Set current stage position {}, encoder value {} to 0'.format(currentpos,currentenc.pos))
        logger.info('Set current stage position {}, encoder value {} to 0'.format(currentpos,currentenc.pos))
        lxt_fast.set_current_position(0)
        lxt_fast_enc.set_zero()
        return


class EXAFSEnergyRangeBuilder:
    """
    A class to build energy range and corresponding acquisition time arrays for X-ray spectroscopy experiments.

    Attributes:
    - element (str): The element symbol (e.g., 'Fe', 'Ti').
    - min_before_pre_edge (float): Minimum energy value before the pre-edge region in eV.
    - max_before_pre_edge (float): Maximum energy value before the pre-edge region in eV.
    - min_K_value (float): Minimum wavenumber value in reciprocal angstroms (K) for the linear region.
    - max_K_value (float): Maximum wavenumber value in reciprocal angstroms (K) for the K-to-eV conversion.
    - before_edge_eV_increment (float): Increment spacing in eV for the "before pre-edge" energy region.
    - edge_eV_increment (float): Increment spacing in eV for the energy range up to the edge of the K-to-eV region.
    - K_spacing (float): K spacing for the K-to-eV energy range.
    - time_before_edge (float): Acquisition time per point before the pre-edge.
    - time_in_edge (float): Acquisition time per point in the edge region.
    - min_time_EXAFS (float): Minimum acquisition time in seconds for the EXAFS region.
    - max_time_EXAFS (float): Maximum acquisition time in seconds for the EXAFS region.
    - power (int): The power for the K-weighting.
    - foil_energies (dict): Dictionary containing foil energies for various elements.
    - threshold_energies (dict): Dictionary containing threshold energies for various elements.
    """

    def __init__(self):
        self.element = 'Fe'
        self.power = 3
        self.foil_energies = {'Sc': 4492.8, 'Ti': 4966.4, 'V': 5465.1, 'Cr': 5989.2, 'Mn': 6539.0, 'Fe': 7111.2,
                              'Co': 7708.9, 'Ni': 8332.8, 'Cu': 8978.9, 'Zn': 9658.6}
        self.threshold_energies = {'Ti': 4985.00, 'Sc': 4510.00, 'V': 5485.00, 'Cr': 6010.00, 'Mn': 6560.00,
                                   'Fe': 7130.00, 'Co': 7730.00, 'Ni': 8350.00, 'Cu': 9000.00, 'Zn': 9680.00}

    def K_to_eV(self, K_value):
        """
        Convert wavenumber (K) to energy (eV) for the specified element.

        Parameters:
        - K_value (float): The wavenumber value in reciprocal angstroms (K).

        Returns:
        - float: The energy in electronvolts (eV).
        """
        threshold_energy = self.threshold_energies[self.element]
        energy_eV = K_value ** 2 / 0.2625 + threshold_energy
        return energy_eV

    def eV_to_K(self, energy_eV):
        """
        Convert energy (eV) to wavenumber (K) for the specified element.

        Parameters:
        - energy_eV (float): The energy value in electronvolts (eV).

        Returns:
        - float: The wavenumber in reciprocal angstroms (K).
        """
        threshold_energy = self.threshold_energies[self.element]
        K_value = (0.2625 * (energy_eV - threshold_energy)) ** 0.5
        return K_value

    def build_energy_range(
            self,
            min_before_pre_edge=7010.0,
            max_before_pre_edge=7080.0,
            preedge_end=7118,
            preedge_eV_increment=0.5,
            max_before_edge=7020.0,
            min_K_value=2.0,
            max_K_value=12.0,
            before_edge_eV_increment=5.0,
            edge_eV_increment=1.0,
            K_spacing=0.1,
            time_before_edge=0.5,
            time_in_edge=1,
            time_in_preedge=1.5,
            min_time_EXAFS=0.5,
            max_time_EXAFS=10,
            debug=False
    ):
        """
        Build the entire energy range for the specified element. Basically with 3 user defined ranges:
        the pre-pre-edge, the pre-edge+edge, and the EXAFS. The user must define the min/max energy of the first two ranges
        and their acquisition time per point. Then the third region is defined by the maximum K-value to measure to; the point spacing (in K);
        the minumum and maximum acquistion time for the EXAFS region; and the power with which that acqusition time range is mapped onto the K points.

        Attributes:
        - min_before_pre_edge (float): Minimum energy value before the pre-edge region in eV.
        - max_before_pre_edge (float): Maximum energy value before the pre-edge region in eV.
        - min_K_value (float): Minimum wavenumber value in reciprocal angstroms (K) for the linear region.
        - max_K_value (float): Maximum wavenumber value in reciprocal angstroms (K) for the K-to-eV conversion.
        - before_edge_eV_increment (float): Increment spacing in eV for the "before pre-edge" energy region.
        - edge_eV_increment (float): Increment spacing in eV for the energy range up to the edge of the K-to-eV region.
        - K_spacing (float): K spacing for the K-to-eV energy range. reciprocal angstroms (K)
        - time_before_edge (float): Acquisition time per point before the pre-edge.
        - time_in_edge (float): Acquisition time per point in the edge region.
        - min_time_EXAFS (float): Minimum acquisition time in seconds for the EXAFS region.
        - max_time_EXAFS (float): Maximum acquisition time in seconds for the EXAFS region.

        Returns:
        - tuple: A tuple containing the energy range array and the corresponding acquisition time array.
        """
        import numpy as np
        energy_before_pre_edge = np.arange(min_before_pre_edge, max_before_pre_edge +
                                           before_edge_eV_increment, before_edge_eV_increment)
        K_values = np.arange(min_K_value, max_K_value + K_spacing, K_spacing)
        energy_K_range = [self.K_to_eV(K) for K in K_values if self.K_to_eV(K) is not None]
        energy_in_preedge = np.arange(max_before_pre_edge + preedge_eV_increment, preedge_end, preedge_eV_increment)
        energy_in_edge = np.arange(preedge_end + edge_eV_increment, np.min(energy_K_range), edge_eV_increment)
        energy_range = np.concatenate((energy_before_pre_edge, energy_in_preedge, energy_in_edge, energy_K_range))

        num_points_before_pre_edge = len(energy_before_pre_edge)
        num_points_in_edge = len(energy_in_edge)
        num_points_in_preedge = len(energy_in_preedge)

        time_before_edge_arr = np.ones(num_points_before_pre_edge) * time_before_edge
        time_in_preedge_arr = np.ones(num_points_in_preedge) * time_in_preedge
        time_in_edge_arr = np.ones(num_points_in_edge) * time_in_edge
        time_EXAFS = self.map_time_to_K_weighting(min_time_EXAFS, max_time_EXAFS, K_values)

        time_range = np.concatenate((time_before_edge_arr, time_in_preedge_arr, time_in_edge_arr, time_EXAFS))
        self.time_range = time_range
        self.energy_range = energy_range
        self.energy_K_range = energy_K_range
        self.K_values = K_values
        if debug:
            self.current_scan_profile()
        return energy_range, time_range, energy_K_range, K_values

    def map_time_to_K_weighting(self, min_time, max_time, K_values):
        """
        Map acquisition times to a K-weighting with a specified power.

        Parameters:
        - min_time (float): Minimum acquisition time in seconds.
        - max_time (float): Maximum acquisition time in seconds.
        - K_values (array-like): Array of K-space values in reciprocal angstroms (K).

        Returns:
        - numpy.ndarray: An array of normalized acquisition times based on the K-weighting.
        """
        import numpy as np
        time_range = np.linspace(min_time, max_time, len(K_values))
        K_time = K_values ** self.power
        K_time_range = time_range * K_time
        min_weighted_time = min(K_time_range)
        max_weighted_time = max(K_time_range)
        normalized_time_range = min_time + (max_time - min_time) * (K_time_range - min_weighted_time) / (
                max_weighted_time - min_weighted_time)
        self.normalized_time_range = normalized_time_range
        return normalized_time_range

    def current_scan_profile(self):
        self.plot_scan_profile(
            self.energy_range,
            self.time_range,
            self.energy_K_range,
            self.K_values
        )

    def plot_scan_profile(
            self,
            energy_range,
            time_range,
            energy_K_range,
            K_values
    ):
        """
        Plot the energy range, acquisition time, cumulative acquisition time, and estimated resolution.

        This method generates a multi-panel plot visualizing the scan profile. For informational purposes.
        """
        import numpy as np
        import matplotlib.pyplot as plt
        fig, axs = plt.subplots(3, 2, dpi=300, figsize=(6, 9))
        axs[0, 0].plot(energy_range, color='k')
        axs[0, 0].set_xlabel('Data Point')
        axs[0, 0].set_ylabel('Requested Energy (eV)')

        axs[1, 0].plot(time_range, color='k')
        axs[1, 0].set_xlabel('Data Point')
        axs[1, 0].set_ylabel('Acq. Time Per Point (s)')

        axs[2, 0].plot(np.cumsum(time_range), color='k')
        axs[2, 0].set_xlabel('Data Point')
        axs[2, 0].set_ylabel('Total Acq. Time (s)')

        K_2 = np.argmin(np.abs(K_values - 2.0))
        expectedResolution = np.pi * 0.5 / (K_values[K_2:] - 1.99)

        axs[0, 1].plot(K_values[K_2:], expectedResolution, color='k')
        axs[0, 1].set_xlabel('K-Value ($\AA^{-1}$)')
        axs[0, 1].set_ylabel('Estimated Resolution ($\AA$)', rotation=270, labelpad=15)
        axs[0, 1].yaxis.set_label_position("right")

        axs[0, 1].set_ylim(0.05, 0.5)

        axs[1, 1].plot(energy_range, time_range, color='k')
        axs[1, 1].set_xlabel('Energy (eV)')

        axs[2, 1].plot(energy_range, np.cumsum(time_range), color='k')
        axs[2, 1].set_xlabel('Energy (eV)')
        plt.tight_layout()

    def output_scan_profile(self, elist_name='elist', tlist_name='tlist'):
        import numpy as np
        np.savetxt(tlist_name + '.txt', time_range)
        np.savetxt(elist_name + '.txt', energy_range / 1000.0)
