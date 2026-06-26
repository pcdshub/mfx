"""
EXAFS (Extended X-ray Absorption Fine Structure) control for MFX beamline.

Provides automated EXAFS data collection with coordinated DCCM, vernier,
and undulator K parameter control. Supports track-and-check calibration
for accurate energy scanning.
"""

import sys
import os
import json
import logging
from time import sleep, time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import matplotlib.pyplot as plt

try:
    from ophyd import EpicsSignalRO
    from pcdsdevices.beam_stats import BeamEnergyRequestACRWait
    from tfs.sim_transfocator import make_tfs_sim
    from tfs.transfocator import Transfocator
    _HW_AVAILABLE = True
except ImportError:
    _HW_AVAILABLE = False


class _SimMotor:
    """Minimal simulated motor for offline testing."""
    def __init__(self):
        self.position = 0.0

    def mv(self, value):
        self.position = float(value)


class Exafs:
    """
    Main EXAFS scan controller for MFX beamline.

    This class provides comprehensive control for Extended X-ray Absorption Fine Structure
    (EXAFS) scans, including energy scanning, vernier alignment, transfocator control,
    and FEE spectrometer tracking.

    Attributes
    ----------
    ipm_sum : EpicsSignalRO
        DG1 IPM sum signal (read-only)
    acr_energy_v : BeamEnergyRequestACRWait
        ACR energy request for vernier
    acr_energy_k : BeamEnergyRequestACRWait
        ACR energy request for undulator K
    logger : logging.Logger
        Logger instance for this class
    dccm : DCCM
        Double crystal monochromator controller
    vernier : Vernier
        Vernier energy controller
    exafs_energy_range_builder : EXAFSEnergyRangeBuilder
        Energy range builder for EXAFS scans
    simulate : bool
        Simulation mode flag
    sim : object
        Simulation hardware object
    tfs : Transfocator
        Transfocator controller
    k_energy : float
        Current undulator K energy
    vernier_offset : float
        Current vernier offset
    vernier_device : object
        Vernier device controller
    """

    if _HW_AVAILABLE:
        ipm_sum = EpicsSignalRO("MFX:DG1:W8:01:SUM", name="dg1_sum")

        acr_energy_v = BeamEnergyRequestACRWait(
            name='acr_energy', prefix='MFX', acr_status_suffix='AO805'
        )
        acr_energy_k = BeamEnergyRequestACRWait(
            name='acr_energy', prefix='MFX', acr_status_suffix='AO805', pv_index=2
        )

    def __init__(self, simulate=False):
        """
        Initialize EXAFS controller.

        Parameters
        ----------
        simulate : bool, optional
            If True, skip all hardware connections and use mock motors.
            Allows fully offline instantiation for testing. (default: False)
        """
        self.logger = logging.getLogger(__name__)
        self.simulate = simulate
        self.exafs_energy_range_builder = EXAFSEnergyRangeBuilder()
        self.tfs = None
        self.k_energy = None
        self.vernier_offset = None
        self.vernier_device = None

        if simulate:
            self.dccm = None
            self.xrtspec = None
            self.sim = SimpleNamespace(
                fast_motor1=_SimMotor(),
                slow_motor1=_SimMotor(),
            )
        else:
            from mfx.dccm import DCCM
            from hutch_python import sim
            from mfx.xrt_spec import XRTspec
            self.xrtspec = XRTspec()
            self.dccm = DCCM(name='DCCM')
            self.sim = sim.get_hw()

    # ==================== Core Motion Methods ====================

    def _move_dccm_energy_with_vernier(self, energy_keV):
        """
        Move DCCM energy with vernier correction.

        Parameters
        ----------
        energy_keV : float
            Target energy in keV

        Notes
        -----
        In simulation mode, moves simulated motor instead of real hardware.
        """
        if self.simulate:
            self.sim.fast_motor1.mv(energy_keV)
        else:
            self.dccm.energy_with_vernier(energy_keV)

    def _move_k_energy(self, k_energy):
        """
        Move undulator K energy.

        Parameters
        ----------
        k_energy : float
            Target K energy in eV

        Notes
        -----
        Updates self.k_energy after successful move.
        Uses ACR energy request system in real mode.
        """
        self.logger.warning(f"Moving K to {k_energy:.0f} eV")
        if self.simulate:
            self.sim.slow_motor1.mv(k_energy)
        else:
            self.acr_energy_k.move(k_energy)
        self.k_energy = k_energy

    def _move_vernier_energy(self, vernier_energy):
        """
        Move vernier to specified energy.

        Parameters
        ----------
        vernier_energy : float
            Target vernier energy in eV

        Notes
        -----
        Waits for move to complete before returning.
        """
        self.logger.info(f"Moving Vernier to {vernier_energy:.2f} eV")
        self.vernier_device.move(vernier_energy).wait()

    def _current_k_energy(self):
        """
        Get current K energy.

        Returns
        -------
        float
            Current K energy in eV

        Notes
        -----
        In simulation mode, returns stored value.
        In real mode, reads from ACR energy PV.
        """
        return self.k_energy if self.simulate else self.acr_energy_k.get().setpoint

    def _delta_eV_to_k_energy(self, energy_keV, abs_value=False, rounding=1):
        """
        Calculate energy delta to K energy.

        Parameters
        ----------
        energy_keV : float
            Energy to compare in keV
        abs_value : bool, optional
            Return absolute value if True (default: False)
        rounding : int, optional
            Decimal places to round to (default: 1)

        Returns
        -------
        float
            Energy difference in eV, rounded to specified precision
        """
        delta = energy_keV * 1000 - self.k_energy
        if abs_value:
            delta = np.abs(delta)
        return round(delta, rounding)

    def _next_k_energy(self, k_stepsize, k_offset, reverse, min_k_keV):
        """
        Calculate next K energy based on current position.

        Parameters
        ----------
        k_stepsize : float
            Step size in eV
        k_offset : float
            Offset to apply in eV
        reverse : bool
            True for reverse scan direction
        min_k_keV : float
            Minimum allowed K energy in keV

        Returns
        -------
        float
            Next K energy in eV

        Notes
        -----
        Ensures minimum K energy is not violated in reverse scans.
        Adds 1 eV safety margin to minimum.
        """
        k_energy = self._current_k_energy() + k_offset
        if reverse:
            k_energy -= k_stepsize
            if k_energy / 1000 < min_k_keV:
                k_energy = min_k_keV * 1000 + 1  # +1 eV safety margin
        else:
            k_energy += k_stepsize
        return k_energy

    # ==================== Energy Range Building ====================

    def _build_energy_and_wait_time(self, energies_list, wait_time_list,
                                    start_eV, end_eV, min_k, max_k, element,
                                    min_time_EXAFS, max_time_EXAFS, debug):
        """
        Build energy and wait time arrays for EXAFS scan.

        Parameters
        ----------
        energies_list : list
            Custom energy list (if provided, overrides auto-generation)
        wait_time_list : list
            Custom wait time list (must match energies_list length)
        start_eV : float
            Starting energy in eV
        end_eV : float
            Ending energy in eV
        min_k : float
            Minimum K value in Å⁻¹
        max_k : float
            Maximum K value in Å⁻¹
        element : str
            Element symbol (e.g., 'Fe', 'Cu')
        min_time_EXAFS : float
            Minimum acquisition time in EXAFS region (s)
        max_time_EXAFS : float
            Maximum acquisition time in EXAFS region (s)
        debug : bool
            If True, shows scan profile and prompts for continuation

        Returns
        -------
        tuple
            (energies, wait_times) arrays

        Raises
        ------
        ValueError
            If custom lists provided with mismatched lengths
        SystemExit
            If user declines to continue in debug mode

        Notes
        -----
        If custom lists are empty, automatically generates energy points
        based on element edge structure with appropriate time weighting.
        """
        if energies_list and wait_time_list:
            if len(wait_time_list) != len(energies_list):
                raise ValueError('wait_time and energies must have same length')
            return energies_list, wait_time_list

        foil_energies = {
            'Sc': 4492.8, 'Ti': 4966.4, 'V': 5465.1, 'Cr': 5989.2, 'Mn': 6539.0,
            'Fe': 7111.2, 'Co': 7708.9, 'Ni': 8332.8, 'Cu': 8978.9, 'Zn': 9658.6
        }
        threshold_energies = {
            'Ti': 4985.00, 'Sc': 4510.00, 'V': 5485.00, 'Cr': 6010.00,
            'Mn': 6560.00, 'Fe': 7130.00, 'Co': 7730.00, 'Ni': 8350.00,
            'Cu': 9000.00, 'Zn': 9680.00
        }

        preedge_end = foil_energies[element] + 5

        if end_eV and end_eV <= threshold_energies[element]:
            min_k = max_k = 0.0
        elif end_eV and end_eV > threshold_energies[element]:
            max_k = (0.2625 * (end_eV - threshold_energies[element])) ** 0.5

        energies, wait_time, _, _ = self.exafs_energy_range_builder.build_energy_range(
            min_before_pre_edge=start_eV,
            max_before_pre_edge=preedge_end - 6,
            preedge_end=preedge_end,
            preedge_eV_increment=0.5,
            min_K_value=min_k,
            max_K_value=max_k,
            before_edge_eV_increment=5.0,
            edge_eV_increment=1.0,
            K_spacing=0.1,
            time_before_edge=2,
            time_in_edge=1,
            time_in_preedge=2,
            min_time_EXAFS=min_time_EXAFS,
            max_time_EXAFS=max_time_EXAFS,
            debug=debug
        )

        if debug:
            answer = input("Continue? (y/n): ")
            if answer.lower() == "n":
                sys.exit("User aborted")

        return energies, wait_time

    # ==================== Initialization Methods ====================

    def _initialize_energies_and_move(self, energies, wait_time, reverse,
                                     k_offset, k_stepsize, track_feespec, crystal_angle_offset=0.0):
        """
        Initialize energy values and move to starting position.

        Parameters
        ----------
        energies : array_like
            Energy array in eV
        wait_time : array_like
            Wait time array in seconds
        reverse : bool
            True for reverse scan direction (high to low energy)
        k_offset : float
            K energy offset in eV
        k_stepsize : float
            K step size in eV
        track_feespec : bool
            True to track FEE spectrometer

        Returns
        -------
        tuple
            (energies, wait_time) - potentially reversed if reverse=True

        Notes
        -----
        Calculates initial K energy position based on scan direction.
        Moves DCCM, K motor, and optionally FEE spectrometer to start position.
        Verifies K motor position matches expected value.
        """
        energy_0_keV = energies[0] / 1000.0
        self.k_energy = energy_0_keV * 1000.0 + (k_stepsize / 2) + k_offset

        if reverse:
            energies = energies[::-1]
            wait_time = wait_time[::-1]
            energy_0_keV = energies[0] / 1000.0
            self.k_energy = energy_0_keV * 1000.0 - (k_stepsize / 2) + k_offset
            self.logger.info('REVERSED MODE: Flipping energy and time lists')

        self._move_dccm_energy_with_vernier(energy_0_keV)

        self.logger.warning(f"Moving K to initial energy: {self.k_energy:.0f} eV")
        if track_feespec:
            self.xrtspec.move_feespec_energy(
                self.k_energy / 1000, crystal_angle_offset=crystal_angle_offset)
        if round(self.k_energy, 1) != round(self._current_k_energy(), 1):
            self._move_k_energy(self.k_energy)
        if track_feespec:
            self.xrtspec.check_feespec_crystal_angle(
                self.k_energy / 1000, crystal_angle_offset=crystal_angle_offset)

        return energies, wait_time

    def _init_tfs(self, energies, margin_mm, ref_focal_length_um, ref_z_stage_mm,
                  avoid_forbidden, enable_prefocus, map_focus_track,
                  lens_beam_energy_offset, target=400.37):
        """
        Initialize transfocator system.

        Parameters
        ----------
        energies : array_like
            Energy array for focus tracking in eV
        margin_mm : float
            Safety margin in mm
        ref_focal_length_um : float
            Reference focal length in µm
        ref_z_stage_mm : float
            Reference Z stage position in mm
        avoid_forbidden : bool
            Avoid forbidden lens combinations
        enable_prefocus : bool
            Enable prefocusing capability
        map_focus_track : bool
            Generate focus tracking map
        lens_beam_energy_offset : float
            Lens beam energy offset in eV
        target : float, optional
            Target focal position (default: 400.37)

        Notes
        -----
        Creates transfocator object (simulated or real based on self.simulate).
        If map_focus_track=True, generates and displays focus tracking map.
        """
        tfs = Transfocator("MFX:LENS", name='MFX Transfocator')
        self.tfs = make_tfs_sim(tfs) if self.simulate else tfs

        if map_focus_track:
            sim_tfs = make_tfs_sim(tfs)
            sim_tfs.track_focus(
                energies=energies, margin_mm=margin_mm, show=True,
                lens_beam_energy_offset=lens_beam_energy_offset,
                ref_focal_length_um=ref_focal_length_um,
                ref_z_stage_mm=ref_z_stage_mm,
                avoid_forbidden=avoid_forbidden,
                enable_prefocus=enable_prefocus,
                target=target
            )

    def _init_tchk(self, map_tchk_track):
        """
        Initialize vernier tracking system.

        Parameters
        ---------- map_tchk_track : bool
            If True, clears existing tracking data to generate new map

        Returns
        -------
        list
            Tracking data (empty list if mapping, loaded data otherwise)

        Notes
        -----
        Initializes vernier device from beamline hardware.
        Loads existing tracking data from JSON unless mapping mode active.
        """
        from mfx.optimize.beamline_hw import init_devices

        devices = init_devices()
        self.vernier_device = devices["vernier_energy"]

        track_tchk_data = self._get_track_data("track_tchk_results.json")
        if map_tchk_track:
            self.vernier_offset = None
            track_tchk_data = []
        return track_tchk_data

    # ==================== DAQ Methods ====================

    def _setup_daq_and_start_recording(self, sample, picker, inspire, record, run_index):
        """
        Setup DAQ and start recording.

        Parameters
        ----------
        sample : str
            Sample name
        picker : str
            Pulse picker mode ('open', 'flip', or None)
        inspire : bool
            Add inspirational quote
        record : bool
            Enable data recording
        run_index : int
            Current run index

        Returns
        -------
        tuple
            (run_number, success) where success is bool indicating DAQ ready

        Notes
        -----
        In simulation mode, returns incremented run_index without DAQ interaction.
        In real mode:
        - Connects to LCLS-II DAQ
        - Checks DAQ state
        - Operates pulse picker
        - Configures and starts recording
        Returns (None, False) if DAQ connection or state check fails.
        """
        if self.simulate:
            return run_index + 1, True

        from mfx.db import daq, mfx_pulsepicker
        from mfx.macros import get_run
        from mfx.autorun import quote
        from psdaq.control.DaqControl import DaqControl

        run_number = get_run(station=0) + 1
        daq.control = DaqControl(
            host=daq.control.host,
            platform=daq.control.platform,
            timeout=10000
        )

        instr = daq.control.getInstrument()
        if instr is None:
            self.logger.error('Failed to connect to LCLS-II DAQ')
            return None, False

        if daq.control.getState() == 'error':
            self.logger.error('DAQ is in error state')
            return None, False

        self.logger.info(f"Run {run_number}: {sample} - {quote()['quote']}")

        if picker == 'open':
            mfx_pulsepicker.open()
        elif picker == 'flip':
            mfx_pulsepicker.flipflop()

        daq.control.setState("configured")
        while daq.control.getState() != "configured":
            sleep(0.01)

        daq.control.setRecord(record)
        daq.control.setState("running")
        while daq.control.getState() != "running":
            sleep(0.01)

        return run_number, True

    # ==================== Beam Status Methods ====================

    def check_beam_status(self, flux_threshold):
        """
        Check beam status and pause if below threshold.

        Parameters
        ----------
        flux_threshold : float or None
            Minimum acceptable flux in mJ (no check if None)

        Notes
        -----
        Monitors beam flux continuously:
        - Pauses DAQ if flux drops below threshold
        - Waits for beam recovery
        - Resumes DAQ when flux restored
        Uses BeamCheck from mfx.optimize.beam_status.
        """
        if flux_threshold is None or self.simulate:
            return

        from mfx.optimize.beam_status import BeamCheck
        from mfx.db import daq

        beam_status = BeamCheck()
        current_flux = beam_status.gdet_ave(threshold=flux_threshold)

        if current_flux < flux_threshold and daq.control.getState() == "running":
            self.logger.error(f'Beam below threshold ({flux_threshold} mJ). Pausing DAQ')
            daq.control.setState("paused")
            while daq.control.getState() != "paused":
                sleep(0.01)

        while beam_status.gdet_ave(threshold=flux_threshold) < flux_threshold:
            self.logger.warning('Waiting for beam recovery...')
            sleep(1)

        if current_flux > flux_threshold and daq.control.getState() == "paused":
            self.logger.info('Beam restored. Resuming DAQ')
            daq.control.setState("running")
            while daq.control.getState() != "running":
                sleep(0.01)

    # ==================== Vernier Alignment ====================

    def align_vernier_to_dccm(self, energy_center_offset_eV=0.0, energy_range_eV=5.0, energy_steps=21,
                              events_per_step=60, flux_threshold=None, diagnostic='dg2'):
        """
        Align vernier to DCCM using intensity-based optimization.

        Scans vernier around current DCCM energy and finds position
        that maximizes beam intensity. Pure intensity-based alignment
        without using calibration prediction.

        Parameters
        ----------
        energy_center_offset_eV: float, optional
            Center of the scan (default: 0.0)
        energy_range_eV : float, optional
            Range around current DCCM energy to scan in eV (default: 5.0)
        energy_steps : int, optional
            Number of steps in alignment scan (default: 21)
        events_per_step : int, optional
            Number of events to average per step (default: 60)
        flux_threshold : float or None, optional
            Minimum intensity required (default: None)

        Returns
        -------
        float or False
            Vernier offset (vernier - DCCM) in eV, or False if failed

        Notes
        -----
        Procedure:
        1. Read current DCCM energy
        2. Scan vernier ±energy_range_eV/2 around DCCM + offset
        3. Measure intensity at each point
        4. Move to position with maximum intensity
        5. Calculate and return offset

        Uses 10ms sleep between intensity readings for averaging.
        Checks beam status at each step if flux_threshold provided.
        """
        from mfx.optimize.beamline_hw import init_devices, read_dccm_energy

        devices = init_devices()
        vernier_energy_pv = devices["vernier_energy"]
        if diagnostic == 'xcs1':
            intensity_pv = devices["vernier_intensity1"]
        elif diagnostic == 'dg1':
            intensity_pv = devices["vernier_intensity2"]
        elif diagnostic == 'dg2':
            intensity_pv = devices["vernier_intensity3"]
        else:
            self.logger.error(f"Unknown diagnostic: {diagnostic}")
            return False

        current_dccm_energy = float(read_dccm_energy())
        self.logger.info(f"DCCM energy: {current_dccm_energy:.2f} eV")

        scan_start = current_dccm_energy + energy_center_offset_eV - energy_range_eV / 2
        scan_end = current_dccm_energy + energy_center_offset_eV + energy_range_eV / 2

        best_intensity = float('-inf')
        best_vernier_energy = None
        energy_list, intensity_list = [], []

        for step in range(energy_steps):
            if flux_threshold:
                self.check_beam_status(flux_threshold)

            vernier_energy = scan_start + step * (scan_end - scan_start) / (energy_steps - 1)

            try:
                vernier_energy_pv.move(vernier_energy).wait()
            except Exception as e:
                self.logger.error(f"Vernier move failed: {e}")
                return False

            intensities = []
            for _ in range(events_per_step):
                try:
                    intensities.append(float(intensity_pv.get()))
                except Exception:
                    pass
                sleep(0.01)  # 10ms between readings

            intensity = np.mean(intensities) if intensities else float(intensity_pv.get())
            energy_list.append(vernier_energy)
            intensity_list.append(intensity)

            if intensity > best_intensity:
                best_intensity = intensity
                best_vernier_energy = vernier_energy
                self.logger.warning(f"New best: {intensity:.2f} @ {vernier_energy:.2f} eV")

        # Print scan results
        self.logger.info("Alignment scan results:")
        for vernier_energy, intensity in zip(energy_list, intensity_list):
            marker = " <-- BEST" if vernier_energy == best_vernier_energy else ""
            self.logger.info(f"  {vernier_energy:.2f} eV: {intensity:.2f}{marker}")

        # Move to best position
        if best_vernier_energy:
            self.logger.info(f"Moving to optimal position: {best_vernier_energy:.2f} eV")
            vernier_energy_pv.move(best_vernier_energy).wait()

            final_dccm_energy = float(read_dccm_energy())
            final_vernier_actual = float(vernier_energy_pv.position)
            final_offset = final_vernier_actual - final_dccm_energy

            self.logger.info(f"Final DCCM: {final_dccm_energy:.2f} eV")
            self.logger.info(f"Final vernier: {final_vernier_actual:.2f} eV")
            self.logger.info(f"Alignment complete. Offset: {final_offset:.2f} eV")
            return final_offset

        self.logger.error("Alignment failed: no valid measurements")
        return False

    def _measure_vernier_offset(self, energy, track_tchk_data, diagnostic='dg2'):
        """
        Measure and store vernier offset.

        Parameters
        ----------
        energy : float
            Energy at which to measure offset in eV
        track_tchk_data : list
            Tracking data list to append result

        Notes
        -----
        Performs intensity-based alignment and appends result to tracking data.
        Uses flux_threshold from instance attribute if available.
        """
        try:
            current_offset = track_tchk_data[-1]['vernier_offset']
        except:
            current_offset = 0.0

        self.logger.info("Performing intensity-based vernier alignment")
        offset = self.align_vernier_to_dccm(
            energy_center_offset_eV=current_offset,
            energy_range_eV=5.0,
            energy_steps=21,
            events_per_step=50,
            flux_threshold=getattr(self, 'flux_threshold', None),
            diagnostic=diagnostic
        )
        print(f"... ... ... TCHK DATA NEW ITEM: {energy=} {offset=}")
        track_tchk_data.append({"energy": energy, "vernier_offset": offset})

    def _retrieve_vernier_offset(self, energy, track_tchk_data):
        """
        Retrieve vernier offset from tracking data.

        Parameters
        ----------
        energy : float
            Energy to look up in eV
        track_tchk_data : list
            Tracking data list

        Returns
        -------
        float or None
            Vernier offset in eV if found, None otherwise

        Notes
        -----
        Updates self.vernier_offset if match found.
        """
        if track_tchk_data:
            for data in track_tchk_data:
                if data["energy"] == energy:
                    self.vernier_offset = data["vernier_offset"]
                    return data["vernier_offset"]
        return None

    def _align_vernier_to_dccm(self, energy_eV, track_tchk_data, map_tchk_track, diagnostic='dg2'):
        """
        Perform vernier alignment with DCCM.

        Parameters
        ----------
        energy_eV : float
            Target energy in eV
        track_tchk_data : list
            Tracking data list
        map_tchk_track : bool
            True if building tracking map

        Notes
        -----
        Skipped in simulation mode.
        Measures new offset if needed based on _request_vernier_offset_measurement.
        Applies stored offset to energy move if available.
        """
        if self.simulate:
            return

        print(f"... checking if need to request Vernier offset measurement {energy_eV=}")
        if self._request_vernier_offset_measurement(energy_eV, track_tchk_data, map_tchk_track):
            print(f"... ... requesting Vernier offset measurement {energy_eV=}")
            self._measure_vernier_offset(energy_eV, track_tchk_data, diagnostic)
        else:
            print(f"... ... not needed.")

        if self.vernier_offset is not None and self.vernier_offset is not False:
            self._move_dccm_energy_with_vernier((energy_eV + self.vernier_offset) / 1000)

    def _request_vernier_offset_measurement(self, energy, track_tchk_data, map_tchk_track):
        """
        Determine if vernier offset measurement is needed.

        Parameters
        ----------
        energy : float
            Current energy in eV
        track_tchk_data : list
            Tracking data list
        map_tchk_track : bool
            True if building tracking map

        Returns
        -------
        bool
            True if measurement needed, False otherwise

        Notes
        -----
        Measurement needed if:
        - Close to K energy (<0.1 eV) and mapping mode active
        - No offset available in tracking data
        """
        if self._delta_eV_to_k_energy(energy / 1000, abs_value=True) < 0.1 and map_tchk_track:
            return True
        if self._retrieve_vernier_offset(energy, track_tchk_data) is None:
            return True
        return False

    # ==================== Transfocator Methods ====================

    def _move_tfs_to_energy(self, energy_eV, track_focus_data, attenuation=None, tfs_offset=0.0):
        """
        Move transfocator to energy configuration.

        Parameters
        ----------
        energy_eV : float
            Target energy in eV
        track_focus_data : list
            Focus tracking data with lens configurations
        attenuation : float or None
            Attenuation value to set (default: None)

        Notes
        -----
        Looks up energy in tracking data and:
        1. Moves Z stage to specified position
        2. Inserts/removes lenses per configuration
        3. Sets attenuation if provided

        Waits for each motion to complete before proceeding.
        Handles attenuator fault state with 20s timeout.
        Skips if energy not found in tracking data.
        """
        if track_focus_data is None:
            self.logger.warning("No track_focus_data available")
            return

        energy_eV = float(energy_eV)
        #target_config = next((d for d in track_focus_data if d["energy"] == energy_eV), None)
        target_config = min(track_focus_data, key=lambda d: abs(d['energy']-energy_eV))
        #should add if the target config E and target energy are too far apart it returns None or does something

        if not target_config:
            self.logger.warning(f"Energy {energy_eV} eV not found in tracking data")
            return

        z_position = target_config["z_position"]+tfs_offset
        inserted_lenses = [
            lens.replace('SIM::', 'MFX:LENS:')
            for lens in target_config["inserted_lenses"]
        ]

        # Move Z stage
        if z_position is not None:
            self.logger.info(f"Moving TFS to {z_position:.3f} mm")
            self.tfs.translation.umv(z_position)
            while self.tfs.translation.moving:
                sleep(0.1)

        # Configure lenses
        for lens in self.tfs.lenses:
            if lens.prefix in inserted_lenses:
                if not lens.inserted:
                    lens.insert()
                    sleep(0.5)
                    while lens.moving:
                        sleep(0.1)
            else:
                if lens.inserted:
                    lens.remove()
                    sleep(0.5)
                    while lens.moving:
                        sleep(0.1)

        # Set attenuation
        if attenuation is not None:
            timeout = 20
            start_time = time()

            while os.popen("caget MFX:ATT:COM:STATUS | awk '{print $2}'").read().strip() == 'Faulted':
                if time() - start_time > timeout:
                    self.logger.error("ATT faulted after 20s timeout")
                    os.system('caput MFX:ATT:COM:STATUS OK')
                    break
                self.logger.warning("ATT faulted, waiting...")
                sleep(1)

            from mfx.db import mfx_attenuator as att
            att(attenuation)

    # ==================== K Energy Management ====================

    def _request_k_energy_update(self, energy_keV, k_stepsize, k_offset, reverse, min_k_keV):
        """
        Check if K energy update is needed.

        Parameters
        ----------
        energy_keV : float
            Current scan energy in keV
        k_stepsize : float
            K step size in eV
        k_offset : float
            K offset in eV
        reverse : bool
            Reverse scan direction
        min_k_keV : float
            Minimum K energy in keV

        Returns
        -------
        bool
            True if K update needed, False otherwise

        Notes
        -----
        Update needed if distance from K exceeds stepsize/2.
        Calculates next K energy and compares to current (rounded to 0.1 eV).
        """
        delta = self._delta_eV_to_k_energy(energy_keV, abs_value=True)
        self.logger.info(f"Distance from K: {delta:.1f} eV")

        if delta > k_stepsize / 2:
            new_k_energy = self._next_k_energy(k_stepsize, k_offset, reverse, min_k_keV)
            if round(new_k_energy, 1) != round(self._current_k_energy(), 1):
                self.logger.info(f"K update needed: {self._current_k_energy():.0f} → {new_k_energy:.0f} eV")
                return True
        return False

    def _move_k_if_necessary(self, energy_keV, k_stepsize, k_offset,
                            reverse, min_k_keV, track_feespec,
                            crystal_angle_offset=0.0):
        """
        Move K if necessary and manage DAQ state.

        Parameters
        ----------
        energy_keV : float
            Current scan energy in keV
        k_stepsize : float
            K step size in eV
        k_offset : float
            K offset in eV
        reverse : bool
            Reverse scan direction
        min_k_keV : float
            Minimum K energy in keV
        track_feespec : bool
            Track FEE spectrometer
        crystal_angle_offset : float, optional
            FEE spectrometer crystal angle offset in degrees (default: 0.0)

        Notes
        -----
        If K move needed:
        1. Pause DAQ (real mode only)
        2. Move FEE spectrometer (if tracking)
        3. Move K energy
        4. Check FEE crystal angle (if tracking)
        5. Resume DAQ (real mode only)

        DAQ pause/resume only in real mode, not simulation.
        """
        if not self._request_k_energy_update(energy_keV, k_stepsize, k_offset, reverse, min_k_keV):
            return

        new_k_energy = self._next_k_energy(k_stepsize, k_offset, reverse, min_k_keV)

        if not self.simulate:
            from mfx.db import daq
            self.logger.info("Pausing DAQ for K move")
            daq.control.setState("paused")
            while daq.control.getState() != "paused":
                sleep(0.01)
            sleep(0.5)

        if track_feespec:
            self.xrtspec.move_feespec_energy(
                new_k_energy / 1000, crystal_angle_offset=crystal_angle_offset)

        self._move_k_energy(new_k_energy)

        if track_feespec:
            self.xrtspec.check_feespec_crystal_angle(
                new_k_energy / 1000, crystal_angle_offset=crystal_angle_offset)

        if not self.simulate:
            from mfx.db import daq
            self.logger.info("Resuming DAQ after K move")
            daq.control.setState("running")
            while daq.control.getState() != "running":
                sleep(0.01)

    # ==================== Undulator Alignment ====================

    def _align_undulator(self, on_diagnostic, using_device, with_method, grid_bins):
        """
        Perform undulator alignment using beam alignment system.

        Parameters
        ----------
        on_diagnostic : str
            Diagnostic location ('dg1', 'dg2', 'xcs1')
        using_device : str
            Device to use ('yag', 'wave8')
        with_method : str
            Alignment method ('calib', 'turbo')
        grid_bins : int
            Number of grid bins for calibration

        Notes
        -----
        In simulation mode, initializes sim_devices first.
        Uses Beam.align() with fixed parameters:
        - use_2d_markers=True
        - mover="und"

        Catches exceptions to allow scan continuation if alignment fails.
        """
        if self.simulate:
            try:
                from mfx.optimize.beamline_hw import sim_devices
                sim_devices()
                self.logger.info("Simulation devices initialized for undulator alignment")
            except Exception as e:
                self.logger.warning(f"Failed to set simulation devices: {e}")
                return

        try:
            from mfx.optimize.beam import Beam
            beam = Beam()
            beam.align(
                on_diagnostic=on_diagnostic,
                using_device=using_device,
                use_2d_markers=True,
                mover="und",
                with_method=with_method,
                grid_bins=grid_bins
            )
        except Exception as e:
            self.logger.warning(f"Undulator alignment failed: {e}")

    # ==================== Tracking Data Methods ====================

    def _get_track_data(self, json_file_name):
        """
        Load tracking data from JSON file.

        Parameters
        ----------
        json_file_name : str
            JSON filename in user home directory

        Returns
        -------
        list or None
            Tracking data if file exists, None otherwise

        Notes
        -----
        Searches for file in Path.home() directory.
        Returns None if file doesn't exist or loading fails.
        Logs info/warning messages about file status.
        """
        try:
            track_path = Path.home() / json_file_name
            if track_path.exists():
                with open(track_path, "r") as f:
                    track_data = json.load(f)
                self.logger.info(f"Loaded {json_file_name}")
                return track_data
            self.logger.info(f"No {json_file_name} found")
        except Exception as e:
            self.logger.warning(f"Failed to load {json_file_name}: {e}")
        return None

    def _save_track_data(self, track_record, json_file_name):
        """
        Save tracking data to JSON file.

        Parameters
        ----------
        track_record : list
            Tracking data to save
        json_file_name : str
            JSON filename in user home directory

        Notes
        -----
        Saves to Path.home() directory with indent=4 formatting.
        """
        track_path = Path.home() / json_file_name
        with open(track_path, "w") as f:
            json.dump(track_record, f, indent=4)
        self.logger.info(f"Saved {json_file_name}")

    def _save_track_tchk_data(self, track_record, display=True):
        """
        Save vernier tracking data.

        Parameters
        ----------
        track_record : list
            Vernier tracking data
        display : bool, optional
            Plot data after saving (default: True)

        Notes
        -----
        Saves to track_tchk_results.json in home directory.
        Optionally displays plot of offset vs energy.
        """
        self._save_track_data(track_record, "track_tchk_results.json")
        if display:
            self._plot_track_tchk_data("track_tchk_results.json")

    def _plot_track_tchk_data(self, json_file_name):
        """
        Plot vernier offset vs energy.

        Parameters
        ----------
        json_file_name : str
            JSON file containing vernier tracking data

        Notes
        -----
        Creates matplotlib plot:
        - X-axis: Energy (eV)
        - Y-axis: Vernier offset (eV)
        - Blue line with circle markers
        """
        json_file_path = Path.home() / json_file_name
        with open(json_file_path, 'r') as f:
            data = json.load(f)

        energies = [entry['energy'] for entry in data]
        offsets = [entry['vernier_offset'] for entry in data]

        plt.figure(figsize=(12, 8))
        plt.plot(energies, offsets, marker='o', linestyle='-', color='b')
        plt.title('Vernier Offset vs Energy')
        plt.xlabel('Energy (eV)')
        plt.ylabel('Vernier Offset (eV)')
        plt.grid(True)
        plt.show()

    def _measure_lens_beam_offset(self, energy, track_lens_offset_data):
        """
        Measure lens beam energy offset.

        Parameters
        ----------
        energy : float Current energy in eV
        track_lens_offset_data : list
            Tracking data list to append result

        Notes
        -----
        Reads MFX:LENS:BEAM:ENERGY PV and stores with energy.
        Used for tracking lens system energy calibration.
        """
        lens_beam_energy = os.popen("caget MFX:LENS:BEAM:ENERGY | awk '{print $2}'").read().strip()
        track_lens_offset_data.append({
            "energy": energy,
            "lens_beam_energy": lens_beam_energy
        })

    # ==================== Cleanup Methods ====================

    def _return_to_start(self, energy_start, k_energy_start):
        """
        Return to initial positions.

        Parameters
        ----------
        energy_start : float
            Initial DCCM energy in keV
        k_energy_start : float
            Initial K energy in eV

        Notes
        -----
        In real mode:
        - Stops DAQ recording
        - Closes pulse picker
        - Returns DCCM and K to initial positions

        In simulation mode:
        - Only moves DCCM and K
        """
        if self.simulate:
            k_energy = k_energy_start
        else:
            from mfx.db import daq, mfx_pulsepicker
            k_energy = self.acr_energy_k.get().setpoint
            daq.control.setState("configured")
            while daq.control.getState() != "configured":
                sleep(0.01)
            daq.control.setRecord(False)
            daq.control.setState("running")
            mfx_pulsepicker.close()

        self.logger.info('Returning to initial position')
        self._move_dccm_energy_with_vernier(energy_start)
        if round(k_energy_start, 1) != round(k_energy, 1):
            self._move_k_energy(k_energy_start)

    def _handle_keyboard_interrupt(self, sample, tag, run_number, record,
                                   inspire, energy_start, k_energy_start, crystal_angle_offset=0.0):
        """
        Handle KeyboardInterrupt and cleanup.

        Parameters
        ----------
        sample : str
            Sample name
        tag : str
            Run tag
        run_number : int
            Run number
        record : bool
            Recording flag
        inspire : bool
            Inspirational quote flag
        energy_start : float
            Initial DCCM energy in keV
        k_energy_start : float
            Initial K energy in eV

        Notes
        -----
        Posts elog message if recording was active.
        Returns all motors to initial positions.
        Includes FEE spectrometer return.
        """
        if not self.simulate and record:
            self._post(
                sample=sample, tag=tag, run_number=run_number,
                post=record, inspire=inspire,
                add_note='Run ended prematurely'
            )

        self.logger.warning("Stopping run and cleaning up...")
        self._return_to_start(energy_start, k_energy_start)
        if not self.simulate and self.xrtspec:
            self.xrtspec.move_feespec_energy(
                energy_start, crystal_angle_offset=crystal_angle_offset)
            self.xrtspec.check_feespec_crystal_angle(
                energy_start, crystal_angle_offset=crystal_angle_offset)
        self.logger.warning('Run ended prematurely')

    def _finalize_scan(self, energy_start, k_energy_start, crystal_angle_offset=0.0):
        """
        Finalize scan and return to initial positions.

        Parameters
        ----------
        energy_start : float
            Initial DCCM energy in keV
        k_energy_start : float
            Initial K energy in eV

        Notes
        -----
        Returns DCCM, K, and FEE spectrometer to initial positions.
        Logs completion message.
        """
        self._return_to_start(energy_start, k_energy_start)
        if not self.simulate and self.xrtspec:
            self.xrtspec.move_feespec_energy(
                energy_start, crystal_angle_offset=crystal_angle_offset)
            self.xrtspec.check_feespec_crystal_angle(
                energy_start, crystal_angle_offset=crystal_angle_offset)
        self.logger.warning('Scan completed successfully\n')

    def _wait(self, wait_time):
        """
        Wait for specified time.

        Parameters
        ----------
        wait_time : float
            Time to wait in seconds

        Notes
        -----
        Defaults to 0.1s if wait_time is NaN.
        """
        sleep(0.1 if np.isnan(wait_time) else wait_time)

    # ==================== Elog Posting ====================

    def _post(self, sample='?', tag=None, run_number=None, post=False,
              inspire=False, add_note=''):
        """
        Post message to elog.

        Parameters
        ----------
        sample : str, optional
            Sample name (default: '?')
        tag : str or None, optional
            Run tag (defaults to sample if None)
        run_number : int or None, optional
            Run number (auto-detected if None)
        post : bool, optional
            Actually post to elog if True (default: False)
        inspire : bool, optional
            Add inspirational quote (default: False)
        add_note : str, optional
            Additional note to append (default: '')

        Returns
        -------
        str
            Complete post message

        Notes
        -----
        Builds comprehensive parameter summary from instance attributes.
        Always prints message to console.
        Only posts to elog if post=True.
        """
        from mfx.db import elog
        from mfx.autorun import quote
        from mfx.macros import get_run

        if tag is None:
            tag = sample
        if run_number is None:
            run_number = get_run(station=0)

        comment = f"Running {sample}"
        if inspire:
            comment += f"\n{quote()['quote']}"
        if add_note:
            comment += f"\n{add_note}"

        # Build parameter summary
        param_names = [
            'simulate', 'start_eV', 'end_eV', 'min_k', 'max_k', 'element',
            'picker', 'inspire', 'daq_delay', 'record', 'runs', 'k_stepsize',
            'reverse', 'min_k_keV', 'k_offset', 'flux_threshold', 'attenuation',
            'min_time_EXAFS', 'max_time_EXAFS', 'tchk', 'map_focus_track',
            'track_focus', 'track_feespec', 'undulator_point', 'debug', 'diagnostic'
        ]

        params = {name: getattr(self, name, None) for name in param_names}

        post_msg = f"Run Number {run_number}: {comment}\n\n"
        post_msg += "\n".join(f"{k} -> {v}" for k, v in params.items())

        print(f'\n{post_msg}\n')
        if post:
            elog.post(msg=post_msg, tags=tag, run=run_number)
        return post_msg

    # ==================== Main Scan Methods ====================

    def long_escan(self, simulate=False, start_eV=0.0, end_eV=None,
                   min_k=2.0, max_k=12.0, energies_list=None, wait_time_list=None,
                   element='Fe', sample='?', tag=None, picker=None,
                   inspire=False, daq_delay=5, record=False, runs=1,
                   k_stepsize=120, reverse=False, min_k_keV=7.035,
                   k_offset=0, flux_threshold=None, attenuation=None,
                   min_time_EXAFS=0.5, max_time_EXAFS=10.0, tchk=False,
                   diagnostic='dg2', map_focus_track=False,
                   map_tchk_track=False, map_lens_beam_energy_offset=False,
                   lens_beam_energy_offset=0.0, track_focus=False, crystal_angle_offset=0.0,
                   tfs_margin_mm=5.0, ref_focal_length_um=None,
                   ref_z_stage_mm=None, tfs_target=400.37,
                   avoid_forbidden_combo=True, enable_prefocus=True,
                   track_feespec=False, track_feespec_cam=False,
                   undulator_point=False, undulator_on_diagnostic="dg1",
                   undulator_using_device="yag", undulator_with_method="calib",
                   undulator_grid_bins=5, debug=False,tfs_offset=0.0):
        """
        Perform EXAFS scan with comprehensive automation.

        Main EXAFS scan function supporting energy scanning, vernier tracking,
        focus tracking, undulator pointing, and FEE spectrometer tracking.

        Parameters
        ----------
        simulate : bool, optional
            Run in simulation mode (default: False)
        start_eV : float, optional
            Starting photon energy in eV (default: 0.0)
        end_eV : float or None, optional
            Ending photon energy in eV (default: None)
        min_k : float, optional
            Minimum K value in Å⁻¹ (default: 2.0)
        max_k : float, optional
            Maximum K value in Å⁻¹ (default: 12.0)
        energies_list : list, optional
            Custom energy array (overrides auto-generation) (default: [])
        wait_time_list : list, optional
            Custom wait time array (must match energies_list) (default: [])
        element : str, optional
            Element symbol (default: 'Fe')
        sample : str, optional
            Sample name (default: '?')
        tag : str or None, optional
            Run tag (defaults to sample if None)
        picker : str or None, optional
            Pulse picker mode: 'open', 'flip', or None
        inspire : bool, optional
            Add inspirational quote to elog (default: False)
        daq_delay : int, optional
            Delay between runs in seconds (default: 5)
        record : bool, optional
            Enable data recording (default: False)
        runs : int, optional
            Number of scan repetitions (default: 1)
        k_stepsize : int, optional
            Undulator K step size in eV (default: 120)
        reverse : bool, optional
            Scan high to low energy (default: False)
        min_k_keV : float, optional
            Minimum K energy in keV (default: 7.035)
        k_offset : int, optional
            K energy offset in eV (default: 0)
        flux_threshold : float or None, optional
            Minimum beam flux in mJ (no check if None)
        attenuation : float or None, optional
            Attenuation value to set
        min_time_EXAFS : float, optional
            Minimum EXAFS acquisition time in seconds (default: 0.5)
        max_time_EXAFS : float, optional
            Maximum EXAFS acquisition time in seconds (default: 10.0)
        tchk : bool or str, optional
            Vernier tracking: False/True/'single' (default: False)
        diagnostic : str, optional
            Diagnostic for vernier tracking: 'dg1', 'dg2', 'xcs1' (default: 'dg2')
        map_focus_track : bool, optional
            Pre-map focus tracking and exit (default: False)
        map_tchk_track : bool, optional
            Pre-map vernier tracking (default: False)
        map_lens_beam_energy_offset : bool, optional
            Map lens beam energy offset (default: False)
        lens_beam_energy_offset : float, optional
            Lens beam energy offset in eV (default: 0.0)
        track_focus : bool, optional
            Enable focus tracking during scan (default: False)
        crystal_angle_offset : float, optional
            Offset to add to the calculated crystal angle in degrees. Used for
            fine-tuning calibration or compensating for systematic errors.
            Positive values increase the crystal angle. Default: 0.0
        tfs_margin_mm : float, optional
            Transfocator margin in mm (default: 5.0)
        ref_focal_length_um : float or None, optional
            Reference focal length in µm
        ref_z_stage_mm : float or None, optional
            Reference Z stage position in mm
        tfs_target : float, optional
            TFS target position (default: 400.37)
        avoid_forbidden_combo : bool, optional
            Avoid forbidden lens combinations (default: True)
        enable_prefocus : bool, optional
            Enable prefocusing (default: True)
        track_feespec : bool, optional
            Track FEE spectrometer (default: False)
        track_feespec_cam : bool, optional
            Track FEE spectrometer camera (default: False)
        undulator_point : bool, optional
            Perform undulator pointing (default: False)
        undulator_on_diagnostic : str, optional
            Diagnostic location: 'dg1', 'dg2', 'xcs1' (default: 'dg1')
        undulator_using_device : str, optional
            Device for alignment: 'yag', 'wave8' (default: 'yag')
        undulator_with_method : str, optional
            Alignment method: 'calib', 'turbo' (default: 'calib')
        undulator_grid_bins : int, optional
            Grid bins for calibration (default: 5)
        debug : bool, optional
            Enable debug output (default: False)

        Returns
        -------
        None
            Returns early if map_focus_track=True after mapping

        Notes
        -----
        Scan procedure:
        1. Initialize devices and store initial positions
        2. Build/load energy and wait time arrays
        3. Initialize tracking systems (focus, vernier)
        4. For each run:
           a. Move to start position
           b. Check beam status
           c. Setup DAQ
           d. Perform undulator pointing (optional)
           e. For each energy point:
              - Move K if needed
              - Move transfocator (if tracking)
              - Check beam status
              - Perform vernier alignment (if enabled)
              - Move DCCM
              - Track FEE camera (if enabled)
              - Wait acquisition time
           f. Save tracking data
        5. Return to initial positions

        Handles KeyboardInterrupt for graceful abort.
        Posts elog messages if recording enabled.
        """

        # Store parameters as instance attributes
        for key, value in locals().items():
            if key not in ['self', 'kwargs']:
                setattr(self, key, value)

        # Log configuration
        bool_params = [
            'simulate', 'inspire', 'record', 'reverse', 'tchk',
            'map_focus_track', 'track_focus', 'map_tchk_track',
            'avoid_forbidden_combo', 'enable_prefocus', 'track_feespec',
            'track_feespec_cam', 'undulator_point', 'debug'
        ]

        for param in bool_params:
            value = getattr(self, param)
            log_fn = self.logger.error if value else self.logger.warning
            param_display = param.replace('_', ' ').title()
            log_fn(f"{param_display}: {'ON' if value else 'OFF'}")

        # Initialize devices if needed
        if not simulate:
            from mfx.devices import LaserShutter
            self.opo_shutter = LaserShutter('MFX:USR:ao1:6', name='opo_shutter')
            self.fe_foil = LaserShutter('MFX:USR:ao1:3', name='fe_foil')
            self.nd_wheel = EpicsSignalRO("MFX:LAS:MMN:08", name="nd_wheel")
            self.waveplate = EpicsSignalRO("MFX:LAS:MMN:10", name="waveplate")

        # Store initial positions
        if simulate:
            energy_start = (energies_list[0] / 1000.0) if energies_list else start_eV / 1000.0
            k_energy_start = (energies_list[0] if energies_list else start_eV) + k_stepsize / 2 + k_offset
        else:
            energy_start = self.dccm.energy_with_vernier.energy()
            k_energy_start = self.acr_energy_k.get().setpoint

        # Build energy arrays
        energies, wait_times = self._build_energy_and_wait_time(
            energies_list, wait_time_list, start_eV, end_eV, min_k, max_k,
            element, min_time_EXAFS, max_time_EXAFS, debug
        )

        # Initialize tracking systems
        track_focus_data = self._get_track_data("track_focus_results.json") if not map_focus_track else None

        if track_focus or map_focus_track:
            self._init_tfs(
                energies, tfs_margin_mm, ref_focal_length_um, ref_z_stage_mm,
                avoid_forbidden_combo, enable_prefocus, map_focus_track,
                lens_beam_energy_offset, tfs_target
            )

        if map_focus_track:
            return

        track_tchk_data = self._init_tchk(map_tchk_track) if (tchk or tchk == 'single') else None
        track_lens_offset_data = []
        if map_lens_beam_energy_offset:
            track_lens_offset_data = []

        # Main scan loop
        try:
            for run_idx in range(runs):
                # Initialize energies and move to start
                energies, wait_times = self._initialize_energies_and_move(
                    energies, wait_times, reverse,
                    k_offset, k_stepsize, track_feespec, crystal_angle_offset
                )

                # Check beam
                if flux_threshold:
                    self.check_beam_status(flux_threshold)

                # Setup DAQ
                run_number, daq_success = self._setup_daq_and_start_recording(
                    sample, picker, inspire, record, run_idx
                )

                if not daq_success:
                    break

                if record:
                    self._post(
                        sample=sample, tag=tag, run_number=run_number,
                        post=record, inspire=inspire,
                        add_note=f'Starting run {run_idx + 1} of {runs}'
                    )

                # Undulator pointing
                if undulator_point:
                    self._align_undulator(
                        undulator_on_diagnostic, undulator_using_device,
                        undulator_with_method, undulator_grid_bins
                    )

                # Energy scan
                for ii, (energy, wait_time) in enumerate(zip(energies, wait_times)):
                    self.logger.info(f"Step {ii + 1}/{len(energies)}: {energy:.2f} eV, {wait_time:.2f}s")
                    energy_keV = energy / 1000.0

                    # Move K if necessary
                    self._move_k_if_necessary(
                        energy_keV, k_stepsize, k_offset, reverse, min_k_keV,
                        track_feespec, crystal_angle_offset
                    )

                    # Move TFS
                    if track_focus:
                        self._move_tfs_to_energy(energy, track_focus_data, attenuation,tfs_offset)

                    # Check beam
                    if flux_threshold:
                        self.check_beam_status(flux_threshold)

                   # Move DCCM
                    self._move_dccm_energy_with_vernier(energy_keV)

                    # Vernier alignment
                    if tchk == 'single':
                        offset = self._retrieve_vernier_offset(energy, track_tchk_data)
                        if offset is None:
                            self._measure_vernier_offset(energy, track_tchk_data, diagnostic)
                        if map_tchk_track:
                            self._save_track_tchk_data(track_tchk_data)
                    elif tchk:
                        print(f"DEBUG ALIGN TCHK {energy=}")
                        self._align_vernier_to_dccm(
                            energy, track_tchk_data, map_tchk_track, diagnostic)
                        # Save tracking data
                        if tchk and map_tchk_track:
                            print(f"DEBUG SAVING TCHK DATA {energy=} {track_tchk_data=}")
                            self._save_track_tchk_data(track_tchk_data, display=False)

                    if track_feespec_cam:
                        self.xrtspec.track_feespec_camera(energy_keV, crystal_angle_offset)

                    if map_lens_beam_energy_offset:
                        self._measure_lens_beam_offset(energy, track_lens_offset_data)

                    # Wait
                    self._wait(wait_time)

                # Save tracking data
                if tchk and map_tchk_track:
                    self._save_track_tchk_data(track_tchk_data)

                if map_lens_beam_energy_offset:
                    self._save_track_data(track_lens_offset_data, "track_lens_beam_offset_results.json")

                if record:
                    self._post(
                        sample=sample, tag=tag, run_number=run_number,
                        post=record, inspire=inspire,
                        add_note=f'Completed run {run_idx + 1} of {runs}'
                    )

                sleep(daq_delay)

        except KeyboardInterrupt:
            self._handle_keyboard_interrupt(
                sample, tag, run_number, record, inspire,
                energy_start, k_energy_start, crystal_angle_offset
            )

        self._finalize_scan(energy_start, k_energy_start, crystal_angle_offset)

    # ==================== K-Primary XAS Scan ====================

    def k_xas_scan(self, start_eV=None, end_eV=None, element='Fe',
                   k_step_eV=None, k_positions=None, k_move_mode='pause',
                   dccm_window_eV=2.0, dccm_step_eV=1.0,
                   dccm_offsets=None, dwell_time=3.0,
                   record=False, picker=None,
                   track_feespec=False, track_feespec_cam=False,
                   flux_threshold=None,
                   crystal_angle_offset=0.0,
                   sample='?', simulate=False, runs=1):
        """
        K-primary XAS scan: undulator K is the primary scan axis,
        DCCM steps within a small window around each K position.

        Designed for commissioning undulator motion and evaluating
        data quality during K transit. No vernier requests are made.

        Parameters
        ----------
        start_eV : float or None, optional
            Starting energy in eV (ignored if k_positions provided)
        end_eV : float or None, optional
            Ending energy in eV (ignored if k_positions provided)
        element : str, optional
            Element symbol (default: 'Fe')
        k_step_eV : float or None, optional
            K step size in eV. Defaults to 2*dccm_window_eV (seamless tiling).
            Ignored if k_positions provided.
        k_positions : array_like or None, optional
            Explicit list of K energies in eV. If provided, overrides
            start_eV/end_eV/k_step_eV. Rounded to 0.1 eV, deduplicated,
            and sorted ascending.
        k_move_mode : str, optional
            'pause': Pause DAQ, move K, wait, resume DAQ (default)
            'concurrent': Request K non-blocking, immediately step DCCM
        dccm_window_eV : float, optional
            DCCM scans ±this around K center (default: 2.0)
        dccm_step_eV : float, optional
            DCCM step size within window (default: 1.0)
        dccm_offsets : list or None, optional
            Explicit list of DCCM offsets in eV relative to K center.
            If provided, overrides dccm_window_eV and dccm_step_eV.
        dwell_time : float, optional
            Collection time per DCCM point in seconds (default: 3.0)
        record : bool, optional
            Enable DAQ recording (default: False)
        picker : str or None, optional
            Pulse picker mode: 'open', 'flip', or None
        track_feespec : bool, optional
            Track FEE spectrometer at each K move (default: False)
        track_feespec_cam : bool, optional
            Track FEE spectrometer camera at each DCCM point (default: False)
        flux_threshold : float or None, optional
            Minimum beam flux in mJ (default: None)
        crystal_angle_offset : float, optional
            FEE spectrometer crystal angle offset in degrees (default: 0.0)
        sample : str, optional
            Sample name (default: '?')
        simulate : bool, optional
            Run in simulation mode (default: False)
        runs : int, optional
            Number of scan repetitions (default: 1)

        Returns
        -------
        list of dict
            Summary of each collection point:
            [{'k_target_eV': float, 'dccm_energy_eV': float,
              'dccm_offset_eV': float, 'k_move_mode': str,
              'run_index': int, 'point_index': int}, ...]

        Notes
        -----
        K positions are computed as arange(start_eV, end_eV, k_step_eV).
        Default k_step_eV = 2*dccm_window_eV gives seamless energy tiling
        with no gaps between successive DCCM windows.

        Uses dccm.energy (crystal-only) — no vernier requests are issued.
        This is required for experiments where the vernier PV is rejected
        by the accelerator.

        In 'concurrent' mode, early DCCM points at each K position are
        collected while the undulator is still settling. This allows
        evaluating data quality during transit vs. after settling.

        Examples
        --------
        Mode 1 — K at every point (undulator moves at each energy):

        >>> roi_scan = [7095, 7098, 7101, 7104, 7106.3, 7106.6, ...]
        >>> summary = exafs.k_xas_scan(k_positions=roi_scan,
        ...     dccm_offsets=[0.0], dwell_time=1.0,
        ...     track_feespec=True, simulate=True)

        Mode 2 — DCCM probes window around each K position:

        >>> summary = exafs.k_xas_scan(start_eV=7095, end_eV=7195,
        ...     k_step_eV=4.0, dccm_window_eV=2.0, dccm_step_eV=1.0,
        ...     track_feespec=True, simulate=True)

        Concurrent K moves (collect during transit):

        >>> summary = exafs.k_xas_scan(start_eV=7095, end_eV=7195,
        ...     k_step_eV=1.0, dccm_offsets=[0.0],
        ...     k_move_mode='concurrent', simulate=True)
        """
        self.simulate = simulate

        # === Parameter defaults and validation ===
        if k_move_mode not in ('pause', 'concurrent'):
            raise ValueError(f"k_move_mode must be 'pause' or 'concurrent', got '{k_move_mode}'")

        if dccm_offsets is None:
            dccm_offsets = np.round(np.arange(
                -dccm_window_eV, dccm_window_eV + dccm_step_eV / 2, dccm_step_eV
            ), 1).tolist()
            dccm_offsets = sorted(set(dccm_offsets))

        # Compute K positions
        if k_positions is not None:
            k_positions_eV = sorted(set(np.round(k_positions, 1).tolist()))
        else:
            if start_eV is None or end_eV is None:
                raise ValueError("Must provide either k_positions or both start_eV and end_eV")
            if k_step_eV is None:
                k_step_eV = 2 * dccm_window_eV
            k_positions_eV = np.round(
                np.arange(start_eV, end_eV + k_step_eV / 2, k_step_eV), 1
            )
            k_positions_eV = sorted(set(k_positions_eV.tolist()))

        # Normalize dwell_time to per-K-position array
        n_k = len(k_positions_eV)
        if np.ndim(dwell_time) == 0:
            dwell_times = np.full(n_k, float(dwell_time))
        else:
            dwell_times = np.asarray(dwell_time, dtype=float)
            if len(dwell_times) != n_k:
                raise ValueError(
                    f"dwell_time list length ({len(dwell_times)}) must match "
                    f"number of K positions ({n_k})"
                )

        # Total points
        total_points = n_k * len(dccm_offsets) * runs

        # === Print scan configuration ===
        print("\n" + "=" * 60)
        print("K-PRIMARY XAS SCAN (k_xas_scan)")
        print("=" * 60)
        print(f"  Element:         {element}")
        print(f"  Energy range:    {k_positions_eV[0]:.1f} - {k_positions_eV[-1]:.1f} eV")
        if k_step_eV is not None:
            print(f"  K step:          {k_step_eV:.1f} eV")
        else:
            print(f"  K step:          custom ({n_k} positions)")
        print(f"  K positions:     {n_k} ({k_positions_eV[0]:.1f} to {k_positions_eV[-1]:.1f} eV)")
        print(f"  K move mode:     {k_move_mode}")
        print(f"  DCCM offsets:    {dccm_offsets} eV")
        print(f"  DCCM points/K:   {len(dccm_offsets)}")
        if dwell_times[0] == dwell_times[-1]:
            print(f"  Dwell time:      {dwell_times[0]:.2f} s")
        else:
            print(f"  Dwell time:      {dwell_times[0]:.2f} - {dwell_times[-1]:.2f} s ({n_k} values)")
        print(f"  Runs:            {runs}")
        print(f"  Total points:    {total_points}")
        print(f"  Record:          {record}")
        print(f"  Picker:          {picker}")
        print(f"  Track FEE spec:  {track_feespec}")
        print(f"  Track FEE cam:   {track_feespec_cam}")
        print(f"  Flux threshold:  {flux_threshold}")
        print(f"  Simulate:        {simulate}")
        print(f"  Sample:          {sample}")
        est_time = float(np.sum(dwell_times) * len(dccm_offsets) * runs)
        if k_move_mode == 'pause':
            est_time += n_k * runs * 4  # ~4s per K move
        print(f"  Est. time:       {est_time:.0f}s ({est_time/60:.1f} min)")
        print("=" * 60 + "\n")

        # === Store initial positions ===
        if simulate:
            energy_start = 7.0  # dummy for sim
            k_energy_start = k_positions_eV[0]
        else:
            energy_start = self.dccm.energy_with_vernier.energy()
            k_energy_start = self.acr_energy_k.get().setpoint

        # === Summary collector ===
        summary = []
        point_index = 0

        # === Main scan loop ===
        try:
            for run_idx in range(runs):
                self.logger.warning(f"Starting run {run_idx + 1}/{runs}")

                # Setup DAQ
                run_number, daq_success = self._setup_daq_and_start_recording(
                    sample, picker, False, record, run_idx
                )
                if not daq_success:
                    self.logger.error("DAQ setup failed, aborting")
                    break

                for k_idx, k_target_eV in enumerate(k_positions_eV):
                    k_target_keV = k_target_eV / 1000.0

                    self.logger.warning(
                        f"K position {k_idx + 1}/{len(k_positions_eV)}: "
                        f"{k_target_eV:.1f} eV [{k_move_mode}]"
                    )

                    if k_move_mode == 'pause':
                        self._k_xas_move_pause(
                            k_target_eV, k_target_keV,
                            track_feespec, crystal_angle_offset
                        )
                    elif k_move_mode == 'concurrent':
                        self._k_xas_move_concurrent(
                            k_target_eV, k_target_keV,
                            track_feespec, crystal_angle_offset
                        )

                    # Step DCCM through offsets
                    for offset in dccm_offsets:
                        dccm_energy_eV = k_target_eV + offset
                        dccm_energy_keV = dccm_energy_eV / 1000.0

                        self.logger.info(
                            f"  DCCM: {dccm_energy_eV:.1f} eV "
                            f"(offset {offset:+.1f})"
                        )

                        # Move DCCM (crystal only, no vernier)
                        if simulate:
                            self.sim.fast_motor1.mv(dccm_energy_keV)
                        else:
                            self.dccm.energy.move(dccm_energy_keV, wait=True)

                        # Check beam
                        if flux_threshold:
                            self.check_beam_status(flux_threshold)

                        # Track FEE spectrometer camera
                        if track_feespec_cam:
                            self.xrtspec.track_feespec_camera(
                                dccm_energy_keV, crystal_angle_offset)

                        # Collect
                        self._wait(dwell_times[k_idx])

                        # Record summary
                        summary.append({
                            'k_target_eV': k_target_eV,
                            'dccm_energy_eV': dccm_energy_eV,
                            'dccm_offset_eV': offset,
                            'k_move_mode': k_move_mode,
                            'run_index': run_idx,
                            'point_index': point_index,
                        })
                        point_index += 1

                # End of run — stop DAQ
                if not simulate:
                    from mfx.db import daq
                    daq.control.setState("configured")
                    while daq.control.getState() != "configured":
                        sleep(0.01)
                    daq.control.setRecord(False)

                if runs > 1 and run_idx < runs - 1:
                    self.logger.info("Inter-run delay (5s)")
                    sleep(5)

        except KeyboardInterrupt:
            self.logger.warning("Scan aborted by user (Ctrl+C)")
            if not simulate:
                from mfx.db import daq, mfx_pulsepicker
                try:
                    daq.control.setState("configured")
                    daq.control.setRecord(False)
                    mfx_pulsepicker.close()
                except Exception:
                    pass

        # === Return to initial positions ===
        self.logger.info("Returning to initial positions")
        if simulate:
            self.sim.fast_motor1.mv(energy_start)
            self.sim.slow_motor1.mv(k_energy_start)
        else:
            self.dccm.energy.move(energy_start, wait=True)
            if round(k_energy_start, 1) != round(self.acr_energy_k.get().setpoint, 1):
                self.acr_energy_k.move(k_energy_start)
            if track_feespec:
                self.xrtspec.move_feespec_energy(
                    energy_start, crystal_angle_offset=crystal_angle_offset)

        # === Print summary ===
        print("\n" + "=" * 60)
        print("SCAN COMPLETE")
        print("=" * 60)
        print(f"  Total points collected: {len(summary)}")
        print(f"  K positions visited:    {len(k_positions_eV) * min(runs, run_idx + 1)}")
        print(f"  K move mode:            {k_move_mode}")
        if summary:
            print(f"  Energy range covered:   "
                  f"{min(s['dccm_energy_eV'] for s in summary):.1f} - "
                  f"{max(s['dccm_energy_eV'] for s in summary):.1f} eV")
        print("=" * 60 + "\n")

        return summary

    def _k_xas_move_pause(self, k_target_eV, k_target_keV,
                          track_feespec, crystal_angle_offset):
        """
        Move K in 'pause' mode: pause DAQ, move K, wait, resume.

        Parameters
        ----------
        k_target_eV : float
            Target K energy in eV
        k_target_keV : float
            Target K energy in keV
        track_feespec : bool
            Track FEE spectrometer
        crystal_angle_offset : float
            FEE crystal angle offset in degrees

        Notes
        -----
        Sequence: pause DAQ → move FEE spec (optional) → move K
        (blocking) → verify FEE → resume DAQ. Data collection stops
        during K transit. Typical K move takes 2-5 s depending on
        step size.
        """
        if self.simulate:
            self.sim.slow_motor1.mv(k_target_eV)
            self.k_energy = k_target_eV
            return

        from mfx.db import daq

        # Pause DAQ
        if daq.control.getState() == "running":
            daq.control.setState("paused")
            while daq.control.getState() != "paused":
                sleep(0.01)
            sleep(0.5)

        # Move FEE spec before K
        if track_feespec:
            self.xrtspec.move_feespec_energy(
                k_target_keV, crystal_angle_offset=crystal_angle_offset)

        # Move K (blocking)
        self.acr_energy_k.move(k_target_eV)
        self.k_energy = k_target_eV

        # Verify FEE spec
        if track_feespec:
            self.xrtspec.check_feespec_crystal_angle(
                k_target_keV, crystal_angle_offset=crystal_angle_offset)

        # Resume DAQ
        if daq.control.getState() == "paused":
            daq.control.setState("running")
            while daq.control.getState() != "running":
                sleep(0.01)

    def _k_xas_move_concurrent(self, k_target_eV, k_target_keV,
                               track_feespec, crystal_angle_offset):
        """
        Move K in 'concurrent' mode: request K non-blocking, don't wait.

        Parameters
        ----------
        k_target_eV : float
            Target K energy in eV
        k_target_keV : float
            Target K energy in keV
        track_feespec : bool
            Track FEE spectrometer
        crystal_angle_offset : float
            FEE crystal angle offset in degrees

        Notes
        -----
        Issues acr_energy_k.move(wait=False) so data collection can
        continue while the undulator settles. Early DCCM points in the
        subsequent offset loop will be collected during K transit — useful
        for evaluating whether in-transit data is scientifically usable.
        """
        if self.simulate:
            self.sim.slow_motor1.mv(k_target_eV)
            self.k_energy = k_target_eV
            return

        # Move FEE spec (fast, do before K)
        if track_feespec:
            self.xrtspec.move_feespec_energy(
                k_target_keV, crystal_angle_offset=crystal_angle_offset)

        # Request K move — non-blocking (don't wait for completion)
        self.acr_energy_k.move(k_target_eV, wait=False)
        self.k_energy = k_target_eV


class EXAFSEnergyRangeBuilder:
    """
    Build energy ranges and acquisition times for EXAFS scans.

    Generates energy points with appropriate spacing for:
    - Pre-edge region (uniform spacing)
    - Edge region (fine spacing)
    - EXAFS region (K-space spacing with weighted acquisition times)

    Attributes
    ----------
    element : str
        Element symbol (default: 'Fe')
    power : int
        Power for K-weighting acquisition times (default: 3)
    foil_energies : dict
        Fluorescence foil energies for elements (eV)
    threshold_energies : dict
        Absorption edge energies for elements (eV)
    """

    def __init__(self):
        """
        Initialize energy range builder.

        Sets default element to Fe with K³ weighting.
        Loads standard foil and threshold energy tables.
        """
        self.logger = logging.getLogger(__name__)
        self.element = 'Fe'
        self.power = 3
        self.foil_energies = {
            'Sc': 4492.8, 'Ti': 4966.4, 'V': 5465.1, 'Cr': 5989.2, 'Mn': 6539.0,
            'Fe': 7111.2, 'Co': 7708.9, 'Ni': 8332.8, 'Cu': 8978.9, 'Zn': 9658.6
        }
        self.threshold_energies = {
            'Ti': 4985.00, 'Sc': 4510.00, 'V': 5485.00, 'Cr': 6010.00,
            'Mn': 6560.00, 'Fe': 7130.00, 'Co': 7730.00, 'Ni': 8350.00,
            'Cu': 9000.00, 'Zn': 9680.00
        }

    def K_to_eV(self, K_value):
        """
        Convert K (Å⁻¹) to energy (eV).

        Parameters
        ----------
        K_value : float
            Wavenumber in Å⁻¹

        Returns
        -------
        float
            Energy in eV

        Notes
        -----
        Uses formula: E = K²/0.2625 + E₀
        where E₀ is threshold energy for current element.
        """
        threshold = self.threshold_energies[self.element]
        return K_value ** 2 / 0.2625 + threshold

    def eV_to_K(self, energy_eV):
        """
        Convert energy (eV) to K (Å⁻¹).

        Parameters
        ----------
        energy_eV : float
            Energy in eV

        Returns
        -------
        float
            Wavenumber in Å⁻¹

        Notes
        -----
        Uses formula: K = √(0.2625*(E - E₀))
        where E₀ is threshold energy for current element.
        """
        threshold = self.threshold_energies[self.element]
        return (0.2625 * (energy_eV - threshold)) ** 0.5

    def build_energy_range(
            self, min_before_pre_edge=7055.0, max_before_pre_edge=7110.2,
            preedge_end=7116.2, preedge_eV_increment=0.5,
            min_K_value=2.0, max_K_value=12.0,
            before_edge_eV_increment=5.0, edge_eV_increment=1.0,
            K_spacing=0.1, time_before_edge=2, time_in_edge=1,
            time_in_preedge=2, min_time_EXAFS=0.5, max_time_EXAFS=10,
            debug=False):
        """
        Build complete energy range and acquisition times.

        Generates energy points in four regions:
        1. Pre-pre-edge: Coarse spacing before pre-edge
        2. Pre-edge: Fine spacing approaching edge
        3. Edge: Fine spacing across edge
        4. EXAFS: K-space spacing with weighted times

        Parameters
        ----------
        min_before_pre_edge : float, optional
            Start of pre-pre-edge in eV (default: 7055.0)
        max_before_pre_edge : float, optional
            End of pre-pre-edge in eV (default: 7110.2)
        preedge_end : float, optional
            End of pre-edge in eV (default: 7116.2)
        preedge_eV_increment : float, optional
            Pre-edge spacing in eV (default: 0.5)
        min_K_value : float, optional
            Minimum K in Å⁻¹ (default: 2.0)
        max_K_value : float, optional
            Maximum K in Å⁻¹ (default: 12.0)
        before_edge_eV_increment : float, optional
            Pre-pre-edge spacing in eV (default: 5.0)
        edge_eV_increment : float, optional
            Edge spacing in eV (default: 1.0)
        K_spacing : float, optional
            EXAFS K spacing in Å⁻¹ (default: 0.1)
        time_before_edge : float, optional
            Acquisition time in pre-pre-edge (s) (default: 2)
        time_in_edge : float, optional
            Acquisition time in edge (s) (default: 1)
        time_in_preedge : float, optional
            Acquisition time in pre-edge (s) (default: 2)
        min_time_EXAFS : float, optional
            Minimum EXAFS time (s) (default: 0.5)
        max_time_EXAFS : float, optional
            Maximum EXAFS time (s) (default: 10)
        debug : bool, optional
            Show diagnostic plot (default: False)

        Returns
        -------
        tuple
            (energy_range, time_range, energy_K_range, K_values)
            - energy_range: Complete energy array (eV)
            - time_range: Acquisition times (s)
            - energy_K_range: EXAFS region energies (eV)
            - K_values: EXAFS K values (Å⁻¹)

        Notes
        -----
        Energy ranges are concatenated in order:
        pre-pre-edge → pre-edge → edge → EXAFS

        Acquisition times use K³ weighting in EXAFS region
        to maintain S/N across full K range.

        Stores arrays as instance attributes for plotting.
        """
        start_ev = 0.0
        # Build energy regions
        if min_before_pre_edge >= preedge_end:
            self.logger.error(
                "min_before_pre_edge must be less than preedge_end. skipping pre-edge regions.")
            start_ev = min_before_pre_edge
            min_before_pre_edge = 7055.0

        energy_before_pre_edge = np.arange(
            min_before_pre_edge, max_before_pre_edge, before_edge_eV_increment
        )
        energy_in_preedge = np.arange(
            max_before_pre_edge + preedge_eV_increment, preedge_end, preedge_eV_increment
        )

        K_values = np.arange(min_K_value, max_K_value + K_spacing, K_spacing)
        energy_K_range = np.array([self.K_to_eV(K) for K in K_values])

        energy_in_edge = np.arange(
            preedge_end + edge_eV_increment, np.min(energy_K_range), edge_eV_increment
        )

        energy_range = np.concatenate((
            energy_before_pre_edge, energy_in_preedge, energy_in_edge, energy_K_range
        ))

        # Build time arrays
        time_before_edge_arr = np.ones(len(energy_before_pre_edge)) * time_before_edge
        time_in_preedge_arr = np.ones(len(energy_in_preedge)) * time_in_preedge
        time_in_edge_arr = np.ones(len(energy_in_edge)) * time_in_edge
        time_EXAFS = self.map_time_to_K_weighting(min_time_EXAFS, max_time_EXAFS, K_values)

        time_range = np.concatenate((
            time_before_edge_arr, time_in_preedge_arr, time_in_edge_arr, time_EXAFS
        ))

        # Round to 0.1 eV, remove duplicates, sort ascending
        energy_range = np.round(energy_range, 1)
        energy_range, unique_idx = np.unique(energy_range, return_index=True)
        time_range = time_range[unique_idx]

        # Store for plotting and trim if start_ev past preedge
        if start_ev >= preedge_end:
            self.logger.error(
                "min_before_pre_edge must be less than preedge_end. skipping pre-edge regions.")
            index = np.argmin(np.abs(energy_range - start_ev))
            energy_range = energy_range[index:]
            time_range = time_range[index:]
            k_index = np.argmin(np.abs(energy_K_range - start_ev))
            energy_K_range = energy_K_range[k_index:]
            K_values = K_values[k_index:]

        self.energy_range = energy_range
        self.time_range = time_range
        self.energy_K_range = energy_K_range
        self.K_values = K_values

        if debug:
            self.plot_scan_profile(energy_range, time_range, energy_K_range, K_values)

        return energy_range, time_range, energy_K_range, K_values

    def map_time_to_K_weighting(self, min_time, max_time, K_values):
        """
        Map acquisition times to K-weighting.

        Calculates acquisition times that vary as Kⁿ to maintain
        constant signal-to-noise ratio across EXAFS region.

        Parameters
        ----------
        min_time : float
            Minimum acquisition time (s)
        max_time : float
            Maximum acquisition time (s)
        K_values : array_like
            K values in Å⁻¹

        Returns
        -------
        ndarray
            Normalized acquisition times (s)

        Notes
        -----
        Uses power from self.power (default: 3 for K³).
        Normalizes weighted times to [min_time, max_time] range.
        """
        time_range = np.linspace(min_time, max_time, len(K_values))
        K_time = K_values ** self.power
        K_time_range = time_range * K_time

        min_weighted = K_time_range.min()
        max_weighted = K_time_range.max()

        normalized_time = min_time + (max_time - min_time) * \
                         (K_time_range - min_weighted) / (max_weighted - min_weighted)

        return normalized_time

    def plot_scan_profile(self, energy_range, time_range, energy_K_range, K_values):
        """
        Plot scan profile visualization.

        Creates 3x2 subplot figure showing:
        - Energy vs point index
        - Acquisition time vs point index
        - Cumulative time vs point index
        - Resolution vs K
        - Acquisition time vs energy
        - Cumulative time vs energy

        Parameters
        ----------
        energy_range : array_like
            Energy points (eV)
        time_range : array_like
            Acquisition times (s)
        energy_K_range : array_like
            EXAFS energies (eV)
        K_values : array_like
            K values (Å⁻¹)

        Notes
        -----
        Resolution estimated as Δr = π/(2*ΔK) where ΔK ≈ K - 2.
        All plots include grid for readability.
        Figure saved at 150 DPI.
        """
        fig, axs = plt.subplots(3, 2, dpi=150, figsize=(10, 12))

        # Energy vs point
        axs[0, 0].plot(energy_range, 'k')
        axs[0, 0].set_xlabel('Data Point')
        axs[0, 0].set_ylabel('Energy (eV)')
        axs[0, 0].grid(True, alpha=0.3)

        # Time per point
        axs[1, 0].plot(time_range, 'k')
        axs[1, 0].set_xlabel('Data Point')
        axs[1, 0].set_ylabel('Acq. Time (s)')
        axs[1, 0].grid(True, alpha=0.3)

        # Cumulative time
        axs[2, 0].plot(np.cumsum(time_range), 'k')
        axs[2, 0].set_xlabel('Data Point')
        axs[2, 0].set_ylabel('Total Time (s)')
        axs[2, 0].grid(True, alpha=0.3)

        # Resolution
        K_2_idx = np.argmin(np.abs(K_values - 2.0))
        resolution = np.pi * 0.5 / (K_values[K_2_idx:] - 1.99)
        axs[0, 1].plot(K_values[K_2_idx:], resolution, 'k')
        axs[0, 1].set_xlabel('K (Å⁻¹)')
        axs[0, 1].set_ylabel('Resolution (Å)')
        axs[0, 1].set_ylim(0.05, 0.5)
        axs[0, 1].grid(True, alpha=0.3)

        # Time vs energy
        axs[1, 1].plot(energy_range, time_range, 'k')
        axs[1, 1].set_xlabel('Energy (eV)')
        axs[1, 1].set_ylabel('Acq. Time (s)')
        axs[1, 1].grid(True, alpha=0.3)

        # Cumulative time vs energy
        axs[2, 1].plot(energy_range, np.cumsum(time_range), 'k')
        axs[2, 1].set_xlabel('Energy (eV)')
        axs[2, 1].set_ylabel('Total Time (s)')
        axs[2, 1].grid(True, alpha=0.3)

        plt.tight_layout()
        plt.show()

    def output_scan_profile(self, elist_name='elist', tlist_name='tlist'):
        """
        Save energy and time arrays to text files.

        Parameters
        ----------
        elist_name : str, optional
            Energy file basename (default: 'elist')
        tlist_name : str, optional
            Time file basename (default: 'tlist')

        Notes
        -----
        Saves to current directory with .txt extension.
        Energy saved in keV.
        Time saved in seconds.
        """
        np.savetxt(f'{tlist_name}.txt', self.time_range)
        np.savetxt(f'{elist_name}.txt', self.energy_range / 1000.0)
