import math
import logging
from pathlib import Path
import json
from matplotlib import pyplot as plt

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

    # Nominal IP in the lens model's coordinates. 400.37 was calibrated
    # while find_solution() ignored the prefocus lens when computing the
    # image (before Nov 2025), which placed the image ~0.25 m too far
    # downstream at 7-10 keV. Re-derived from 2025-2026 production
    # configurations (no-prefocus at 7.0-7.2 keV and 750 um prefocus at
    # 8.5-9.8 keV, >= 5-10 h at fixed stage): 400.13 +/- 0.06 m.
    def __init__(self, prefix, *, nominal_sample=400.13, **kwargs):
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
    def current_focus(self, energy_eV=None):
        """
        The distance from the focus of the Transfocator to nominal_sample

        Note
        ----
        If no lenses are inserted this will retun NaN
        """
        energy = energy_eV or self.beam_energy.get()
        logger.warning(f"TFS {energy=} eV")
        # Find inserted lenses
        inserted = [lens for lens in self.lenses if lens.inserted]
        # Check that we have any inserted lenses at all
        if not inserted:
            logger.warning("No lenses are currently inserted")
            return math.nan
        # Calculate the image from this set of lenses
        return LensConnect(*inserted).image(0.0, energy) - self.nominal_sample

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

    def find_best_combo(
            self,
            target=None,
            energy_eV=None,
            n=4,
            z_obj=0,
            show=True,
            exclusions=[],
            avoid_forbidden=False,
            enable_prefocus=True,
            **kwargs):
        """
        Calculate the best lens array to hit the nominal sample point

        Parameters
        ----------
        target : float, optional
            The target image of the lens array. By default this is
            `nominal_sample i.e. 400.13`

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

        exclusions : list, optional
            Select your lenses to excluclde from tfs lenes #2-10 as list recommend [8,10]

        avoid_forbidden : bool, optional
            Avoids forbidden TFS configurations. True by default

        enable_prefocus : bool, optional
            Allows the solver to use the prefocusing lenses in the XRT. Default is True since
            the prefocusing lenses are usually required to hit the target plane at MFX.
            Setting this to False will force the solver to find a solution using only
            the TFS lenses.

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
        exclusions = [x - 1 for x in exclusions]
        calc = TFS_Calculator(tfs_lenses=self.tfs_lenses, prefocus_lenses=self.xrt_lenses, exclusions=exclusions)
        combo, diff = calc.find_solution(target, energy, n, z_obj, avoid_forbidden=avoid_forbidden,enable_prefocus=enable_prefocus, **kwargs)
        if combo:
            print(combo)
            combo.show_info()
            logger.info(f'Difference to desired focus position: {round(diff*1000, 2)} mm')
            radius = combo.tfs_radius
            logger.info(f'Given Energy: {energy} eV')
            logger.info(f'Given Sample Position: {target} mm')
            logger.info(f'Calculated Radius: {round(radius, 2)} um')
            estimate_beam_fwhm(radius=radius, energy=energy)
            focal = focal_length(radius=radius, energy=energy)
            if avoid_forbidden:
                logger.info("TFS combo is by default allowed")
            else:
                logger.error("TFS combo may be forbidden. Please check")

            logger.info(f'Calculated Focal Length: {focal} m\n')

        else:
            logger.error("Unable to find a valid solution for target")
        return combo


    def try_combo(
            self,
            target=None,
            energy=None,
            show=True,
            prefocus = None,
            tfs = [],
            **kwargs):
        """
        Calculates the focus based on the lens combo you select

        Parameters
        ----------
        target : float, optional
            The target image of the lens array. By default this is
            `nominal_sample i.e. 400.13`

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

        if prefocus == 750:
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
            calc = TFS_Calculator(tfs_lenses=self.tfs_lenses, prefocus_lenses=self.xrt_lenses)
            if prefocus_idx is not None:
                forbidden = calc.check_forbidden(prefocus_idx, energy, radius)
                log_level = logger.error if forbidden else logger.info
                log_level(f"TFS Configuration is {'Forbidden' if forbidden else 'Allowed'}")

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
            combo, _diff_abs, pre_focus_lens = calc.find_solution(tgt, energy, n=n, z_obj=z_obj)
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

    def plot_focus_track(self, json_file_path):
        # Load the data from the JSON file
        with open(json_file_path, 'r') as f:
            data = json.load(f)

        # Extract energy, z_position, and inserted_lenses values
        energies = [entry['energy'] for entry in data]
        z_positions = [entry['z_position'] for entry in data]
        inserted_lenses = [entry['inserted_lenses'] for entry in data]

        # Create the plot
        plt.figure(figsize=(12, 8))
        plt.plot(energies, z_positions, marker='o', linestyle='-', color='b')

        # Add labels and title
        plt.title('Z Position vs Energy')
        plt.xlabel('Energy (eV)')
        plt.ylabel('Z Position (units)')

        # Variable to keep track of the last inserted lenses shown
        last_displayed_lenses = None

        # Annotate only the first occurrence of each unique set of inserted_lenses
        for energy, z_position, lenses in zip(energies, z_positions, inserted_lenses):
            # Convert list of lenses to a tuple for easier comparison
            lenses_tuple = tuple(lenses)

            if lenses_tuple != last_displayed_lenses:
                plt.annotate(', '.join(lenses),
                            (energy, z_position),
                            textcoords="offset points",
                            xytext=(0, 10),
                            ha='center',
                            fontsize=8,
                            color='red',
                            arrowprops=dict(arrowstyle='->', color='red', lw=0.5))
                last_displayed_lenses = lenses_tuple  # Update the last_displayed_lenses
        plt.grid(True)
        plt.show()

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

    def lens_minder(
        self,
        lenses=(10,),
        *,
        poll_s=1.0,
        tolerance_mm=0.5,
        close_beam=True,
        att=None,
        pulsepicker=None,
        move_timeout=30.0,
        att_timeout=30.0,
    ):
        """
        Keep the TFS lens y motors on their setpoints until stopped.

        The y (vertical) motors of the TFS lens stacks drift slowly over time.
        This method polls the selected y motors in a loop and moves any that
        have drifted back to their setpoint, protecting the beam around each
        move. It blocks until interrupted with Ctrl+C.

        On every poll, each selected motor that is not moving
        (``.DMOV == 1``) is checked. If ``|.RBV - .VAL| > tolerance_mm`` the
        motor is corrected:

        1. The attenuator transmission and the pulse picker state are read
           immediately before the move, not when the minder was started,
           so changes made while it is running are respected.
        2. If ``close_beam`` is True, the beam is closed with
           ``pulsepicker.close()`` and ``att(0)``. This protects the sample
           and detectors even if the lens interlock is defeated. With
           ``close_beam=False`` the lens interlock is relied on to close the
           beam when the lens moves. If neither the pulse picker nor the
           attenuator can be confirmed closed, the lens is not moved.
        3. The motor setpoint (``.VAL``) is re-written and the method waits
           for ``.DMOV`` (up to ``move_timeout``). An error is logged if the
           readback is still outside ``tolerance_mm`` afterwards.
        4. The attenuator transmission and the pulse picker state read in
           step 1 are restored. This is done in a ``finally`` block, so the
           beam state is restored even if the loop is interrupted (Ctrl+C)
           during a correction.

        Attenuator moves are made robust against floating point noise:
        transmissions at or below 1e-9 (e.g. the 3.97e-76 read back after
        ``att(0)``) are treated as 0, others are rounded to 4 significant
        figures, and no move is sent if the attenuator is already at the
        target (the attenuator IOC does not report done for such a move,
        which otherwise leaves the device stuck "moving"). Before each
        attenuator move the method waits up to ``att_timeout`` for any
        previous move to finish, and clears a stale "moving" state if the
        IOC already reports done. A failed correction is logged and the
        loop continues.

        The pulse picker state is restored with the matching command,
        based on ``pulsepicker.mode`` (``:SD_SIMPLE``):

        =====================  ========================
        mode                   restored with
        =====================  ========================
        2 / ``'FLIP-FLOP'``    ``pulsepicker.flipflop()``
        3 / ``'BURST'``        ``pulsepicker.burst()``
        6 / ``'FOLLOWER'``     ``pulsepicker.follower()``
        0 / ``'IDLE'``         ``open()`` or ``close()``, from the blade state
        =====================  ========================

        Motors that are moving (``.DMOV == 0``) are skipped, so the minder
        does not interfere with moves made by the user or other code.

        Parameters
        ----------
        lenses : int or iterable of int, optional
            TFS lens numbers (2-10) whose y motor is watched. The motor PVs
            come from ``tfs.lens.LENS_MOTOR_PVS`` (e.g. lens 2 is
            ``MFX:TFS:MMS:04``, lens 10 is ``MFX:TFS:MMS:20``).
            Default ``(10,)``.
        poll_s : float, optional
            Time between polls in seconds. Default 1.0.
        tolerance_mm : float, optional
            Allowed absolute difference between readback and setpoint in mm
            before a correction is made. Default 0.5.
        close_beam : bool, optional
            If True, close the pulse picker and set the attenuator to 0
            before each correction. Default True.
        att : Attenuator, optional
            Attenuator used to read, close and restore the transmission.
            Default ``mfx.db.mfx_attenuator``.
        pulsepicker : PulsePicker, optional
            Pulse picker used to read, close and restore the beam state.
            Default ``mfx.db.mfx_pulsepicker``.
        move_timeout : float, optional
            Maximum time in seconds to wait for each correction move to
            finish. Default 30.0.
        att_timeout : float, optional
            Maximum time in seconds to wait for each attenuator move, and for
            a previous attenuator move to finish. Default 30.0.

        Returns
        -------
        int
            Number of corrections made before the loop was stopped.

        Raises
        ------
        ValueError
            If a lens number is not in 2-10.

        Notes
        -----
        Each correction briefly interrupts the beam. Choose ``tolerance_mm``
        so that corrections are only made when the drift matters.

        Examples
        --------
        Watch lens 10 every second with a +-0.5 mm window:

        >>> tfs.lens_minder()

        Watch lenses 8 and 10 every 2 s with a +-0.2 mm window:

        >>> tfs.lens_minder([8, 10], poll_s=2, tolerance_mm=0.2)

        Rely on the lens interlock to close the beam:

        >>> tfs.lens_minder([4, 5, 8], close_beam=False)
        """
        import time as _time
        from tfs.lens import LENS_MOTOR_PVS

        lenses = [int(n) for n in (lenses if hasattr(lenses, "__iter__") else [lenses])]
        bad = [n for n in lenses if n not in LENS_MOTOR_PVS]
        if bad:
            raise ValueError(f"Unknown TFS lens number(s) {bad}; valid are 2-10")

        if att is None or pulsepicker is None:
            from mfx.db import mfx_attenuator, mfx_pulsepicker

            att = att if att is not None else mfx_attenuator
            pulsepicker = pulsepicker if pulsepicker is not None else mfx_pulsepicker

        motors = {}
        for n in lenses:
            pv = LENS_MOTOR_PVS[n]["y"]
            motors[n] = dict(
                pv=pv,
                rbv=EpicsSignalRO(f"{pv}.RBV", name=f"tfs_{n:02d}_y_rbv"),
                val=EpicsSignal(f"{pv}.VAL", name=f"tfs_{n:02d}_y_val"),
                dmov=EpicsSignalRO(f"{pv}.DMOV", name=f"tfs_{n:02d}_y_dmov"),
            )
        for m in motors.values():
            for sig in (m["rbv"], m["val"], m["dmov"]):
                sig.wait_for_connection(timeout=5.0)

        # pulsepicker.mode (:SD_SIMPLE) values, as used by pcdsdevices
        # PulsePicker.flipflop()/burst()/follower() when waiting for the mode.
        pp_modes = {2: "FLIP", "FLIP-FLOP": "FLIP", 3: "BURST", "BURST": "BURST",
                    6: "FOLLOW", "FOLLOWER": "FOLLOW"}

        def _pp_state():
            """Return a restorable pulse picker state."""
            for as_string in (True, False):
                try:
                    mode = pulsepicker.mode.get(as_string=as_string)
                except Exception:
                    continue
                key = mode.strip().upper() if isinstance(mode, str) else mode
                if key in pp_modes:
                    return pp_modes[key]
            # IDLE (0): no running mode, so restore the blade state
            try:
                return "OPEN" if pulsepicker.position == "OPEN" else "CLOSED"
            except Exception:
                return "CLOSED"

        def _pp_restore(state):
            actions = {
                "FLIP": pulsepicker.flipflop,
                "BURST": pulsepicker.burst,
                "FOLLOW": pulsepicker.follower,
                "OPEN": pulsepicker.open,
                "CLOSED": pulsepicker.close,
            }
            actions[state]()

        # Attenuator transmissions below this are treated as fully blocked
        # (att(0) reads back values like 3.97e-76, not exactly 0).
        att_zero = 1e-9

        def _att_target(value):
            """Snap a transmission to a value the attenuator can be asked for."""
            value = float(value)
            if value <= att_zero:
                return 0.0
            return float(f"{min(value, 1.0):.4g}")

        def _att_at(target):
            """True if the attenuator is already at ``target``."""
            current = float(att.position)
            if target == 0.0:
                return current <= att_zero
            return abs(current - target) <= 1e-3 * target

        def _att_wait_idle():
            """Wait for the attenuator to finish moving.

            The attenuator IOC does not report done for a move to a
            transmission it is already at, which can leave ophyd thinking a
            move is still in progress. If the IOC says it is done but ophyd
            still reports moving, clear the stale state the same way
            pcdsdevices' AttBase._setup_move does.
            """
            t0 = _time.monotonic()
            while att.moving and _time.monotonic() - t0 < att_timeout:
                if att.done.get() == att.done_value:
                    logger.warning(
                        "lens_minder: clearing stale attenuator 'moving' state "
                        f"(position={att.position:.3g}, goal={att.setpoint.get():.3g})")
                    att._move_changed(value=1 - att.done_value)
                    att._move_changed(value=att.done_value)
                    break
                _time.sleep(0.1)
            return not att.moving

        def _att_set(value):
            """Move the attenuator to ``value`` unless it is already there."""
            target = _att_target(value)
            if _att_at(target):
                return True
            if not _att_wait_idle():
                logger.error(
                    f"lens_minder: attenuator still moving after {att_timeout} s; "
                    f"cannot set it to {target:.4g}")
                return False
            att.move(target, wait=True, timeout=att_timeout)
            return True

        def _correct(n, m, setpoint, readback):
            # Read att and pulse picker now, immediately before this move (not
            # when the minder starts), so changes made while it runs are kept.
            att_prev = _att_target(att.position)
            pp_prev = _pp_state()
            logger.warning(
                f"lens_minder: TFS:{n:02d} y ({m['pv']}) RBV={readback:.3f} "
                f"VAL={setpoint:.3f} (off by {readback - setpoint:+.3f} mm). "
                f"Saved att={att_prev:.4g}, pulsepicker={pp_prev}."
            )
            try:
                if close_beam:
                    logger.warning(
                        "lens_minder: closing beam: pulsepicker.close(), att(0)"
                    )
                    pulsepicker.close()
                    try:
                        _att_set(0.0)
                    except Exception as ex:
                        logger.error(f"lens_minder: could not set attenuator to 0: {ex}")
                    if pulsepicker.position != "CLOSED" and not _att_at(0.0):
                        logger.error(
                            f"lens_minder: beam not confirmed closed; skipping move of TFS:{n:02d} y")
                        return False
                m["val"].put(setpoint, wait=True)
                t0 = _time.monotonic()
                _time.sleep(0.2)
                while not m["dmov"].get():
                    if _time.monotonic() - t0 > move_timeout:
                        logger.error(
                            f"lens_minder: TFS:{n:02d} y move timed out after {move_timeout} s"
                        )
                        break
                    _time.sleep(0.1)
                after = m["rbv"].get()
                if abs(after - setpoint) > tolerance_mm:
                    logger.error(
                        f"lens_minder: TFS:{n:02d} y still off: RBV={after:.3f} VAL={setpoint:.3f}"
                    )
                else:
                    logger.warning(
                        f"lens_minder: TFS:{n:02d} y back on setpoint: RBV={after:.3f}"
                    )
                return True
            finally:
                logger.warning(
                    f"lens_minder: restoring att={att_prev:.4g}, pulsepicker={pp_prev}"
                )
                try:
                    _att_set(att_prev)
                except Exception as ex:
                    logger.error(f"lens_minder: could not restore attenuator to {att_prev:.4g}: {ex}")
                try:
                    _pp_restore(pp_prev)
                except Exception as ex:
                    logger.error(f"lens_minder: could not restore pulse picker to {pp_prev}: {ex}")

        logger.warning(
            f"lens_minder: watching y motors of TFS lenses {lenses} every {poll_s} s, "
            f"tolerance +-{tolerance_mm} mm, close_beam={close_beam}. Ctrl+C to stop."
        )
        n_fix = 0
        try:
            while True:
                for n, m in motors.items():
                    if not m["dmov"].get():
                        continue  # motor is moving (e.g. a user move); leave it alone
                    setpoint, readback = m["val"].get(), m["rbv"].get()
                    if abs(readback - setpoint) > tolerance_mm:
                        try:
                            if _correct(n, m, setpoint, readback):
                                n_fix += 1
                        except Exception:
                            logger.exception(
                                f"lens_minder: correction of TFS:{n:02d} y failed; continuing")
                _time.sleep(poll_s)
        except KeyboardInterrupt:
            logger.warning(f"lens_minder: stopped by user after {n_fix} correction(s).")
        return n_fix

    def set_reference_combo(self, energy_eV, show=False, **kwargs):
        """
        kwargs:
            Passed to :meth:`.Calculator.find_solution`
        """
        combo = self.find_best_combo(energy_eV=energy_eV, show=show,  **kwargs)
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

    def track_focus(self, energies, *, margin_mm=10.0, show=False,
                    ref_focal_length_um=None, ref_z_stage_mm=None,
                    display=True, shrinking_rate=4, enable_prefocus=True,
                    lens_beam_energy_offset=0.0, **kwargs):
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

        kwargs:
            Passed to :meth:`.Calculator.find_solution`
        """
        if len(energies) == 0:
            print("No energies provided.")
            return None
        # cast energies to float to avoid json serialization issues
        energies = [float(energy) for energy in energies]

        enable_prefocus_save = enable_prefocus

        min_z_stage_mm, max_z_stage_mm = self.get_stage_limits(margin_mm)

        ref_zs_mm = self.mv_stage_to_pos(max_z_stage_mm)
        combo, ref_fl_um = self.set_reference_combo(energies[0], show=show, **kwargs)
        if ref_focal_length_um is None:
            ref_focal_length_um = ref_fl_um
        if ref_z_stage_mm is None:
            ref_z_stage_mm = ref_zs_mm

        track_record = []

        for energy in energies:
            enable_prefocus = enable_prefocus_save
            target_z_stage_mm = self.get_z_stage_target(
                energy, combo, ref_focal_length_um, ref_z_stage_mm
            )
            if min_z_stage_mm < target_z_stage_mm <= max_z_stage_mm:
                self.mv_stage_to_target_pos(
                    energy, combo, target_z_stage_mm, track_record
                )
            else:
                found_combo = False
                prefocus_fallback = True
                while prefocus_fallback:
                    shrinking_max_z_stage_mm = max_z_stage_mm
                    while shrinking_max_z_stage_mm > min_z_stage_mm:
                        self.mv_stage_to_pos(shrinking_max_z_stage_mm)
                        combo = self.find_best_combo(
                            energy_eV=energy, show=show, enable_prefocus=enable_prefocus, **kwargs
                        )
                        if combo:
                            new_target_z_stage_mm = self.get_z_stage_target(
                                energy, combo, ref_focal_length_um, ref_z_stage_mm
                            )
                            if min_z_stage_mm < new_target_z_stage_mm <= max_z_stage_mm:
                                self.mv_stage_to_target_pos(
                                    energy, combo, new_target_z_stage_mm, track_record
                                )
                                found_combo = True
                                # check compatibility with lens_beam_energy
                                if 'DIA' in combo.lenses[0].prefix:
                                    prefocus_lens_radius = combo.lenses[0].radius
                                    lens_beam_energy = energy + lens_beam_energy_offset
                                    #str(os.popen("caget MFX:LENS:BEAM:ENERGY | awk '{print $2}'").read().strip())
                                    radius = combo.tfs_radius
                                    from tfs.offline_calculator import TFS_Calculator as TFSCalc
                                    calc = TFSCalc(combo.lenses)
                                    forbidden = calc.check_forbidden(prefocus_lens_radius,
                                                         lens_beam_energy,
                                                         radius)
                                    if forbidden:
                                        found_combo = False
                                if found_combo:
                                    break
                        shrinking_max_z_stage_mm -= shrinking_rate*margin_mm
                    if found_combo:
                        break
                    else:
                        print("Stage out of travel. Cannot compensate further...")
                        if enable_prefocus:
                            print("Disabling prefocus for this energy.")
                            enable_prefocus = False
                        else:
                            prefocus_fallback = False

        print(f"Tracking complete. Final energy: {track_record[-1]['energy']:.2f} eV, stage position: {track_record[-1]['z_position']:.3f} mm.")
        print(f"Lenses currently inserted: {track_record[-1]['inserted_lenses']}")

        save_path = Path.home() / "track_focus_results.json"
        with open(save_path, "w") as f:
            json.dump(track_record, f, indent=4)
        print(f"Tracking results saved to {save_path}")
        if display:
            self.plot_focus_track(save_path)
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
