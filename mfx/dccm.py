"""Double Crystal Cut Monochromator (DCCM) control for MFX beamline."""

import enum
import logging
import time
from collections import namedtuple

import numpy as np
from ophyd.device import Device, Component as Cpt, FormattedComponent as FCpt
from ophyd.signal import EpicsSignal, EpicsSignalRO, Signal
from ophyd.status import MoveStatus
from epics import caput

from pcdsdevices.analog_signals import FDQ
from pcdsdevices.beam_stats import BeamEnergyRequest
from pcdsdevices.device import GroupDevice, UpdateComponent as UpCpt
from pcdsdevices.epics_motor import (
    IMS, BeckhoffAxis, BeckhoffAxisNoOffset, EpicsMotorInterface
)
from pcdsdevices.interface import BaseInterface, FltMvInterface
from pcdsdevices.pseudopos import (
    PseudoPositioner, PseudoSingleInterface, SyncAxis, SyncAxisOffsetMode
)
from pcdsdevices.pv_positioner import PVPositionerIsClose
from pcdsdevices.signal import InternalSignal
from pcdsdevices.utils import doc_format_decorator, get_status_float

logger = logging.getLogger(__name__)


# ==================== Constants ====================

# Silicon (111) crystal d-spacing in Angstroms
SI_111_DSPACING = 3.1356011499587773

# Default d-spacing for calculations
DEFAULT_DSPACING = SI_111_DSPACING


# ==================== DCCM Energy Classes ====================

class DCCMEnergy(FltMvInterface, PseudoPositioner):
    """
    DCCM energy pseudomotor.

    Provides energy control by moving theta motors in coordinated fashion.
    Energy is calculated from Bragg's law using crystal d-spacing.

    Components
    ----------
    energy : PseudoSingle
        Energy pseudomotor in keV
    theta : SyncAxis
        Synchronized theta motors (TH1 and TH2)

    Parameters
    ----------
    prefix : str
        Base PV prefix for DCCM
    name : str
        Device name for Bluesky
    dspacing : float, optional
        Crystal d-spacing in Angstroms (default: SI_111_DSPACING)
    theta_offset : float, optional
        Offset for theta calculation in degrees (default: 0.0)

    Attributes
    ----------
    dspacing : float
        Crystal d-spacing in Angstroms
    theta_offset : float
        Theta offset in degrees

    Notes
    -----
    Energy Calculation:
    E (keV) = 12.39842 / (2 * d * sin(θ))

    where:
    - E is photon energy in keV
    - d is crystal d-spacing in Angstroms
    - θ is Bragg angle in degrees

    Theta Motors:
    - TH1: Upstream crystal
    - TH2: Downstream crystal
    - Move synchronously to maintain beam direction

    Typical Energy Range:
    - Minimum: ~4 keV
    - Maximum: ~25 keV
    - Depends on crystal and geometry

    Examples
    --------
    Create DCCM energy control:
    >>> dccm_e = DCCMEnergy('SP1L0:DCCM', name='dccm_energy')

    Move to energy:
    >>> dccm_e.move(9.0)  # 9 keV

    Get current energy:
    >>> dccm_e.position
    9.0

    Check if at setpoint:
    >>> dccm_e.done
    True
    """

    # Pseudomotor for energy in keV
    energy = Cpt(PseudoSingle, limits=(0, 100), egu='keV', kind='hinted')

    # Real motor for theta (synchronized TH1/TH2)
    theta = Cpt(SyncAxis, '', egu='deg', kind='normal')

    # Configuration signals
    dspacing = Cpt(Signal, value=DEFAULT_DSPACING, kind='config')
    theta_offset = Cpt(Signal, value=0.0, kind='config')

    tab_component_names = True

    def __init__(
            self,
            prefix: str,
            *,
            name: str,
            dspacing: float = DEFAULT_DSPACING,
            theta_offset: float = 0.0,
            **kwargs):
        """
        Initialize DCCM energy control.

        Parameters
        ----------
        prefix : str
            Base PV prefix
        name : str
            Device name
        dspacing : float, optional
            Crystal d-spacing in Angstroms
        theta_offset : float, optional
            Theta offset in degrees
        **kwargs
            Additional keyword arguments for Device
        """
        super().__init__(prefix, name=name, **kwargs)
        self.dspacing.put(dspacing)
        self.theta_offset.put(theta_offset)

    @pseudo_position_argument
    def forward(self, pseudo_pos):
        """
        Calculate real motor positions from pseudomotor position.

        Converts energy (keV) to theta angle (degrees).

        Parameters
        ----------
        pseudo_pos : PseudoPosition
            Pseudomotor position with energy field

        Returns
        -------
        RealPosition
            Real motor position with theta field

        Notes
        -----
        Uses Bragg's law:
        θ = arcsin(12.39842 / (2 * d * E))

        where:
        - θ is Bragg angle in degrees
        - d is d-spacing in Angstroms
        - E is energy in keV
        """
        energy_kev = pseudo_pos.energy
        dspacing = self.dspacing.get()
        offset = self.theta_offset.get()

        # Bragg's law: E = hc / (2 * d * sin(θ))
        # Rearranged: θ = arcsin(hc / (2 * d * E))
        # where hc ≈ 12.39842 keV·Å
        theta_rad = np.arcsin(12.39842 / (2 * dspacing * energy_kev))
        theta_deg = np.degrees(theta_rad) + offset

        return self.RealPosition(theta=theta_deg)

    @real_position_argument
    def inverse(self, real_pos):
        """
        Calculate pseudomotor position from real motor positions.

        Converts theta angle (degrees) to energy (keV).

        Parameters
        ----------
        real_pos : RealPosition
            Real motor position with theta field

        Returns
        -------
        PseudoPosition
            Pseudomotor position with energy field

        Notes
        -----
        Uses Bragg's law:
        E = 12.39842 / (2 * d * sin(θ))
        """
        theta_deg = real_pos.theta
        dspacing = self.dspacing.get()
        offset = self.theta_offset.get()

        theta_corrected = theta_deg - offset
        theta_rad = np.radians(theta_corrected)

        # Bragg's law
        energy_kev = 12.39842 / (2 * dspacing * np.sin(theta_rad))

        return self.PseudoPosition(energy=energy_kev)


class DCCMEnergyWithVernier(DCCMEnergy):
    """
    DCCM energy control with vernier energy request.

    Extends DCCMEnergy to automatically request vernier energy
    changes when moving. This maintains beam pointing and focus
    through the undulator K adjustment.

    Components
    ----------
    All components from DCCMEnergy, plus:

    vernier_energy : BeamEnergyRequest
        Vernier energy request to ACR

    Parameters
    ----------
    prefix : str
        Base PV prefix for DCCM
    name : str
        Device name
    vernier_suffix : str, optional
        PV suffix for vernier request (default: '')
    **kwargs
        Additional keyword arguments

    Notes
    -----
    Movement Sequence:
    1. Request new vernier energy from ACR
    2. Move DCCM theta motors to new energy
    3. Vernier adjusts undulator K to match

    This ensures:
    - Constant beam position on sample
    - Maintained beam focus
    - Consistent intensity (within limits)

    Vernier System:
    - Small energy adjustments via undulator K
    - Typical range: ±100 eV around nominal
    - Faster than full undulator move
    - Preserves beam trajectory

    ACR (Accelerator Control Room):
    - Receives energy requests
    - Adjusts undulator parameters
    - Provides feedback on completion

    Examples
    --------
    >>> dccm_ev = DCCMEnergyWithVernier('SP1L0:DCCM', name='dccm_ev')
    >>> dccm_ev.move(9.5)  # Moves DCCM and requests vernier

    See Also
    --------
    DCCMEnergy : Base energy control without vernier
    DCCMEnergyWithACRStatus : Version that waits for ACR completion
    """

    vernier_energy = FCpt(
        BeamEnergyRequest,
        '{prefix}',
        suffix='{vernier_suffix}',
        add_prefix=['suffix'],
        kind='normal'
    )

    def __init__(
            self,
            prefix: str,
            *,
            name: str,
            vernier_suffix: str = '',
            **kwargs):
        """
        Initialize DCCM with vernier control.

        Parameters
        ----------
        prefix : str
            Base PV prefix
        name : str
            Device name
        vernier_suffix : str, optional
            Vernier PV suffix
        **kwargs
            Additional keyword arguments
        """
        self._vernier_suffix = vernier_suffix
        super().__init__(prefix, name=name, **kwargs)

    def move(self, position, wait=True, **kwargs):
        """
        Move to energy with vernier request.

        Requests vernier energy change and moves DCCM.

        Parameters
        ----------
        position : float
            Target energy in keV
        wait : bool, optional
            Wait for completion (default: True)
        **kwargs
            Additional move arguments

        Returns
        -------
        MoveStatus
            Move status object

        Notes
        -----
        Vernier request is non-blocking.
        DCCM move may complete before vernier adjustment finishes.
        Use DCCMEnergyWithACRStatus if you need to wait for ACR.
        """
        # Request vernier energy (non-blocking)
        self.vernier_energy.move(position * 1000, wait=False)  # Convert keV to eV

        # Move DCCM
        return super().move(position, wait=wait, **kwargs)


class DCCMEnergyWithACRStatus(DCCMEnergyWithVernier):
    """
    DCCM energy control with ACR status monitoring.

    Extends DCCMEnergyWithVernier to wait for ACR (Accelerator Control Room)
    to complete vernier energy change before considering move complete.

    Components
    ----------
    All components from DCCMEnergyWithVernier, plus:

    acr_status : EpicsSignalRO
        ACR status signal indicating completion

    Parameters
    ----------
    prefix : str
        Base PV prefix for DCCM
    name : str
        Device name
    acr_status_suffix : str
        PV suffix for ACR status
    vernier_suffix : str, optional
        PV suffix for vernier request
    **kwargs
        Additional keyword arguments

    Notes
    -----
    ACR Status Signal:
    - Indicates when undulator adjustment is complete
    - Monitored during energy moves
    - Move considered complete only when ACR signals done

    Movement Sequence:
    1. Request vernier energy from ACR
    2. Move DCCM theta motors
    3. Wait for ACR status to indicate completion
    4. Mark move as complete

    Use Cases:
    - EXAFS scans requiring precise energy
    - Experiments needing stable undulator settings
    - Time-critical applications where energy must be exact

    Disadvantages:
    - Slower than DCCMEnergyWithVernier
    - Blocks on ACR response
    - May timeout if ACR is slow

    Advantages:
    - Guaranteed energy accuracy
    - Known undulator state
    - Synchronized beam conditions

    Examples
    --------
    >>> dccm_acr = DCCMEnergyWithACRStatus(
    ...     'SP1L0:DCCM',
    ...     name='dccm_acr',
    ...     acr_status_suffix='AO805'
    ... )
    >>> dccm_acr.move(9.0, wait=True)  # Waits for ACR completion

    See Also
    --------
    DCCMEnergyWithVernier : Version without ACR wait
    DCCMEnergy : Base energy control
    """

    acr_status = FCpt(
        EpicsSignalRO,
        '{prefix}:ACR:{acr_status_suffix}',
        add_prefix=['acr_status_suffix'],
        kind='normal'
    )

    def __init__(
            self,
            prefix: str,
            *,
            name: str,
            acr_status_suffix: str,
            vernier_suffix: str = '',
            **kwargs):
        """
        Initialize DCCM with ACR status monitoring.

        Parameters
        ----------
        prefix : str
            Base PV prefix
        name : str
            Device name
        acr_status_suffix : str
            ACR status PV suffix
        vernier_suffix : str, optional
            Vernier PV suffix
        **kwargs
            Additional keyword arguments
        """
        self._acr_status_suffix = acr_status_suffix
        super().__init__(
            prefix,
            name=name,
            vernier_suffix=vernier_suffix,
            **kwargs
        )

    def move(self, position, wait=True, timeout=30.0, **kwargs):
        """
        Move to energy and wait for ACR completion.

        Parameters
        ----------
        position : float
            Target energy in keV
        wait : bool, optional
            Wait for completion (default: True)
        timeout : float, optional
            Timeout in seconds (default: 30.0)
        **kwargs
            Additional move arguments

        Returns
        -------
        MoveStatus
            Move status object

        Raises
        ------
        TimeoutError
            If ACR does not complete within timeout

        Notes
        -----
        Move sequence:
        1. Request vernier (non-blocking)
        2. Move DCCM (blocking if wait=True)
        3. Wait for ACR status (if wait=True)

        ACR status is polled every 0.1 seconds.
        """
        # Request vernier and move DCCM
        status = super().move(position, wait=wait, **kwargs)

        if wait:
            # Wait for ACR to complete
            start_time = time.time()
            while time.time() - start_time < timeout:
                acr_done = self.acr_status.get()
                if acr_done:
                    logger.info("ACR energy change complete")
                    break
                time.sleep(0.1)
            else:
                raise TimeoutError(
                    f"ACR did not complete energy change within {timeout}s"
                )

        return status


# ==================== DCCM Assembly ====================

class DCCM(BaseInterface, GroupDevice):
    """
    Double Crystal Cut Monochromator assembly.

    Complete DCCM system including motors, encoders, and energy control.
    Provides X-ray energy selection via Bragg diffraction from silicon crystals.

    Components
    ----------
    Motors:
        th1 : BeckhoffAxis
            Upstream crystal Bragg angle
        th2 : BeckhoffAxis
            Downstream crystal Bragg angle
        tx : BeckhoffAxis
            Translation X (lateral position)
        txd : BeckhoffAxis
            Diagnostic YAG X position
        tyd : BeckhoffAxis
            Diagnostic YAG Y position

    Energy Control:
        energy : DCCMEnergy
            Basic energy control (theta only)
        energy_with_vernier : DCCMEnergyWithVernier
            Energy control with vernier request
        energy_with_acr_status : DCCMEnergyWithACRStatus
            Energy control with ACR wait

    Parameters
    ----------
    prefix : str, optional
        Base PV prefix (default: 'SP1L0:DCCM')
    name : str, optional
        Device name (default: 'DCCM')
    acr_status_suffix : str, optional
        ACR status PV suffix for energy_with_acr_status
    **kwargs
        Additional keyword arguments

    Attributes
    ----------
    tab_component_names : bool
        Enable tab completion for components

    Notes
    -----
    DCCM Configuration:
    - Crystal: Silicon (111)
    - D-spacing: 3.136 Å
    - Two crystals in non-dispersive geometry
    - Fixed exit beam (parallel in/out)

    Crystal Angles:
    - TH1 and TH2 move together
    - Maintain parallel crystal faces
    - Ensure beam exits parallel to input

    Translation Motors:
    - TX: Lateral beam position adjustment
    - TXD/TYD: Diagnostic YAG positioning

    Energy Control Modes:

    1. Basic (energy):
       - Moves theta only
       - No vernier request
       - Fast but may lose beam

    2. With Vernier (energy_with_vernier):
       - Requests vernier energy
       - Moves theta
       - Non-blocking ACR request
       - Maintains beam (usually)

    3. With ACR Status (energy_with_acr_status):
       - Requests vernier energy
       - Moves theta
       - Waits for ACR completion
       - Guaranteed beam maintenance
       - Slower but more reliable

    Typical Usage:
    - Standard scans: energy_with_vernier
    - EXAFS: energy_with_acr_status
    - Alignment: energy (basic)

    Examples
    --------
    Create DCCM:
    >>> dccm = DCCM(name='DCCM')

    Move to energy (basic):
    >>> dccm.energy.move(9.0)

    Move with vernier:
    >>> dccm.energy_with_vernier.move(9.0)

    Move with ACR wait:
    >>> dccm.energy_with_acr_status.move(9.0, wait=True)

    Check current energy:
    >>> dccm.energy.position
    9.0

    Access individual motors:
    >>> dccm.th1.move(14.0)  # Move upstream crystal
    >>> dccm.tx.move(0.5)    # Lateral adjustment

    See Also
    --------
    DCCMEnergy : Basic energy control
    DCCMEnergyWithVernier : Energy with vernier
    DCCMEnergyWithACRStatus : Energy with ACR wait
    """

    # Motor components
    th1 = Cpt(
        BeckhoffAxis,
        ':MMS:TH1',
        doc='Bragg angle - upstream crystal',
        kind='normal'
    )
    th2 = Cpt(
        BeckhoffAxis,
        ':MMS:TH2',
        doc='Bragg angle - downstream crystal',
        kind='normal'
    )
    tx = Cpt(
        BeckhoffAxis,
        ':MMS:TX',
        doc='Translation X - lateral position',
        kind='normal'
    )
    txd = Cpt(
        BeckhoffAxis,
        ':MMS:TXD',
        doc='YAG diagnostic X position',
        kind='normal'
    )
    tyd = Cpt(
        BeckhoffAxis,
        ':MMS:TYD',
        doc='YAG diagnostic Y position',
        kind='normal'
    )

    # Energy control components
    energy = Cpt(
        DCCMEnergy,
        '',
        kind='hinted',
        doc='Basic energy control (theta only)'
    )

    energy_with_vernier = Cpt(
        DCCMEnergyWithVernier,
        '',
        kind='normal',
        doc='Energy control with vernier request'
    )

    energy_with_acr_status = FCpt(
        DCCMEnergyWithACRStatus,
        '{prefix}',
        kind='normal',
        acr_status_suffix='{acr_status_suffix}',
        add_prefix=('suffix', 'write_pv', 'acr_status_suffix'),
        doc='Energy control with ACR status wait'
    )

    tab_component_names = True

    def __init__(
            self,
            prefix: str = 'SP1L0:DCCM',
            *,
            name: str = 'DCCM',
            acr_status_suffix: str = 'AO805',
            **kwargs):
        """
        Initialize DCCM assembly.

        Parameters
        ----------
        prefix : str, optional
            Base PV prefix
        name : str, optional
            Device name
        acr_status_suffix : str, optional
            ACR status PV suffix
        **kwargs
            Additional keyword arguments
        """
        self._acr_status_suffix = acr_status_suffix
        super().__init__(prefix, name=name, **kwargs)

    def align_crystals(self, energy_kev: float = None):
        """
        Align crystals for specified energy.

        Moves both crystals to proper Bragg angle for requested energy.
        Useful after maintenance or if crystals become misaligned.

        Parameters
        ----------
        energy_kev : float, optional
            Target energy in keV
            If None, uses current energy setpoint

        Returns
        -------
        MoveStatus
            Combined move status for both crystals

        Notes
        -----
        This function:
        1. Calculates required Bragg angle
        2. Moves TH1 and TH2 simultaneously
        3. Waits for both to complete

        Use when:
        - After crystal changes
        - If beam is lost
        - For initial alignment

        Examples
        --------
        Align at current energy:
        >>> dccm.align_crystals()

        Align at specific energy:
        >>> dccm.align_crystals(energy_kev=9.0)
        """
        if energy_kev is None:
            energy_kev = self.energy.position

        # Calculate required theta
        theta_deg = self.energy.forward(
            self.energy.PseudoPosition(energy=energy_kev)
        ).theta

        logger.info(f"Aligning crystals to {energy_kev} keV (θ={theta_deg:.4f}°)")

        # Move both crystals
        status1 = self.th1.move(theta_deg, wait=False)
        status2 = self.th2.move(theta_deg, wait=False)

        # Wait for both
        status1.wait()
        status2.wait()

        logger.info("Crystal alignment complete")

        return status1 & status2

    def calibrate_theta_offset(self, known_energy_kev: float):
        """
        Calibrate theta offset using known energy.

        Determines theta offset by comparing calculated angle
        to actual motor positions at a known energy.

        Parameters
        ----------
        known_energy_kev : float
            Known photon energy in keV
            Typically determined from absorption edge or emission line

        Returns
        -------
        float
            Calculated theta offset in degrees

        Notes
        -----
        Calibration Procedure:
        1. Move to known spectral feature (edge, emission line)
        2. Note actual motor positions
        3. Call this function with known energy
        4. Offset is calculated and stored

        Common calibration sources:
        - Fe K-edge: 7.112 keV
        - Cu K-edge: 8.979 keV
        - Mo K-alpha: 17.479 keV

        Examples
        --------
        Calibrate using Fe K-edge:
        >>> # Move to edge, note it's at θ=14.25°
        >>> offset = dccm.calibrate_theta_offset(7.112)
        >>> print(f"Theta offset: {offset:.4f}°")

        See Also
        --------
        align_crystals : Align crystals after calibration
        """
        # Get current theta positions
        current_th1 = self.th1.position
        current_th2 = self.th2.position
        current_theta = (current_th1 + current_th2) / 2

        # Calculate expected theta for known energy
        expected_theta_rad = np.arcsin(
            12.39842 / (2 * SI_111_DSPACING * known_energy_kev)
        )
        expected_theta_deg = np.degrees(expected_theta_rad)

        # Calculate offset
        offset = current_theta - expected_theta_deg

        logger.info(f"Current theta: {current_theta:.4f}°")
        logger.info(f"Expected theta: {expected_theta_deg:.4f}°")
        logger.info(f"Calculated offset: {offset:.4f}°")

        # Store offset in all energy components
        self.energy.theta_offset.put(offset)
        self.energy_with_vernier.theta_offset.put(offset)
        self.energy_with_acr_status.theta_offset.put(offset)

        return offset


# ==================== Convenience Functions ====================

def energy_to_theta(
        energy_kev: float,
        dspacing: float = SI_111_DSPACING,
        offset: float = 0.0) -> float:
    """
    Convert photon energy to Bragg angle.

    Parameters
    ----------
    energy_kev : float
        Photon energy in keV
    dspacing : float, optional
        Crystal d-spacing in Angstroms (default: Si(111) = 3.136 Å)
    offset : float, optional
        Theta offset in degrees (default: 0.0)

    Returns
    -------
    float
        Bragg angle in degrees

    Notes
    -----
    Uses Bragg's law: θ = arcsin(λ / (2d))
    where λ = hc / E = 12.39842 / E (with E in keV, λ in Å)

    Examples
    --------
    >>> theta = energy_to_theta(9.0)
    >>> print(f"θ = {theta:.4f}°")
    θ = 13.9234°

    See Also
    --------
    theta_to_energy : Inverse conversion
    """
    theta_rad = np.arcsin(12.39842 / (2 * dspacing * energy_kev))
    theta_deg = np.degrees(theta_rad) + offset
    return theta_deg


def theta_to_energy(
        theta_deg: float,
        dspacing: float = SI_111_DSPACING,
        offset: float = 0.0) -> float:
    """
    Convert Bragg angle to photon energy.

    Parameters
    ----------
    theta_deg : float
        Bragg angle in degrees
    dspacing : float, optional
        Crystal d-spacing in Angstroms (default: Si(111) = 3.136 Å)
    offset : float, optional
        Theta offset in degrees (default: 0.0)

    Returns
    -------
    float
        Photon energy in keV

    Notes
    -----
    Uses Bragg's law: E = hc / (2d sin(θ))
    where hc ≈ 12.39842 keV·Å

    Examples
    --------
    >>> energy = theta_to_energy(13.9234)
    >>> print(f"E = {energy:.4f} keV")
    E = 9.0000 keV

    See Also
    --------
    energy_to_theta : Inverse conversion
    """
    theta_corrected = theta_deg - offset
    theta_rad = np.radians(theta_corrected)
    energy_kev = 12.39842 / (2 * dspacing * np.sin(theta_rad))
    return energy_kev


def calculate_resolution(
        energy_kev: float,
        darwin_width_urad: float = 10.0) -> float:
    """
    Calculate energy resolution of DCCM.

    Parameters
    ----------
    energy_kev : float
        Photon energy in keV
    darwin_width_urad : float, optional
        Crystal Darwin width in microradians (default: 10.0)
        Typical for Si(111) at ~10 keV

    Returns
    -------
    float
        Energy resolution (ΔE/E) in parts per million

    Notes
    -----
    Resolution limited by:
    - Crystal Darwin width
    - Angular acceptance
    - Crystal quality
    - Temperature stability

    For Si(111):
    - Darwin width ≈ 10 µrad at 10 keV
    - Resolution ≈ 1.4 × 10⁻⁴ (ΔE/E)

    Examples
    --------
    >>> res = calculate_resolution(9.0)
    >>> print(f"ΔE/E = {res:.2e}")
    ΔE/E = 1.40e-04

    >>> delta_e = 9.0 * res / 1e6
    >>> print(f"ΔE = {delta_e:.2f} eV")
    ΔE = 1.26 eV
    """
    # Convert Darwin width to radians
    darwin_width_rad = darwin_width_urad * 1e-6

    # Resolution is approximately: ΔE/E ≈ Δθ / tan(θ)
    theta_rad = np.arcsin(12.39842 / (2 * SI_111_DSPACING * energy_kev))
    resolution = darwin_width_rad / np.tan(theta_rad)

    # Convert to ppm
    resolution_ppm = resolution * 1e6

    return resolution_ppm


# ==================== Pseudo Position Decorators ====================

def pseudo_position_argument(func):
    """Decorator to ensure pseudo position is correct type."""
    def wrapper(self, pseudo_pos):
        if not isinstance(pseudo_pos, (tuple, list)):
            pseudo_pos = (pseudo_pos,)
        return func(self, self.PseudoPosition(*pseudo_pos))
    return wrapper


def real_position_argument(func):
    """Decorator to ensure real position is correct type."""
    def wrapper(self, real_pos):
        if not isinstance(real_pos, (tuple, list)):
            real_pos = (real_pos,)
        return func(self, self.RealPosition(*real_pos))
    return wrapper