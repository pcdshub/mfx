import copy
import sys, os
from time import sleep
from pathlib import Path
import json
import numpy as np
from tfs.sim_transfocator import make_tfs_sim
from tfs.transfocator import Transfocator

class Exafs:
    from pcdsdevices.beam_stats import BeamEnergyRequest, BeamEnergyRequestACRWait
    from ophyd import EpicsSignalRO

    def __init__(self):
        import logging
        from mfx.dccm import DCCM
        from mfx.vernier import Vernier
        from hutch_python import sim

        self.logger = logging.getLogger(__name__)
        self.dccm = DCCM(name='DCCM')
        self.vernier = Vernier()
        self.exafs_energy_range_builder = EXAFSEnergyRangeBuilder()
        self.simulate = False
        self.sim = sim.get_hw()
        self.tfs = None

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

    def _build_energy_and_wait_time(
        self, energies_list, wait_time_list, start_eV, end_eV, min_k, max_k, element, min_time_EXAFS, max_time_EXAFS, debug):
        """Build energy and wait time lists for EXAFS scan."""
        
        if len(energies_list) == 0 or len(wait_time_list) == 0:
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

            energies, wait_time, energy_K_range, K_values = self.exafs_energy_range_builder.build_energy_range(
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
                min_time_EXAFS = min_time_EXAFS, 
                max_time_EXAFS = max_time_EXAFS,
                debug=debug
                )
            if debug:
                self.logger.warning(f"Would you like to continue?")
                answer = input("(y/n)? ")

                if answer.lower() == "n":
                    self.logger.error(f"Fine. Exiting...")
                    sys.exit()
        else:
            energies = energies_list
            wait_time = wait_time_list

        if len(wait_time) != len(energies):
            self.logger.error('Error: len(wait_time) is not equal to len(energies)')
            self.logger.info('Please pass wait_time as a float or a list of the same length. Exit now.')
            raise ValueError('len(wait_time) is not equal to len(energies)')
        else:
            self.logger.info(f"Energy list: {energies}; Wait time list: {wait_time}")

        return energies, wait_time

    def _initialize_energies_and_move(self, energies, wait_time, reverse, k_offset, k_stepsize):
        """Initialize energy values for the scan."""
        
        energy_0_keV = energies[0] / 1000.0  # energy at the beginning or after a und K step
        k_energy = energy_0_keV * 1000.0 + (k_stepsize / 2) + k_offset
        if reverse:
            energies = energies[::-1]
            energy_0_keV = energies[0] / 1000.0
            k_energy = energy_0_keV * 1000.0 - (k_stepsize / 2) + k_offset
            self.logger.info('THE MODE IS REVERSED. FLIPPING ELIST, CLIST, and TLIST.')
            wait_time = wait_time[::-1]
        
        # Move energy motor
        self._move_dccm_energy_with_vernier(energy_0_keV)
            
        # Move K motor
        self.logger.warning(f"Moving k to initial energy for beginning of scan {k_energy:0.0f}")
        if round(k_energy, 1) != round(self.acr_energy_k.get().setpoint, 1):
            self._move_k_energy(k_energy)
            
        return energies, energy_0_keV, k_energy, wait_time

    def _setup_daq_and_start_recording(self, sample, picker, inspire, record, run_index):
        """Setup DAQ and start recording."""
        
        if self.simulate:
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
            self.logger.error('Failed to connect to LCLS-II DAQ')
            return None, False
        start_state = daq.control.getState()
        if start_state == 'error':
            self.logger.error('DAQ is in an error state.')
            return None, False

        self.logger.info(f"Run Number {run_number} Running {sample}......{quote()['quote']}")
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

    def _move_dccm_energy_with_vernier(self, energy_keV):
        """Move energy with both DCCM and Vernier."""
        if self.simulate:
            self.sim.fast_motor1.mv(energy_keV)
        else:
            self.dccm.energy_with_vernier(energy_keV)

    def _move_k_energy(self, k_energy):
        """Move K energy."""
        if self.simulate:
            self.sim.slow_motor1.mv(k_energy)
        else:
            self.acr_energy_k.move(k_energy)

    def _move_feespec_energy(self, energy_keV):
        """Move FEE spectrometer energy."""
        if self.simulate:
            self.sim.slow_motor2.mv(energy_keV)
        else:
            # check Camera status and abort if running
            os.system(f'caget CAMR:FEE1:441:Acquire')
            status = str(os.popen("caget CAMR:FEE1:441:Acquire | awk '{print $2}'").read().strip())
            if status == 'Acquire':
                self.logger.error('FEE Spectrometer Camera is acquiring. Aborting energy move.')
                return
            # Current
            ref_crystal_angle_deg = hxrsss.th.get_current_values()
            ref_camera_angle_deg = hxrsss.tth.get_current_values()
            ref_camera_y_pos_mm = hxrsss.camy.get_current_values()
            # Target
            crystal_angle_deg = 82.8 - 5.9 * energy_keV
            camera_angle_deg = -1.9 + 2 * crystal_angle_deg
            camera_y_pos_mm = -4.92 - 0.111 * energy_keV
            # Move
            hxrss.th.mv(crystal_angle_deg)
            hxrss.tth.mv(camera_angle_deg)
            hxrss.camy.mv(camera_y_pos_mm)
            # Check safety
            os.system(f'caget XRT:HXS:TRNS.SEVR')
            status = str(os.popen("caget XRT:HXS:TRNS.SEVR | awk '{print $2}'").read().strip())
            if status != 'NO_ALARM':
                self.logger.error('XRT Transmission is in alarm state after FEE spectrometer energy move. Returning to previous position.')
                hxrsss.th.mv(ref_crystal_angle_deg)
                hxrsss.tth.mv(ref_camera_angle_deg)
                hxrsss.camy.mv(ref_camera_y_pos_mm)
            return


    def _align_vernier_to_dccm(self, energy, tchk, use_vernier_calibration):
        """
        Perform Vernier alignment with DCCM (tchk functionality).
        
        This method uses the new VernierCalibration system with two approaches:
        1. If calibration exists and use_vernier_calibration=True: Use calibration to predict offset
        2. Otherwise: Use intensity-based alignment scan
        
        Parameters
        ----------
        energy : float
            Target energy in eV
        tchk : bool
            Whether to perform vernier alignment
        use_vernier_calibration : bool
            Whether to use calibration if available
        """
        if not tchk:
            return
        
        # If simulating, force simulated devices to avoid any real hardware motion
        if self.simulate:
            try:
                from mfx.optimize.beamline_hw import sim_devices
                sim_devices()
                print("[align_vernier_to_dccm] Simulation devices initialized")
            except Exception:
                # Continue even if sim init fails; other simulation guards remain in place
                ...
        
        from mfx.optimize.vernier_calibration import VernierCalibration
        from mfx.dccm import DCCM
        
        vernier_calib = VernierCalibration()
        
        # Check if calibration exists and should be used
        calib = vernier_calib._load_calibration()
        use_calibration = use_vernier_calibration and calib is not None
        
        if use_calibration:
            self.logger.info(f"Using existing calibration from {calib.get('timestamp')}")
            # Method 1: Use calibration
            # First, move DCCM alone to target energy (not with vernier)
            self.logger.info(f"Moving DCCM alone to {energy:.4f} keV")
            if self.simulate:
                # In simulation, use sim motor for DCCM energy
                self.sim.fast_motor1.mv(energy / 1000.0)
            else:
                dccm = DCCM(name='DCCM')
                dccm.energy.mv(energy / 1000.0)  # DCCM uses keV
            
            # Then align vernier using calibration prediction
            self.logger.info("Aligning vernier using calibration")
            success = vernier_calib.move_to_energy_with_calibration()
            if not success:
                self.logger.warning(f"Calibration-based alignment failed at energy {energy:.4f} keV")
        else:
            if use_vernier_calibration and calib is None:
                self.logger.info("No calibration found - using intensity-based alignment")
            elif not use_vernier_calibration:
                self.logger.info("use_vernier_calibration=False - using intensity-based alignment")
            
            # Method 2: No calibration - use intensity scan
            # First move DCCM with vernier to approximate position
            self.logger.info(f"Moving DCCM with vernier to {energy:.4f} keV")
            if self.simulate:
                # In simulation, use sim motor for DCCM+vernier energy
                self.sim.fast_motor1.mv(energy / 1000.0)
            else:
                dccm = DCCM(name='DCCM')
                dccm.energy_with_vernier.mv(energy / 1000.0)  # DCCM uses keV
                
                # Then align to DCCM using intensity scan
                self.logger.info("Performing intensity-based vernier alignment")
                success = vernier_calib.align_to_dccm(
                    energy_range_eV=10.0,
                    energy_steps=11,
                    events_per_step=12
                )
                if not success:
                    self.logger.warning(f"Intensity-based alignment failed at energy {energy:.4f} keV")

    def _align_undulator(self, on_diagnostic, using_device, with_method, grid_bins):
        """
        Perform undulator (undulator) alignment using beam alignment system.

        This method uses the Beam.align() function to align the undulator.
        If with_method="calib", it will use calibration if available, otherwise run calibration.
        If with_method="turbo", it will use turbo optimization.

        Parameters
        ----------
        on_diagnostic : str
            Diagnostic location (e.g., "dg1", "dg2", "xcs1")
        using_device : str
            Device to use ("yag" or "wave8")
        with_method : str
            Alignment method ("calib" or "turbo")
        grid_bins : int
            Number of grid bins for calibration (if using "calib" method)
        """
        # If simulating, force simulated devices to avoid any real hardware motion
        if self.simulate:
            try:
                from mfx.optimize.beamline_hw import sim_devices
                sim_devices()
                print("[align_undulator] Simulation devices initialized")
            except Exception:
                print("[align_undulator] WARNING: Failed to set simulation devices. Returning.")
                return

        try:
            from mfx.optimize.beam import Beam
            beam = Beam()
            beam.align(
                on_diagnostic=on_diagnostic,
                using_device=using_device,
                use_2d_markers=True,
                mover="und",
                with_method = "calib",
                grid_bins = 5
            )
        except Exception as e:
            self.logger.warning(f"undulator alignment failed: {e}")
            # Don't raise - allow scan to continue

    def _get_track_focus_data(self):
        track_focus_data = None
        try:
            track_focus_path = Path.home() / "track_focus_results.json"
            if track_focus_path.exists():
                with open(track_focus_path, "r") as tf:
                    track_focus_data = json.load(tf)
                self.logger.info(f"Loaded track_focus results from {track_focus_path}")
            else:
                self.logger.info("No track_focus_results.json found in home directory; returning None.")
        except Exception as e:
            self.logger.warning(f"Failed to load track_focus_results.json: {e}")
        return track_focus_data

    def _init_tfs(self, energies, margin_mm, 
                  ref_focal_length_um, ref_z_stage_mm,
                  avoid_forbidden, enable_prefocus):
        tfs = Transfocator("MFX:LENS", name='MFX Transfocator')
        if self.simulate:
            self.tfs = make_tfs_sim(tfs)
        else:
            self.tfs = tfs

        sim_tfs = make_tfs_sim(tfs)
        track_focus_data = sim_tfs.track_focus(
            energies=energies,
            margin_mm=margin_mm,
            show=True,
            ref_focal_length_um=ref_focal_length_um,
            ref_z_stage_mm=ref_z_stage_mm,
            avoid_forbidden=avoid_forbidden,
            enable_prefocus=enable_prefocus
        )
        return track_focus_data

    def _move_tfs_to_energy(self, energy_eV, track_focus_data):
        if track_focus_data is not None:
            energy_eV = float(energy_eV)
            for data in track_focus_data:
                if data["energy"] == energy_eV:
                    z_position = data["z_position"]
                    inserted_lenses = data["inserted_lenses"]
                    break
            if z_position is not None:
                self.logger.info(f"Moving TFS to {z_position:.3f} mm")
                self.tfs.translation.mv(z_position)
            for lens in self.tfs.lenses:
                if lens.prefix in inserted_lenses:
                    self.logger.info(f"Inserting lens {lens.prefix}")
                    if lens.inserted:
                        self.logger.info(f"Lens {lens.prefix} already inserted")
                        continue
                    lens.insert()
                else:
                    self.logger.info(f"Removing lens {lens.prefix}")
                    if not lens.inserted:
                        self.logger.info(f"Lens {lens.prefix} already removed")
                        continue
                    lens.remove()
        else:
            self.logger.warning("No track_focus_data found; how did you get here?.")
            return

    def _move_k_if_necessary(self, energy_keV, k_energy, k_stepsize, k_offset, reverse, min_k_keV):
        """Move K if necessary and manage DAQ state."""
        from mfx.db import daq

        if self.simulate:
            prev_k_energy = copy.copy(k_energy)
        else:
            prev_k_energy = self.acr_energy_k.get().setpoint

        e_step = round(np.abs(energy_keV - k_energy / 1000) * 1000, 1)
        self.logger.info(f"Absolute difference vernier and k {e_step}")
        
        # Move K every k_stepsize
        if e_step > k_stepsize / 2:
            # Calculate new k_energy (same logic for both simulation and real)
            k_energy = k_energy + k_stepsize + k_offset
            if reverse:
                k_energy = k_energy - k_stepsize + k_offset
                if k_energy/1000 < min_k_keV:
                    k_energy = min_k_keV * 1000 + 1 #+1 just to be safe. ACR is quite strict on this minimum in seeded mode.

            if round(k_energy, 1) != round(prev_k_energy, 1):
                if not self.simulate:
                    daq.control.setState("paused")
                    while daq.control.getState() != "paused":
                        ...
                    self.logger.info(f"Moving k to {k_energy:0.0f}")
                    sleep(0.5)

                self.logger.warning(f"Moving k to new energy range {k_energy:0.0f}")
                self._move_k_energy(k_energy)

                if not self.simulate:
                    daq.control.setState("running")
                    while daq.control.getState() != "running":
                        ...
        return k_energy

    def _wait(self, wait_time):
        if np.isnan(wait_time):
            wait_time = 0.1
        sleep(wait_time)

    def _return_to_start(self, energy_start, k_energy_start):
        """Finalize scan and return to initial positions."""
        from mfx.db import daq, pp

        if self.simulate:
            k_energy = k_energy_start
        else:
            k_energy = self.acr_energy_k.get().setpoint
            daq.control.setState("configured")
            while daq.control.getState() != "configured":
                ...
            daq.control.setRecord(False)
            daq.control.setState("running")
            pp.close()

        self.logger.info('Returning to initial position')
        self._move_dccm_energy_with_vernier(energy_start)
        if round(k_energy_start, 1) != round(k_energy, 1):
            self._move_k_energy(k_energy_start)

    def _handle_keyboard_interrupt_and_cleanup(self, sample, tag, run_number, record, inspire, energy_start, k_energy_start):
        """Handle KeyboardInterrupt and perform cleanup operations."""
        if not self.simulate and record:
            from mfx.autorun import post
            post(
                sample=sample,
                tag=tag,
                run_number=run_number,
                post=record,
                inspire=inspire,
                daq_num=2,
                add_note='Run ended prematurely. Probably sample delivery problem')
        self.logger.warning("[*] Stopping Run and exiting???...")
        self._return_to_start(energy_start, k_energy_start)
        self.logger.warning('Run ended prematurely. Probably sample delivery problem')

    def _finalize_scan(self, energy_start, k_energy_start):
        """Finalize scan and return to initial positions."""
        self._return_to_start(energy_start, k_energy_start)
        self.logger.warning('Finished with all runs thank you for choosing the MFX beamline!\n')

    def long_calib(
            self,
            simulate: bool = False,
            start_eV: float = 7000.0,
            end_eV: float = 7500.0,
            energy_steps: int = 6,
            vernier_events_per_step: int = 120,
            debug: bool = False):
        """Perform calibration scan over energy range for vernier.
        
        This function calls VernierCalibration.calibrate() to perform a calibration scan
        over the specified energy range.
        
        Parameters:
        -----------
        simulate : bool, optional
            Whether to run in simulation mode. Default: False
            
        start_eV : float, optional
            Starting energy for calibration range in eV. Default: 7000.0
            
        end_eV : float, optional
            Ending energy for calibration range in eV. Default: 7500.0
            
        energy_steps : int, optional
            Number of energy points to visit. Default: 6
            
        vernier_events_per_step : int, optional
            Number of events to average for vernier offset measurement. Default: 120
            
        debug : bool, optional
            Enable debug output. Default: False
        """
        from mfx.optimize.vernier_calibration import VernierCalibration
        
        self.simulate = simulate
        
        # If simulating, force simulated devices to avoid any real hardware motion
        if self.simulate:
            try:
                from mfx.optimize.beamline_hw import sim_devices
                _dev = sim_devices()
                print("Simulated devices initialized")
            except Exception:
                self.logger.warning("Failed to initialize simulated devices")
                return
        
        # Store initial position (keV), handling simulation
        try:
            if self.simulate:
                # Prefer simulated device reading via optimize.beamline_hw if available
                try:
                    # vernier_dccm_energy reported in eV
                    energy_start = float(_dev["vernier_dccm_energy"].get()) / 1000.0
                except Exception:
                    # Fallback to hutch_python sim motors if present
                    try:
                        # sim.fast_motor1 is used in _move_dccm_energy_with_vernier
                        energy_start = float(self.sim.fast_motor1())
                    except Exception:
                        # Sensible default
                        energy_start = float(start_eV) / 1000.0
            else:
                energy_start = self.dccm.energy_with_vernier.energy()
        except Exception:
            # Last-resort fallback: use requested start energy
            energy_start = float(start_eV) / 1000.0
        
        # Initialize calibration object
        vernier_calib = VernierCalibration()
        
        self.logger.info(f"Starting long calibration scan from {start_eV:.2f} to {end_eV:.2f} eV ({energy_steps} steps)")
        
        try:
            # Call the calibrate method which handles the entire scan and fitting
            vernier_calib_result = vernier_calib.calibrate(
                energy_start_eV=start_eV,
                energy_end_eV=end_eV,
                energy_steps=energy_steps,
                events_per_step=vernier_events_per_step, 
                simulate=simulate
            )
            self.logger.info(f"Vernier calibration completed successfully")
            self.logger.info(f"Calibration model: offset = {vernier_calib_result.get('coeff_offset', 'N/A')}")
        
        except KeyboardInterrupt:
            self.logger.warning("[*] Calibration interrupted by user")
        except Exception as e:
            self.logger.error(f"Failed to complete vernier calibration: {e}")
            if not debug:
                raise
        
        # Return to initial position
        self.logger.info(f"\nReturning to initial energy: {energy_start:.4f} keV")
        self._move_dccm_energy_with_vernier(energy_start)
        
        self.logger.warning('Finished long calibration scan!\n')
        return

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
            min_time_EXAFS: float = 0.5,
            max_time_EXAFS: float = 10.0,
            tchk = False,
            use_vernier_calibration: bool = True,
            map_focus_track: bool = False,
            track_focus: bool = False,
            tfs_margin_mm=5.0,
            ref_focal_length_um=None,
            ref
            avoid_forbidden_combo=True,
            enable_prefocus=True,
            undulator_point: bool = False,
            undulator_on_diagnostic: str = "dg1",
            undulator_using_device: str = "yag",
            undulator_with_method: str = "calib",
            undulator_grid_bins: int = 5,
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

            min_time_EXAFS (float): 
                Minimum acquisition time in seconds for the EXAFS region.
            
            max_time_EXAFS (float): 
                Maximum acquisition time in seconds for the EXAFS region.
                
            tchk: bool, optional
                If True, perform vernier alignment at each energy step.
                
            use_vernier_calibration: bool, optional
                If True (default), use vernier calibration if available, otherwise use 
                intensity-based alignment. If False, always use intensity-based alignment.
                
            undulator_point: bool, optional
                If True, perform undulator alignment at each energy step. Default: False
                
            undulator_on_diagnostic: str, optional
                Diagnostic location for undulator alignment. Options: "xcs1", "dg1", "dg2". Default: "dg1"
                
            undulator_using_device: str, optional
                Device to use for undulator alignment. Options: "yag", "wave8". Default: "yag"
                
            undulator_with_method: str, optional
                Method to use for undulator alignment. Options: "turbo", "calib". Default: "calib"
                
            undulator_grid_bins: int, optional
                Number of grid bins for undulator calibration (if using "calib" method). Default: 5
        """
        from mfx.autorun import post

        self.simulate = simulate

        # Load track_focus results from current working directory, if available
        track_focus_data = None
        try:
            track_focus_path = Path(os.getcwd()) / "track_focus_results.json"
            if track_focus_path.exists():
                with open(track_focus_path, "r") as tf:
                    track_focus_data = json.load(tf)
                self.logger.info(f"Loaded track_focus results from {track_focus_path}")
            else:
                self.logger.info("No track_focus_results.json found in current directory; proceeding without TFS guidance.")
        except Exception as e:
            self.logger.warning(f"Failed to load track_focus_results.json: {e}")

        energies, wait_times = self._build_energy_and_wait_time(
            energies_list,
            wait_time_list,
            start_eV,
            end_eV,
            min_k,
            max_k,
            element,
            min_time_EXAFS,
            max_time_EXAFS,
            debug
        )

        # Map the focus track over the energy list and record to track_focus_results.json
        if map_focus_track:
            self._init_tfs(energies,
                           margin_mm=tfs_margin_mm,
                           ref_focal_length_um=ref_focal_length_um,
                           ref_z_stage_mm=ref_z_stage_mm,
                           avoid_forbidden=avoid_forbidden_combo,
                           enable_prefocus=enable_prefocus)
            return

        energy_start = self.dccm.energy_with_vernier.energy()
        k_energy_start = self.acr_energy_k.get().setpoint

        try:
            for i in range(runs):
                # Initialize energies
                energies, energy_0_keV, k_energy, wait_times = self._initialize_energies_and_move(
                    energies, wait_times, reverse, k_offset, k_stepsize
                )

                # Setup DAQ and start recording (or simulate run number)
                run_number, daq_success = self._setup_daq_and_start_recording(
                    sample, picker, inspire, record, i
                )
                if not daq_success:
                    break
                if undulator_point:
                    self._align_undulator(
                        on_diagnostic=undulator_on_diagnostic,
                        using_device=undulator_using_device,
                        with_method=undulator_with_method,
                        grid_bins=undulator_grid_bins
                    )

                # Start Energy scan
                for ii, (energy, wait_time) in enumerate(zip(energies, wait_times)):
                    self.logger.info(f"Energy: {energy:0.4f}, Time: {wait_time}")
                    energy_keV = energy / 1000.0

                    # Move K if necessary
                    k_energy = self._move_k_if_necessary(
                        energy_keV, k_energy, k_stepsize, k_offset, reverse, min_k_keV
                    )

                    # Move TFS to energy
                    if track_focus:
                        self._move_tfs_to_energy(energy_eV=energy,
                                                 track_focus_data=track_focus_data)

                    # Move DCCM and Vernier to energy
                    self._move_dccm_energy_with_vernier(energy_keV)
                    
                    # Perform Vernier alignment if needed
                    self._align_vernier_to_dccm(energy, tchk, use_vernier_calibration)


                    # Move XRT spectrometer camera if necessary

                    # Adjust undulator pointing on DCCM

                    # Wait before moving on
                    self._wait(wait_time)

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
            self._handle_keyboard_interrupt_and_cleanup(
                sample, tag, run_number, record, inspire, energy_start, k_energy_start
            )

        self._finalize_scan(energy_start, k_energy_start)
        return


### START OF TRASH? ###
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
        from pcdsdevices.pv_positioner import OnePVMotor
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
            self.logger.error('Please enter spread type of vernier or k only')
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
            self.logger.info(f"Run Number {run_number} Running {tchk}......{quote()['quote']}")
            post(
                sample=tchk, 
                tag=tchk, 
                run_number=run_number, 
                post=record, 
                inspire=inspire,
                daq_num=2,
                add_note=f'Energy range:{energy_scan_start_eV}-{energy_scan_end_eV}eV, steps:{energy_scan_steps}eV @ {events_per_step} events per step')
        self.logger.warning('Finished with all runs thank you for choosing the MFX beamline!\n')

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
        from mfx.optimize.vernier_calibration import VernierCalibration
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
#### END OF TRASH? ###

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
