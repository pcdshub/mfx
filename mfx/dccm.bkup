"""
Double Crystal Channel-cut Monochromator (DCCM) control for MFX beamline.

Provides device classes for DCCM energy control, including PseudoPositioners
for energy-based motion with vernier integration and ACR (Automatic Crystal
Rotation) status monitoring.
"""

import enum
import logging
import time
import typing
from collections import namedtuple

import numpy as np
from epics import caput
from lightpath import LightpathState
from ophyd.device import Component as Cpt
from ophyd.device import FormattedComponent as FCpt
from ophyd.signal import EpicsSignal, EpicsSignalRO, Signal
from ophyd.status import MoveStatus

from pcdsdevices.analog_signals import FDQ
from pcdsdevices.beam_stats import BeamEnergyRequest
from pcdsdevices.device import GroupDevice
from pcdsdevices.device import UpdateComponent as UpCpt
from pcdsdevices.epics_motor import (IMS, BeckhoffAxis,
                                      BeckhoffAxisNoOffset,
                                      EpicsMotorInterface)
from pcdsdevices.interface import BaseInterface, FltMvInterface
from pcdsdevices.pseudopos import (PseudoPositioner, PseudoSingleInterface,
                                    SyncAxis, SyncAxisOffsetMode)
from pcdsdevices.pv_positioner import PVPositionerIsClose
from pcdsdevices.signal import InternalSignal
from pcdsdevices.utils import doc_format_decorator, get_status_float

logger = logging.getLogger(__name__)

# Constants
si_111_dspacing = 3.1356011499587773  # Silicon (111) d-spacing in Angstroms

# Defaults
default_dspacing = si_111_dspacing


class DCCMEnergy(FltMvInterface, PseudoPositioner):
    """
    DCCM energy pseudo-motor.

    Converts between X-ray energy (keV) and crystal Bragg angle,
    enabling energy-based positioning of the DCCM monochromator.

    Components
    ----------
    energy : PseudoSingle
        Energy setpoint in keV (pseudo axis)
    theta : Motor
        Crystal Bragg angle in degrees (real axis)

    Attributes
    ----------
    d_spacing : float
        Crystal d-spacing in Angstroms (default: Si 111 = 3.136 Å)

    Methods
    -------
    forward(pseudo_pos)
        Convert energy to Bragg angle
    inverse(real_pos)
        Convert Bragg angle to energy

    Notes
    -----
    Bragg's Law:
    E (keV) = 12.398 / (2 * d * sin(θ))

    Where:
    - E is photon energy in keV
    - d is crystal d-spacing in Angstroms
    - θ is Bragg angle in degrees

    Silicon (111) Crystal:
    - d-spacing: 3.1356 Å
    - Typical energy range: 4-25 keV
    - High reflectivity
    - Good energy resolution

    Energy Range:
    - Minimum: ~4 keV (θ ≈ 45°)
    - Maximum: ~25 keV (θ ≈ 7°)
    - Limited by crystal geometry

    Examples
    --------
    Create energy motor:
    >>> dccm_energy = DCCMEnergy('SP1L0:DCCM', name='dccm_energy')

    Move to 9 keV:
    >>> dccm_energy.move(9.0)

    Read current energy:
    >>> current_energy = dccm_energy.position
    >>> print(f"Energy: {current_energy:.3f} keV")

    See Also
    --------
    DCCM : Full DCCM assembly class
    DCCMEnergyWithVernier : Energy control with vernier integration
    """

    # Pseudo motor and real motor
    energy = Cpt(
        PseudoSingleInterface,
        egu='keV',
        kind='hinted',
        limits=(4, 25),
        verbose_name='DCCM Photon Energy',
        doc=(
            'PseudoSingle that moves the calculated DCCM '
            'selected energy in keV.'
        ),
    )

    th1 = Cpt(BeckhoffAxis, ":MMS:TH1", doc="Bragg Upstream/TH1 Axis", kind="normal", name='th1')
    th2 = Cpt(BeckhoffAxis, ":MMS:TH2", doc="Bragg Upstream/TH2 Axis", kind="normal", name='th2')

    tab_component_names = True

    def forward(self, pseudo_pos: namedtuple) -> namedtuple:
        """
        PseudoPositioner interface function for calculating the setpoint.

        Converts the requested energy to theta 1 and theta 2 (Bragg angle).
        """
        pseudo_pos = self.PseudoPosition(*pseudo_pos)
        energy = pseudo_pos.energy
        theta = self.energyToSi111BraggAngle(energy)
        return self.RealPosition(th1=theta, th2=theta)

    def inverse(self, real_pos: namedtuple) -> namedtuple:
        """
        PseudoPositioner interface function for calculating the readback.

        Converts the real position of the DCCM theta motor to the calculated energy.
        """
        real_pos = self.RealPosition(*real_pos)
        theta = real_pos.th1
        energy = self.thetaToSi111energy(theta)
        return self.PseudoPosition(energy=energy)

    def energyToSi111BraggAngle(self, energy: float) -> float:
        """
        Converts energy to Bragg angle theta

        Parameters
        ----------
        energy : float
            The photon energy (color) in keV.

        Returns
        ---------
        Bragg angle: float
            The angle in degrees
        """
        dspacing = 3.13560114
        energy = energy * 1000
        bragg_angle = np.rad2deg(np.arcsin(12398.419/energy/(2*dspacing)))
        return bragg_angle

    def thetaToSi111energy(self, theta):
        """
        Converts dccm theta angle to energy.

        Parameters
        ----------
        energy : float
            The Bragg angle theta in degrees

        Returns:
        ----------
        energy: float
             The photon energy (color) in keV.
        """
        dspacing = 3.13560114
        energy = 12398.419/(2*dspacing*np.sin(np.deg2rad(theta)))
        return energy/1000


class DCCMEnergyWithVernier(DCCMEnergy):
    """
    DCCM energy control with vernier integration.

    Extends DCCMEnergy to simultaneously request vernier energy
    changes via Machine Control Center (MCC) when moving DCCM.

    Components
    ----------
    vernier : BeamEnergyRequest
        Interface to MCC vernier energy request system

    Methods
    -------
    move(position, wait, timeout)
        Move DCCM energy and request vernier change

    Notes
    -----
    Coordinated Motion:
    - DCCM crystal angle changes via Bragg motion
    - Vernier (undulator K) requested via MCC
    - Both systems move to match energy

    Benefits:
    - Maintains beam position during energy changes
    - Optimizes undulator harmonics
    - Improves energy stability
    - Reduces need for manual vernier adjustment

    MCC Integration:
    - Automatic vernier energy request
    - No manual PV writing needed
    - MCC handles undulator control
    - Synchronized motion completion

    Typical Workflow:
    1. Request new energy
    2. DCCM begins crystal rotation
    3. MCC receives vernier request
    4. Undulator K parameter adjusts
    5. Both complete simultaneously

    Examples
    --------
    Create energy motor with vernier:
    >>> dccm = DCCMEnergyWithVernier('SP1L0:DCCM',
    ...                              hutch='mfx',
    ...                              name='dccm_vernier')

    Move to 9 keV (both DCCM and vernier):
    >>> dccm.move(9.0, wait=True)
    # DCCM rotates AND vernier adjusts

    See Also
    --------
    DCCMEnergy : Base energy control without vernier
    BeamEnergyRequest : MCC vernier interface
    """

    acr_energy = FCpt(BeamEnergyRequest, '{hutch}', kind='normal',
                      doc='Requests ACR to move the Vernier.')

    # These are duplicate warnings with main energy motor
    _enable_warn_constants: bool = False
    hutch: str

    def __init__(
        self,
        prefix: str,
        hutch = 'MFX',
        **kwargs
    ):
        self.hutch=hutch
        super().__init__(prefix, **kwargs)

    def forward(self, pseudo_pos: namedtuple) -> namedtuple:
        """
        PseudoPositioner interface function for calculating the setpoint.
        Converts the requested energy to theta 1 and theta 2 (Bragg angle).
        """
        pseudo_pos = self.PseudoPosition(*pseudo_pos)
        energy = pseudo_pos.energy
        theta = self.energyToSi111BraggAngle(energy)
        vernier = energy * 1000
        return self.RealPosition(th1=theta,th2=theta, acr_energy=vernier)

    def inverse(self, real_pos: namedtuple) -> namedtuple:
        """
        PseudoPositioner interface function for calculating the readback.
        Converts the real position of the DCCM theta motor to the calculated energy.
        """
        real_pos = self.RealPosition(*real_pos)
        theta = real_pos.th1
        energy = self.thetaToSi111energy(theta)
        return self.PseudoPosition(energy=energy)


class DCCMEnergyWithACRStatus(DCCMEnergyWithVernier):
    """
    DCCM energy control with ACR status monitoring.

    Extends DCCMEnergyWithVernier to monitor Automatic Crystal Rotation
    (ACR) completion status via SIOC PV.

    Components
    ----------
    acr_status : BeamEnergyRequest with status monitoring
        Extended vernier interface with ACR status feedback

    Attributes
    ----------
    acr_status_suffix : str
        PV suffix for ACR status (e.g., 'AO805')
    acr_status_pv_index : int
        Index for ACR status PV selection

    Methods
    -------
    move(position, wait, timeout)
        Move with ACR completion verification

    Notes
    -----
    ACR (Automatic Crystal Rotation):
    - MCC service for coordinated energy changes
    - Adjusts multiple beamline components
    - Reports completion via status PV
    - Ensures system-wide energy matching

    Status Monitoring:
    - ACR sets status PV when complete
    - Move waits for ACR confirmation
    - Prevents premature completion
    - Ensures full system synchronization

    Typical Components Adjusted by ACR:
    - Undulator K parameter (vernier)
    - Upstream crystal monochromators
    - Beam position monitors
    - Focus optimization

    Status PV Location:
    - SIOC:SYS0:ML00:{acr_status_suffix}
    - Typically AO805 for HXR
    - May vary by beamline

    Examples
    --------
    Create with ACR monitoring:
    >>> dccm = DCCMEnergyWithACRStatus(
    ...     'SP1L0:DCCM',
    ...     hutch='mfx',
    ...     acr_status_suffix='AO805',
    ...     pv_index=2,
    ...     name='dccm_acr'
    ... )

    Move and wait for ACR:
    >>> dccm.move(9.0, wait=True)
    # Waits for both DCCM motion AND ACR completion

    See Also
    --------
    DCCMEnergyWithVernier : Without ACR monitoring
    BeamEnergyRequest : Vernier/ACR interface
    """

    acr_energy = FCpt(BeamEnergyRequest, '{hutch}',
                      pv_index='{pv_index}',
                      acr_status_suffix='{acr_status_suffix}',
                      add_prefix=('suffix', 'write_pv', 'pv_index',
                                  'acr_status_suffix'),
                      kind='normal',
                      doc='Requests ACR to move the energy.')

    def __init__(
        self,
        prefix: str,
        hutch: typing.Optional[str] = None,
        acr_status_suffix='AO805',
        pv_index=2,
        **kwargs
    ):
        self.acr_status_suffix = acr_status_suffix
        self.pv_index = pv_index
        super().__init__(prefix, **kwargs)


class DCCM(BaseInterface, GroupDevice):
    """
    Complete Double Crystal Channel-cut Monochromator assembly.

    Controls all DCCM axes including crystal rotation, translation,
    and diagnostic YAG positioning. Provides multiple energy control
    interfaces.

    Components
    ----------
    th1 : BeckhoffAxis
        Upstream crystal theta (Bragg angle)
    th2 : BeckhoffAxis
        Downstream crystal theta (Bragg angle)
    tx : BeckhoffAxis
        Chamber translation in X
    txd : BeckhoffAxis
        YAG diagnostic translation in X
    tyd : BeckhoffAxis
        YAG diagnostic translation in Y
    energy : DCCMEnergy
        Basic energy control via Bragg angle
    energy_with_vernier : DCCMEnergyWithVernier
        Energy control with vernier coordination
    energy_with_acr_status : DCCMEnergyWithACRStatus
        Energy control with ACR status monitoring

    Attributes
    ----------
    tab_component_names : bool
        Enable tab completion for components

    Methods
    -------
    All standard motor and PseudoPositioner methods available
    through energy components

    Notes
    -----
    DCCM Configuration:
    - Two matched Si(111) crystals
    - Channel-cut design for stability
    - Temperature controlled
    - Vacuum chamber enclosed

    Axes Description:

    TH1/TH2 (Crystal Angles):
    - Typically move together
    - TH1: Upstream crystal
    - TH2: Downstream crystal
    - Energy determined by angle

    TX (Chamber Translation):
    - Moves entire DCCM assembly
    - Compensates for beam offset
    - Required for some energy changes

    TXD/TYD (YAG Diagnostics):
    - Position YAG for beam viewing
    - Independent of crystal motion
    - Used for alignment

    Energy Control Modes:

    1. Basic (energy):
       - Moves crystals only
       - Manual vernier adjustment needed
       - Simple, direct control

    2. With Vernier (energy_with_vernier):
       - Automatic vernier request
       - Better energy stability
       - Recommended for scans

    3. With ACR Status (energy_with_acr_status):
       - Full system coordination
       - Status verification
       - Safest for large changes

    Typical Operations:
    - Energy scans: Use energy_with_vernier
    - Large changes: Use energy_with_acr_status
    - Alignment: Use individual motors
    - Diagnostics: Use txd/tyd for YAG

    Examples
    --------
    Create DCCM device:
    >>> dccm = DCCM('SP1L0:DCCM', name='dccm')

    Move to 9 keV (basic):
    >>> dccm.energy.move(9.0)

    Move with vernier (recommended):
    >>> dccm.energy_with_vernier.move(9.0, wait=True)

    Move with ACR status (safest):
    >>> dccm.energy_with_acr_status.move(9.0, wait=True, timeout=60)

    Access individual motors:
    >>> dccm.th1.move(14.5)  # Move upstream crystal
    >>> dccm.tx.move(10.0)   # Translate chamber

    Position YAG for alignment:
    >>> dccm.txd.move(5.0)   # YAG X position
    >>> dccm.tyd.move(2.0)   # YAG Y position

    Read current energy:
    >>> energy = dccm.energy.position
    >>> print(f"Current energy: {energy:.3f} keV")

    See Also
    --------
    DCCMEnergy : Basic energy control
    DCCMEnergyWithVernier : With vernier integration
    DCCMEnergyWithACRStatus : With ACR monitoring
    """

    th1 = Cpt(BeckhoffAxis, ":MMS:TH1", doc="Bragg Upstream/TH1 Axis", kind="normal")
    th2 = Cpt(BeckhoffAxis, ":MMS:TH2", doc="Bragg Downstream/TH2 Axis", kind="normal")
    tx = Cpt(BeckhoffAxis, ":MMS:TX", doc="Translation X Axis", kind="normal")
    txd = Cpt(BeckhoffAxis, ":MMS:TXD", doc="YAG Diagnostic X Axis", kind="normal")
    tyd = Cpt(BeckhoffAxis, ":MMS:TYD", doc="YAG Diagnostic Y Axis", kind="normal")


    energy = Cpt(
        DCCMEnergy, '', kind='hinted',
        doc=(
            'PseudoPositioner that moves the theta motors in '
            'terms of the calculated DCCM energy.'
        ),
    )

    energy_with_vernier = Cpt(
        DCCMEnergyWithVernier, '', kind='normal',
        doc=(
            'PseudoPositioner that moves the theta motor in '
            'terms of the calculated DCCM energy while '
            'also requesting a vernier move.'
        ),
    )
    energy_with_acr_status = FCpt(
        DCCMEnergyWithACRStatus, '{prefix}', kind='normal',
        acr_status_suffix='{acr_status_suffix}',
        add_prefix=('suffix', 'write_pv', 'acr_status_suffix'),
        doc=(
            'PseudoPositioner that moves the alio in '
            'terms of the calculated CCM energy while '
            'also requesting an energy change to ACR. '
            'This will wait on ACR to complete the move.'
        ),
    )

    def __init__(
        self,
        prefix:str = "SP1L0:DCCM",
        **kwargs
    ):

        self.acr_status_suffix = kwargs.get('acr_status_suffix', 'AO805')
        self.acr_status_pv_index = kwargs.get('acr_status_suffix', 2)
        super().__init__(prefix, **kwargs)

        logger.info(f"DCCM initialized: {self.name}")
        logger.info(f"  Energy control modes: 3")
        logger.info(f"  Crystal motors: th1, th2")
        logger.info(f"  Translation: tx")
        logger.info(f"  Diagnostics: txd, tyd")

    def insert(self):
        caput('SP1L0:DCCM:MMS:STATE:SET','IN',wait=True)

    def remove(self):
        caput('SP1L0:DCCM:MMS:State:SET','OUT',wait=True)


def calculate_bragg_angle(energy_kev, d_spacing=default_dspacing):
    """
    Calculate Bragg angle for given energy.

    Utility function for quick Bragg angle calculation without
    creating device instance.

    Parameters
    ----------
    energy_kev : float
        Photon energy in keV
    d_spacing : float, optional
        Crystal d-spacing in Angstroms.
        Default is Si(111) = 3.1356 Å

    Returns
    -------
    float
        Bragg angle in degrees

    Notes
    -----
    Uses Bragg's law: θ = arcsin(12.398 / (2 * d * E))

    Examples
    --------
    Calculate angle for 9 keV with Si(111):
    >>> angle = calculate_bragg_angle(9.0)
    >>> print(f"Bragg angle: {angle:.3f}°")

    Different crystal:
    >>> angle = calculate_bragg_angle(9.0, d_spacing=2.7)

    See Also
    --------
    calculate_energy : Inverse calculation
    DCCMEnergy.forward : PseudoPositioner implementation
    """
    wavelength = 12.398 / energy_kev
    sin_theta = wavelength / (2.0 * d_spacing)

    if not -1.0 <= sin_theta <= 1.0:
        raise ValueError(
            f"Energy {energy_kev} keV out of range for "
            f"d-spacing {d_spacing} Å"
        )

    theta_rad = np.arcsin(sin_theta)
    theta_deg = np.degrees(theta_rad)
    return theta_deg


def calculate_energy(angle_deg, d_spacing=default_dspacing):
    """
    Calculate energy for given Bragg angle.

    Utility function for quick energy calculation without
    creating device instance.

    Parameters
    ----------
    angle_deg : float
        Bragg angle in degrees
    d_spacing : float, optional
        Crystal d-spacing in Angstroms.
        Default is Si(111) = 3.1356 Å

    Returns
    -------
    float
        Photon energy in keV

    Notes
    -----
    Uses Bragg's law: E = 12.398 / (2 * d * sin(θ))

    Examples
    --------
    Calculate energy for 14° with Si(111):
    >>> energy = calculate_energy(14.0)
    >>> print(f"Energy: {energy:.3f} keV")

    Different crystal:
    >>> energy = calculate_energy(14.0, d_spacing=2.7)

    See Also
    --------
    calculate_bragg_angle : Inverse calculation
    DCCMEnergy.inverse : PseudoPositioner implementation
    """
    theta_rad = np.radians(angle_deg)
    wavelength = 2.0 * d_spacing * np.sin(theta_rad)
    energy_kev = 12.398 / wavelength
    return energy_kev