import math
import logging
from pathlib import Path
import json

from pcdsdevices.device_types import IMS
from ophyd import (Device, EpicsSignalRO, Component as Cpt,
    FormattedComponent, EpicsSignal)
from ophyd.status import wait as status_wait

from tfs.lens import LensConnect, LensTripLimits
from tfs.lens import MFXLens as Lens
from tfs.offline_calculator import TFS_Calculator
from functools import wraps
from tfs.utils import estimate_beam_fwhm, focal_length, MFX_prefocus_energy_range

logger = logging.getLogger(__name__)


class TransfocatorInterlock(Device):
    """
    Device containing signals pertinent to the interlock system.
    """
    limits = Cpt(
        LensTripLimits, ":ACTIVE",
        doc="Active trip limit settings, based on pre-focus lens"
    )

    # Active limits, predicated on pre-focus lens insertion:
    # no_lens_limit = Cpt(LensTripLimits, ":NO_LENS")
    # lens1_limit = Cpt(LensTripLimits, ":LENS1")
    # lens2_limit = Cpt(LensTripLimits, ":LENS2")
    # lens3_limit = Cpt(LensTripLimits, ":LENS3")

    bypass = Cpt(
        EpicsSignal, ":BYPASS:STATUS", write_pv=":BYPASS:SET",
        doc="Bypass in use?",
    )
    bypass_energy = Cpt(
        EpicsSignal, ":BYPASS:ENERGY",
        doc="Bypass energy",
    )
    ioc_alive = Cpt(
        EpicsSignalRO, ":BEAM:ALIVE",  # string=True,
        doc="IOC alive [active]"
    )
    faulted = Cpt(
        EpicsSignalRO, ":BEAM:FAULTED",  # string=True,
        doc="Fault currently active [active]"
    )
    state_fault = Cpt(
        EpicsSignalRO, ":BEAM:UNKNOWN",  # string=True,
        doc="Lens position unknown [active]"
    )

    violated_fault = Cpt(
        EpicsSignalRO, ":BEAM:VIOLATED",  # string=True,
        doc="Summary fault due to energy/lens combination [active]"
    )
    min_fault = Cpt(
        EpicsSignalRO, ":BEAM:MIN_FAULT",  # string=True,
        doc="Minimum required energy not met for lens combination [active]"
    )
    lens_required_fault = Cpt(
        EpicsSignalRO, ":BEAM:REQ_TFS_FAULT",  # string=True,
        doc="Transfocator lens required for energy/lens combination [active]"
    )
    table_fault = Cpt(
        EpicsSignalRO, ":BEAM:TAB_FAULT",  # string=True,
        doc="Effective radius in table-based disallowed area [active]"
    )

    violated_fault_latch = Cpt(
        EpicsSignalRO, ":BEAM:VIOLATED_LT",  # string=True,
        doc="Summary fault due to energy/lens combination [latched]"
    )
    min_fault_latch = Cpt(
        EpicsSignalRO, ":BEAM:MIN_FAULT_LT",  # string=True,
        doc="Minimum required energy not met for lens combination [latched]"
    )
    lens_required_fault_latch = Cpt(
        EpicsSignalRO, ":BEAM:REQ_TFS_FAULT_LT",  # string=True,
        doc="Transfocator lens required for energy/lens combination [latched]"
    )
    table_fault_latch = Cpt(
        EpicsSignalRO, ":BEAM:TAB_FAULT_LT",  # string=True,
        doc="Effective radius in table-based disallowed area [latched]"
    )


class TransfocatorBase(Device):
    def __init__(self, prefix, *args, **kwargs):
        super().__init__(prefix, **kwargs)
        return


class MFXTransfocator(TransfocatorBase):
    """
    Class to represent the MFX Transfocator
    """
    interlock = Cpt(TransfocatorInterlock, '')

    # XRT Lenses
    prefocus_top = Cpt(Lens, ":DIA:03")
    prefocus_mid = Cpt(Lens, ":DIA:02")
    prefocus_bot = Cpt(Lens, ":DIA:01")
    xrt_radius = Cpt(EpicsSignalRO, ":BEAM:XRT_RADIUS", kind="normal",
                     doc="XRT effective radius")
    tfs_radius = Cpt(EpicsSignalRO, ":BEAM:TFS_RADIUS", kind="normal",
                     doc="TFS effective radius")

    # TFS Lenses
    tfs_02 = Cpt(Lens, ":TFS:02")
    tfs_03 = Cpt(Lens, ":TFS:03")
    tfs_04 = Cpt(Lens, ":TFS:04")
    tfs_05 = Cpt(Lens, ":TFS:05")
    tfs_06 = Cpt(Lens, ":TFS:06")
    tfs_07 = Cpt(Lens, ":TFS:07")
    tfs_08 = Cpt(Lens, ":TFS:08")
    tfs_09 = Cpt(Lens, ":TFS:09")
    tfs_10 = Cpt(Lens, ":TFS:10")

    # Requested energy
    req_energy = Cpt(EpicsSignal, ":BEAM:REQ_ENERGY")

    # Actual beam energy
    beam_energy = Cpt(EpicsSignal, ":BEAM:ENERGY")

    # Translation
    translation = FormattedComponent(IMS, "MFX:TFS:MMS:21")

    def __init__(self, prefix, *, nominal_sample=400.37, **kwargs):
        self.nominal_sample = nominal_sample
        super().__init__(prefix, **kwargs)

    @property
    def lenses(self):
        """
        Component lenses
        """
        return [getattr(self, dev) for dev in self._sub_devices
                if isinstance(getattr(self, dev), Lens)]

    @property
    def xrt_lenses(self):
        """
        Lenses in the XRT
        """
        return [lens for lens in self.lenses if 'DIA' in lens.prefix]

    @property
    def tfs_lenses(self):
        """
        Transfocator lenses
        """
        return [lens for lens in self.lenses if 'TFS' in lens.prefix]

    @property
    def current_focus(self):
        """
        The distance from the focus of the Transfocator to nominal_sample

        Note
        ----
        If no lenses are inserted this will retun NaN
        """
        # Find inserted lenses
        inserted = [lens for lens in self.lenses if lens.inserted]
        # Check that we have any inserted lenses at all
        if not inserted:
            logger.warning("No lenses are currently inserted")
            return math.nan
        # Calculate the image from this set of lenses
        return LensConnect(*inserted).image(0.0) - self.nominal_sample


    def remove_all(self):
        """
        Removes all tfs lenses.
        """
        self.tfs_02.remove()
        self.tfs_03.remove()
        self.tfs_04.remove()
        self.tfs_05.remove()
        self.tfs_06.remove()
        self.tfs_07.remove()
        self.tfs_08.remove()
        self.tfs_09.remove()
        self.tfs_10.remove()


    def find_best_combo(self, target=None, energy_eV=None, n=4, z_obj=0, show=True, exclusions=[], **kwargs):

        """
        Calculate the best lens array to hit the nominal sample point

        Parameters
        ----------
        target : float, optional
            The target image of the lens array. By default this is
            `nominal_sample i.e. 400.37`

        energy_eV : int, optional
            Select the energy in eV.
            Default uses the beam energy given by acr which is usually wrong

        n : int, optional
            The maximum number of lenses in a valid combination. This saves
            time by avoiding calculating the focal plane of combinations with a
            large number of lenses, default n=4

        z_obj : float, optional
            The source point of the beam, default halfway through range at 150.0

        show : bool, optional
            Print a table of the of the calculated lens combination

        kwargs:
            Passed to :meth:`.Calculator.find_solution`
        """
        if 'energy' in kwargs:
            raise ValueError('energy is no longer the correct input variable. Please use energy_eV. Thank Fred.')

        energy = energy_eV or self.beam_energy.get()
        try:
            assert energy > 1000
        except AssertionError:
            logging.warning(f"please double-check that {energy} is in eV, not keV.")
        target = target or self.nominal_sample
        calc = TFS_Calculator(tfs_lenses=self.tfs_lenses, prefocus_lenses=self.xrt_lenses,exclusions=exclusions)
        combo, diff = calc.find_solution(target, energy, n, z_obj, **kwargs)
        if combo:
            combo.show_info()
            logger.info(f'Difference to desired focus position: {round(diff*1000, 2)} mm')
            radius = combo.tfs_radius
            logger.info(f'Given Energy: {energy} eV')
            logger.info(f'Given Sample Position: {target} mm')
            logger.info(f'Calculated Radius: {round(radius, 2)} um')
            estimate_beam_fwhm(radius=radius, energy=energy)
            focal = focal_length(radius=radius, energy=energy)

            logger.info(f'Calculated Focal Length: {focal} m\n')

        else:
            logger.error("Unable to find a valid solution for target")
        return combo


    def try_combo(self, target=None, energy=None, show=True, prefocus = None, tfs = [], **kwargs):
        """
        Calculates the focus based on the lens combo you select

        Parameters
        ----------
        target : float, optional
            The target image of the lens array. By default this is
            `nominal_sample i.e. 399.88`

        energy : int, optional 
            Select the energy in eV.
            Default uses the beam energy given by acr which is usually wrong

        show : bool, optional
            Print a table of the of the calculated lens combination

        prefocus : int, optional
            Select either 333, 428, or 750 um radius lens

        tfs : list, optional
            Select your lens combination from tfs lenes #2-10 as list i.e. [2,6,8,10]

        kwargs:
            Passed to :meth:`.Calculator.find_solution`
        """
        energy = energy or self.beam_energy.get()
        target = target or self.nominal_sample

        for e_range, lens in MFX_prefocus_energy_range.items():
            if energy >= e_range[0] and energy < e_range[1]:
                prefocus_rec = lens[1]

        if prefocus_rec != prefocus:
            logging.error(
                f'{prefocus_rec} um prefocusing lens is reccommended for {energy} eV '
                f'You are not using the recommended prefocusing lens.')

        if prefocus == int(750):
            prefocus_idx = 2
        elif prefocus == 428:
            prefocus_idx = 1
        elif prefocus == 333:
            prefocus_idx = 0
        elif prefocus is None:
            prefocus_idx = None
        else:
            logging.error(
                'No proper prefocusing lens selected. '
                'Select either 333, 428, or 750 um radius lens (as int)')

        if prefocus_idx is None:
            tfs_combo = []
        else:
            tfs_combo = [self.xrt_lenses[prefocus_idx]]

        for lens in tfs:
            tfs_combo.append(self.tfs_lenses[int(lens) - 2])

        combo = LensConnect(*tfs_combo)

        if combo:
            combo.show_info()
            radius = combo.tfs_radius
            logger.info(f'Given Energy: {energy} eV')
            logger.info(f'Given Sample Position: {target} mm')
            logger.info(f'Calculated Radius: {round(radius, 2)} um')
            estimate_beam_fwhm(radius=radius, energy=energy)
            focal = focal_length(radius=radius, energy=energy)

            logger.info(f'Calculated Focal Length: {focal} um\n')

        else:
            logger.error("Unable to find a valid solution for target")
        return combo


    def set(self, value, **kwargs):
        """
        Set the Transfocator focus

        Parameters
        """
        return self.focus_at(value=value, **kwargs)

    def focus_at(self, value=None, wait=False, timeout=None, **kwargs):
        """
        Calculate a combination and insert the lenses

        Parameters
        ----------
        value: float, optional
            Chosen focal plane. Nominal sample by default

        wait : bool, optional
            Wait for the motion of the transfocator to complete

        timeout: float, optional
            Timeout for motion

        kwargs:
            All passed to :meth:`.find_best_combo`

        Returns
        -------
        StateStatus
            Status that represents whether the move is complete
        """
        # Find the best combination of lenses to match the target image
        plane = value or self.nominal_sample
        best_combo = self.find_best_combo(target=plane, **kwargs)
        # Collect status to combine
        statuses = list()
        # Only tell one XRT lens to insert
        prefocused = False
        for lens in self.xrt_lenses:
            if lens in best_combo.lenses:
                statuses.append(lens.insert(timeout=timeout))
                prefocused = True
                break
        # If we have no XRT lenses one remove will do
        if not prefocused:
            statuses.append(self.xrt_lenses[0].remove(timeout=timeout))
        # Ensure all Transfocator lenses are correct
        for lens in self.tfs_lenses:
            if lens in best_combo.lenses:
                statuses.append(lens.insert(timeout=timeout))
            else:
                statuses.append(lens.remove(timeout=timeout))
        # Conglomerate all status objects
        status = statuses.pop(0)
        for st in statuses:
            status = status & st
        # Wait if necessary
        if wait:
            status_wait(status, timeout=timeout)
        return status


    def plan_energy_schedule(self, low_eV, high_eV, step_eV=10.0, *, target=None,
                             n=4, z_obj=0.0, show=False):
        """
        Plan a schedule of lens insert/remove actions and stage offsets
        over an energy interval without moving hardware.

        Parameters
        ----------
        low_eV : float
            Starting energy in eV.
        high_eV : float
            Ending energy in eV.
        step_eV : float, optional
            Energy increment in eV (default 10 eV).
        target : float, optional
            Desired focal plane (defaults to nominal sample).
        n : int, optional
            Max number of TFS lenses in combo (passed to solver).
        z_obj : float, optional
            Source point in solver.
        show : bool, optional
            If True, print combo info for each energy.

        Returns
        -------
        list of dict
            For each energy step, returns an entry with keys:
              - 'energy_eV': energy value in eV
              - 'lenses': list of lens prefixes in the planned combo
              - 'actions': {'insert': [...], 'remove': [...]} compared to previous step
              - 'image_target_delta': signed difference (image - target)
              - 'stage_offset_mm': signed offset in mm to place focus at target
        """
        if step_eV is None or step_eV == 0:
            raise ValueError("step_eV must be non-zero")

        tgt = target or self.nominal_sample
        # Energy sequence inclusive of high_eV
        num_steps = int((high_eV - low_eV) // step_eV)
        energies = [low_eV + i * step_eV for i in range(num_steps + 1)]
        if energies[-1] < high_eV:
            energies.append(high_eV)

        calc = TFS_Calculator(tfs_lenses=self.tfs_lenses, prefocus_lenses=self.xrt_lenses)
        schedule = []
        prev_lenses = set()

        for energy in energies:
            combo, _diff_abs = calc.find_solution(tgt, energy, n=n, z_obj=z_obj)
            if combo is None:
                schedule.append({
                    'energy_eV': energy,
                    'lenses': [],
                    'actions': {'insert': [], 'remove': []},
                    'image_target_delta': None,
                    'stage_offset_mm': None,
                })
                continue

            if show:
                combo.show_info()

            # Determine planned lenses as prefixes for readability
            lens_list = [lens.prefix for lens in combo.lenses]
            lens_set = set(lens_list)

            # Signed difference between image and target
            image_pos = combo.image(z_obj, energy)
            delta = image_pos - tgt
            stage_offset_mm = delta * 1000.0 # convert from meters to mm

            # Actions relative to previous step
            to_insert = sorted(list(lens_set - prev_lenses))
            to_remove = sorted(list(prev_lenses - lens_set))

            schedule.append({
                'energy_eV': energy,
                'lenses': lens_list,
                'actions': {'insert': to_insert, 'remove': to_remove},
                'image_target_delta': delta,
                'stage_offset_mm': stage_offset_mm,
            })

            prev_lenses = lens_set

        return schedule

    def get_stage_limits(self, margin_mm):
        stage = self.translation
        z_high_mm = stage.high_limit
        z_low_mm = stage.low_limit
        z_max_mm = z_high_mm - margin_mm
        z_min_mm = z_low_mm + margin_mm
        print(f"Stage limits: low={z_low_mm:.3f} mm, high={z_high_mm:.3f} mm, margin={margin_mm:.3f} mm")
        return z_min_mm, z_max_mm

    def mv_stage_to_pos(self, z_mm):
        stage = self.translation
        print(f"Moving stage to position: z={z_mm:.3f}mm")
        stage.mv(z_mm)
        print(f"Stage moved to position: z={z_mm:.3f}mm")
        return z_mm

    def set_reference_combo(self, energy_eV, show=False):
        combo = self.find_best_combo(energy_eV=energy_eV, show=show)
        ref_focal_length_um = focal_length(combo.tfs_radius, energy=energy_eV)
        print(f"Reference energy: {energy_eV:.2f} eV, reference focal length: {ref_focal_length_um:.3f} um")
        return combo, ref_focal_length_um

    def get_z_stage_target(self, energy_eV, combo, ref_focal_length_um, ref_z_stage_mm):
        focal_length_um = focal_length(combo.tfs_radius, energy=energy_eV)
        z_stage_target_mm = ref_z_stage_mm - (focal_length_um - ref_focal_length_um) * 1000
        print(f"Energy {energy_eV:.2f} eV: computed focal length = {focal_length_um:.3f} um, target z = {z_stage_target_mm:.3f} mm.")
        return z_stage_target_mm

    def mv_stage_to_target_pos(self, energy_eV, combo, target_z_mm, track_record):
        stage = self.translation
        print(f"Moving stage to {target_z_mm:.3f} mm.")
        stage.mv(target_z_mm)
        track_record.append({
            "energy": energy_eV,
            "inserted_lenses": [lens.prefix for lens in combo.lenses],
            "z_position": target_z_mm
        })

    def track_focus(self, energies, *, margin_mm=10.0, show=False):
        """
        Keep the focal length fixed over a provided list of energies by
        compensating with the translation stage. Lenses are NOT actuated.

        Workflow:
        - Move stage to high limit minus a small margin.
        - Compute initial lens combo and reference focal length.
        - For each next energy, compute focal length for the current combo and
          move the stage to compensate.
        - If the move would exceed the stage low limit, return to the top
          position and recompute the lens combo at that energy, then continue.
        """
        if not energies:
            print("No energies provided.")
            return None

        min_z_stage_mm, max_z_stage_mm = self.get_stage_limits(margin_mm)
        ref_z_stage_mm = self.mv_stage_to_pos(max_z_stage_mm)
        combo, ref_focal_length_um = self.set_reference_combo(energies[0], show=show)
        track_record = []

        for energy in energies:
            target_z_stage_mm = self.get_z_stage_target(energy, combo, ref_focal_length_um, ref_z_stage_mm)
            if target_z_stage_mm > min_z_stage_mm and target_z_stage_mm < max_z_stage_mm:
                self.mv_stage_to_target_pos(energy, combo, target_z_stage_mm, track_record)
            else:
                shrinking_max_z_stage_mm = max_z_stage_mm
                while shrinking_max_z_stage_mm > min_z_stage_mm:
                    self.mv_stage_to_pos(shrinking_max_z_stage_mm)
                    combo = self.find_best_combo(energy_eV=energy, show=show)
                    if combo:
                        new_target_z_stage_mm = self.get_z_stage_target(energy, combo, ref_focal_length_um, ref_z_stage_mm)
                        if new_target_z_stage_mm > min_z_stage_mm and new_target_z_stage_mm < max_z_stage_mm:
                            self.mv_stage_to_target_pos(energy, combo, new_target_z_stage_mm, track_record)
                            break
                    shrinking_max_z_stage_mm -= margin_mm
                if not combo:
                    print("Stage out of travel. Cannot compensate further...")

        print(f"Tracking complete. Final energy: {track_record[-1]['energy']:.2f} eV, stage position: {track_record[-1]['z_position']:.3f} mm.")
        print(f"Lenses currently inserted: {track_record[-1]['inserted_lenses']}")
        
        save_path = Path.home() / "track_focus_results.json"
        with open(save_path, "w") as f:
            json.dump(track_record, f, indent=4)
        print(f"Tracking results saved to {save_path}")
        return track_record


class Transfocator(MFXTransfocator):
    pass


class TransfocatorEnergyInterrupt(Exception):
    """
    Custom exception returned when input beam energy (user defined
    or current measured value) changes significantly during
    calculation
    """
    pass


def constant_energy(func):
    """
    Ensures that requested energy does not change during calculation

    Parameters:
    transfocator_obj: transfocate.transfocator.Transfocator object

    energy_type: string
        input string specifying 'req_energy' or 'beam_energy'
        to be monitored during calculation

    tolerance: float
        energy (in eV) for which current beam energy can change during
        calculation and still assumed constant
    """
    @wraps(func)
    def with_constant_energy(transfocator_obj, energy_type, tolerance, *args, **kwargs):
        try:
            energy_signal = getattr(transfocator_obj, energy_type)
        except Exception as e:
            raise AttributeError("input 'energy_type' not defined") from e
        energy_before = energy_signal.get()
        result = func(transfocator_obj, *args, **kwargs)
        energy_after = energy_signal.get()
        if not math.isclose(energy_before, energy_after, abs_tol=tolerance):
            raise TransfocatorEnergyInterrupt("The beam energy changed significantly during the calculation")
        return result
    return with_constant_energy
