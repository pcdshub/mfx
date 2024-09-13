import math
import logging

from pcdsdevices.device_types import IMS
from ophyd import (Device, EpicsSignalRO, Component as Cpt,
    FormattedComponent, EpicsSignal)
from ophyd.status import wait as status_wait

from tfs.lens import LensConnect, LensTripLimits
from tfs.lens import MFXLens as Lens
from tfs.offline_calculator import TFS_Calculator
from functools import wraps
from tfs.utils import estimate_beam_fwhm, focal_length

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

    def __init__(self, prefix, *, nominal_sample=399.88103, **kwargs):
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

    def find_best_combo(self, target=None, energy=None, show=True, **kwargs):
        """
        Calculate the best lens array to hit the nominal sample point

        Parameters
        ----------
        target : float, optional
            The target image of the lens array. By default this is
            `nominal_sample`

        show : bool, optional
            Print a table of the of the calculated lens combination

        kwargs:
            Passed to :meth:`.Calculator.find_solution`
        """
        energy = energy or self.beam_energy.get()
        target = target or self.nominal_sample
        calc = TFS_Calculator(tfs_lenses=self.tfs_lenses, prefocus_lenses=self.xrt_lenses)
        combo, diff = calc.find_solution(target, energy, **kwargs)
        if combo:
            combo.show_info()
            logger.info(f'Difference to desired focus position: {round(diff*1000, 2)} mm')
            radius = combo.effective_radius
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
