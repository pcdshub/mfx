"""
Energy control and calibration utilities for MFX beamline.

This module provides interfaces for reading and writing vernier energy
values via EPICS PVs, enabling precise energy tuning through undulator
K parameter adjustments and monochromator control.
"""

import os
import logging

logger = logging.getLogger(__name__)


class EnergyGet:
    """
    Read vernier energy values from EPICS PVs.

    Provides methods to read current vernier energy settings from both
    reference and setpoint PVs, as well as DCCM monochromator energy.

    The vernier system uses four main energy PVs:
    - REF1: First reference energy for calibration
    - REF2: Second reference energy for calibration
    - SET1: First setpoint energy for control
    - SET2: Second setpoint energy for control

    Attributes
    ----------
    dccm : DCCM
        DCCM monochromator device for direct energy readback

    Methods
    -------
    all()
        Read all energy PVs (REF1, REF2, SET1, SET2, DCCM)
    vernier_ref()
        Read reference energy 1 (MFX:USER:MCC:EPHOT:REF1)
    k_ref()
        Read reference energy 2 (MFX:USER:MCC:EPHOT:REF2)
    vernier()
        Read setpoint energy 1 (MFX:USER:MCC:EPHOT:SET1)
    k_energy()
        Read setpoint energy 2 (MFX:USER:MCC:EPHOT:SET2)
    mono()
        Read DCCM monochromator energy

    Notes
    -----
    PV Locations:
    - REF1: MFX:USER:MCC:EPHOT:REF1
    - REF2: MFX:USER:MCC:EPHOT:REF2
    - SET1: MFX:USER:MCC:EPHOT:SET1
    - SET2: MFX:USER:MCC:EPHOT:SET2

    Energy Units:
    - All energies returned in eV
    - Typical range: 4000-25000 eV
    - DCCM energy converted from keV to eV

    Reading Methods:
    - Uses caget via os.popen()
    - Parses output with awk
    - Returns float value
    - Logs each read operation

    Examples
    --------
    Read all energy values:
    >>> vget = EnergyGet()
    >>> vget.all()
    vernier_ref: 9000.0 eV
    k_ref: 9000.0 eV
    vernier: 9000.0 eV
    k_energy: 9000.0 eV
    dccm: 9000.0 eV

    Read specific values:
    >>> vernier_ref = vget.vernier_ref()
    >>> vernier = vget.vernier()
    >>> print(f"Reference: {vernier_ref}, Setpoint: {vernier}")

    Check monochromator energy:
    >>> mono_energy = vget.mono()
    >>> print(f"DCCM Energy: {mono_energy} eV")

    See Also
    --------
    EnergyPut : Set vernier energy values
    DCCM : Monochromator device control
    """

    def __init__(self):
        """
        Initialize EnergyGet interface.

        Creates DCCM device instance for monochromator energy readback.
        """
        from mfx.dccm import DCCM
        self.dccm = DCCM(name='DCCM')

    def all(self):
        """
        Get all energy PVs and references.

        Reads and displays all vernier energy PVs (REF1, REF2, SET1,
        SET2) and DCCM monochromator energy. Useful for verifying
        system state and energy consistency.

        Returns
        -------
        None
            Prints all energy values to log

        Notes
        -----
        Use Cases:
        - Initial setup verification
        - Post-calibration checks
        - Troubleshooting energy inconsistencies
        - System state documentation

        This ensures all vernier PVs are displayed together, making it
        easy to identify inconsistencies or calibration issues.

        Examples
        --------
        Display all energies:
        >>> vget = EnergyGet()
        >>> vget.all()
        vernier_ref: 9000.0 eV
        k_ref: 9000.0 eV
        vernier: 9000.0 eV
        k_energy: 9000.0 eV
        dccm: 9000.0 eV
        """
        logger.info("Reading all vernier PVs in eV")
        self.vernier_ref()
        self.k_ref()
        self.vernier()
        self.k_energy()
        self.mono()

    def vernier_ref(self):
        """
        Read vernier reference energy (REF1).

        Returns
        -------
        float
            Reference energy in eV

        Notes
        -----
        Reference energies store calibration values typically set
        during initial beamline setup. REF1 is used as the primary
        calibration reference for vernier operations.

        PV: MFX:USER:MCC:EPHOT:REF1

        Examples
        --------
        >>> vget = EnergyGet()
        >>> vernier_ref = vget.vernier_ref()
        vernier_ref: 9000.0 eV
        >>> print(f"Reference: {vernier_ref} eV")

        See Also
        --------
        k_ref : Read second reference energy
        EnergyPut.vernier_ref : Set reference energy
        """
        energy = float(
            os.popen("caget MFX:USER:MCC:EPHOT:REF1 | awk '{print $2}'")
            .read()
            .strip()
        )
        logger.info(f"vernier_ref: {energy} eV")
        return energy

    def k_ref(self):
        """
        Read k reference energy (REF2).

        Returns
        -------
        float
            Second reference energy in eV

        Notes
        -----
        Second reference energy for dual-energy applications or backup
        calibration. REF2 provides an independent calibration point
        for K-parameter based energy control.

        PV: MFX:USER:MCC:EPHOT:REF2

        Examples
        --------
        >>> vget = EnergyGet()
        >>> k_ref = vget.k_ref()
        k_ref: 9000.0 eV

        See Also
        --------
        vernier_ref : Read first reference energy
        EnergyPut.k_ref : Set second reference energy
        """
        energy = float(
            os.popen("caget MFX:USER:MCC:EPHOT:REF2 | awk '{print $2}'")
            .read()
            .strip()
        )
        logger.info(f"k_ref: {energy} eV")
        return energy

    def vernier(self):
        """
        Read vernier setpoint energy (SET1).

        Returns
        -------
        float
            Setpoint energy in eV

        Notes
        -----
        Setpoint energies control the actual undulator K parameter.
        SET1 is the primary setpoint used for vernier energy control.

        PV: MFX:USER:MCC:EPHOT:SET1

        Typical Use:
        - Read current energy request
        - Verify energy changes
        - Compare with reference

        Examples
        --------
        >>> vget = EnergyGet()
        >>> vernier = vget.vernier()
        vernier: 9005.0 eV

        Compare setpoint to reference:
        >>> ref = vget.vernier_ref()
        >>> set_pt = vget.vernier()
        >>> offset = set_pt - ref
        >>> print(f"Energy offset: {offset} eV")

        See Also
        --------
        k_energy : Read second setpoint energy
        EnergyPut.vernier : Set primary setpoint
        """
        energy = float(
            os.popen("caget MFX:USER:MCC:EPHOT:SET1 | awk '{print $2}'")
            .read()
            .strip()
        )
        logger.info(f"vernier: {energy} eV")
        return energy

    def k_energy(self):
        """
        Read k setpoint energy (SET2).

        Returns
        -------
        float
            Second setpoint energy in eV

        Notes
        -----
        Second setpoint energy for K-parameter control. SET2 provides
        independent energy control useful for dual-energy experiments
        or alternative control schemes.

        PV: MFX:USER:MCC:EPHOT:SET2

        Examples
        --------
        >>> vget = EnergyGet()
        >>> k_energy = vget.k_energy()
        k_energy: 9005.0 eV

        See Also
        --------
        vernier : Read primary setpoint energy
        EnergyPut.k_energy : Set second setpoint
        """
        energy = float(
            os.popen("caget MFX:USER:MCC:EPHOT:SET2 | awk '{print $2}'")
            .read()
            .strip()
        )
        logger.info(f"k_energy: {energy} eV")
        return energy

    def mono(self):
        """
        Read DCCM monochromator energy.

        Returns
        -------
        float
            DCCM energy in eV

        Notes
        -----
        Reads energy directly from DCCM (Double Crystal Channel-cut
        Monochromator) device. This provides independent verification
        of the beam energy based on crystal diffraction angle.

        Energy Conversion:
        - DCCM reports in keV
        - Converted to eV for consistency
        - Rounded to 0.1 eV precision

        The DCCM energy is calculated from the Bragg angle and crystal
        d-spacing, providing absolute energy calibration independent
        of the vernier system.

        Examples
        --------
        >>> vget = EnergyGet()
        >>> mono = vget.mono()
        dccm: 9000.0 eV

        Compare vernier to monochromator:
        >>> vernier_e = vget.vernier()
        >>> dccm_e = vget.mono()
        >>> diff = vernier_e - dccm_e
        >>> print(f"Vernier offset: {diff} eV")

        See Also
        --------
        DCCM : Monochromator device class
        EnergyPut.mono : Set DCCM energy
        """
        energy = round(self.dccm.energy() * 1000, 1)
        logger.info(f"dccm: {energy} eV")
        return energy


class EnergyPut:
    """
    Set vernier energy values via EPICS PVs.

    Provides methods to write vernier energy setpoints to control
    undulator K parameter and DCCM monochromator position.

    Methods
    -------
    all(energy)
        Set all vernier PVs to same energy
    vernier_ref(energy)
        Set reference energy 1
    k_ref(energy)
        Set reference energy 2
    vernier(energy)
        Set setpoint energy 1
    k_energy(energy)
        Set setpoint energy 2
    mono(energy)
        Set DCCM monochromator energy

    Notes
    -----
    PV Locations:
    - REF1: MFX:USER:MCC:EPHOT:REF1
    - REF2: MFX:USER:MCC:EPHOT:REF2
    - SET1: MFX:USER:MCC:EPHOT:SET1
    - SET2: MFX:USER:MCC:EPHOT:SET2

    Energy Units:
    - All energies in eV
    - Typical range: 4000-25000 eV
    - Values sent to machine control system (MCC)

    Writing Methods:
    - Uses caput via os.system()
    - Synchronous execution
    - Logs each write operation

    Safety:
    - No limits enforced at this level
    - MCC enforces undulator limits
    - Large changes may affect beam

    Warnings
    --------
    Large energy changes can affect beam position and focus.
    Verify beamline optics after significant energy moves.

    Examples
    --------
    Set all PVs to same energy:
    >>> vput = EnergyPut()
    >>> vput.all(9000)

    Set individual setpoint:
    >>> vput.vernier(9010)

    Set reference energy:
    >>> vput.vernier_ref(9000)

    See Also
    --------
    EnergyGet : Read vernier energy values
    """

    def __init__(self):
        """
        Initialize EnergyPut interface.

        Creates DCCM device instance for monochromator control.
        """
        from mfx.dccm import DCCM
        self.dccm = DCCM(name='DCCM')

    def all(self, energy):
        """
        Set all vernier PVs to same energy.

        Sets REF1, REF2, SET1, and SET2 to the specified energy value.
        Useful for initial setup or resynchronizing all PVs.

        Parameters
        ----------
        energy : float
            Target energy in eV

        Returns
        -------
        None

        Notes
        -----
        Use Cases:
        - Initial system setup
        - Reset after experiments
        - Synchronize all PVs
        - Calibration preparation

        This ensures all vernier PVs are consistent, which is required
        for some control modes and simplifies troubleshooting.

        Warnings
        --------
        This will change both reference and setpoint values. Use with
        caution during active experiments.

        Examples
        --------
        Initialize all PVs to 9 keV:
        >>> vput = EnergyPut()
        >>> vput.all(9000)

        Reset to nominal energy:
        >>> nominal_energy = 9000
        >>> vput.all(nominal_energy)

        See Also
        --------
        EnergyGet.all : Read all PV values
        """
        logger.info(f"Setting all vernier PVs to {energy} eV")
        self.vernier_ref(energy)
        self.k_ref(energy)
        self.vernier(energy)
        self.k_energy(energy)

    def vernier_ref(self, energy):
        """
        Set reference energy 1 (REF1).

        Parameters
        ----------
        energy : float
            Target reference energy in eV

        Returns
        -------
        None

        Notes
        -----
        Reference energies typically set during beamline setup or
        calibration. REF1 serves as primary calibration reference.

        PV: MFX:USER:MCC:EPHOT:REF1

        Typical Use:
        - Initial calibration
        - After major beamline changes
        - Establishing energy baseline

        Examples
        --------
        Set primary reference to 9 keV:
        >>> vput = EnergyPut()
        >>> vput.vernier_ref(9000)

        See Also
        --------
        k_ref : Set second reference
        EnergyGet.vernier_ref : Read reference value
        """
        logger.info(f"Setting vernier_ref to {energy} eV")
        os.system(f"caput MFX:USER:MCC:EPHOT:REF1 {energy}")

    def k_ref(self, energy):
        """
        Set k reference energy (REF2).

        Parameters
        ----------
        energy : float
            Target second reference energy in eV

        Returns
        -------
        None

        Notes
        ----- Secondary reference for dual-energy mode or backup calibration.
        REF2 provides independent calibration for K-based control.

        PV: MFX:USER:MCC:EPHOT:REF2

        Examples
        --------
        Set secondary reference:
        >>> vput = EnergyPut()
        >>> vput.k_ref(9000)

        See Also
        --------
        vernier_ref : Set primary reference
        EnergyGet.k_ref : Read reference value
        """
        logger.info(f"Setting k_ref to {energy} eV")
        os.system(f"caput MFX:USER:MCC:EPHOT:REF2 {energy}")

    def vernier(self, energy):
        """
        Set vernier setpoint energy (SET1).

        Parameters
        ----------
        energy : float
            Target setpoint energy in eV

        Returns
        -------
        None

        Notes
        -----
        Primary setpoint for energy control. MCC adjusts undulator K
        parameter to match this value.

        PV: MFX:USER:MCC:EPHOT:SET1

        Energy Changes:
        - Take effect within ~1 second
        - Actual energy depends on undulator response
        - Small changes maintain beam position

        Typical Use:
        - Fine energy tuning
        - Energy scans
        - Resonance optimization

        Examples
        --------
        Request 9 keV:
        >>> vput = EnergyPut()
        >>> vput.vernier(9000)

        Fine adjustment (+50 eV):
        >>> current = 9000
        >>> vput.vernier(current + 50)

        See Also
        --------
        k_energy : Set second setpoint
        EnergyGet.vernier : Read setpoint value
        """
        logger.info(f"Setting vernier to {energy} eV")
        os.system(f"caput MFX:USER:MCC:EPHOT:SET1 {energy}")

    def k_energy(self, energy):
        """
        Set k setpoint energy (SET2).

        Parameters
        ----------
        energy : float
            Target second setpoint energy in eV

        Returns
        -------
        None

        Notes
        -----
        Secondary setpoint for K parameter control. Provides independent
        energy tuning useful for specialized control schemes.

        PV: MFX:USER:MCC:EPHOT:SET2

        Applications:
        - Dual-energy experiments
        - Independent undulator tuning
        - Alternative control modes

        Examples
        --------
        Set second setpoint:
        >>> vput = EnergyPut()
        >>> vput.k_energy(9010)

        See Also
        --------
        vernier : Set primary setpoint
        EnergyGet.k_energy : Read setpoint value
        """
        logger.info(f"Setting k_energy to {energy} eV")
        os.system(f"caput MFX:USER:MCC:EPHOT:SET2 {energy}")

    def mono(self, energy):
        """
        Set DCCM monochromator energy.

        Parameters
        ----------
        energy : float
            Target energy in eV

        Returns
        -------
        None

        Notes
        -----
        Sets DCCM energy by moving crystal Bragg angle. Energy
        converted from eV to keV for DCCM interface.

        Large energy changes may require:
        - Beam position adjustments
        - Focus optimization
        - Harmonic rejection verification

        Warnings
        --------
        Moving DCCM changes beam position and may require
        reoptimization of downstream optics.

        Examples
        --------
        Set DCCM to 9 keV:
        >>> vput = EnergyPut()
        >>> vput.mono(9000)

        See Also
        --------
        DCCM : Monochromator device class
        EnergyGet.mono : Read DCCM energy
        """
        logger.info(f"Setting DCCM to {energy} eV")
        energy_kev = energy / 1000.0
        self.dccm.energy.move(energy_kev)

# Convenience instance for direct import
get = EnergyGet()
put = EnergyPut()

def get_energy(pv_list: list = ['vr', 'kr', 'v', 'k', 'd']) -> float:
    """
    Get current vernier energy from specified PV.

    Parameters
    ----------
    pv : str, optional
        PV name: 'vernier_ref', 'k_ref', 'vernier', or 'k_energy' (default: 'all')

    Returns
    -------
    float
        Energy in eV

    Examples
    --------
    >>> energy = get_energy('vernier')
    >>> print(f"Current energy: {energy} eV")
    """
    if 'vr' in [pv.lower() for pv in pv_list]:
        get.vernier_ref()
    if 'kr' in [pv.lower() for pv in pv_list]:
        get.k_ref()
    if 'v' in [pv.lower() for pv in pv_list]:
        get.vernier()
    if 'k' in [pv.lower() for pv in pv_list]:
        get.k_energy()
    if 'd' in [pv.lower() for pv in pv_list]:
        get.mono()
    if 'all' in [pv.lower() for pv in pv_list]:
        get.all()
    if not pv_list:
        logger.error(f"Unknown PV: {pv_list}. Use 'vr', 'kr', 'v', 'k', 'd', or 'all'")
        raise ValueError("Invalid PV name")

def set_energy(energy: float, pv_list: list = []):
    """
    Set vernier energy to specified value.

    Parameters
    ----------
    energy : float
        Target energy in eV
    pv : str, optional
        PV name: 'vernier_ref', 'k_ref', 'vernier', or 'k_energy' (default: 'vernier')

    Returns
    -------
    None

    Examples
    --------
    >>> set_energy(9000)  # Set to 9 keV
    >>> set_energy(9000, pv='k_energy')  # Set SET2 PV

    See Also
    --------
    get_energy : Read vernier energy
    """
    if 'vr' in [pv.lower() for pv in pv_list]:
        put.vernier_ref(energy)
    if 'kr' in [pv.lower() for pv in pv_list]:
        put.k_ref(energy)
    if 'v' in [pv.lower() for pv in pv_list]:
        put.vernier(energy)
    if 'k' in [pv.lower() for pv in pv_list]:
        put.k_energy(energy)
    if 'd' in [pv.lower() for pv in pv_list]:
        put.mono(energy)
    if 'all' in [pv.lower() for pv in pv_list]:
        put.all(energy)
    if not pv_list:
        logger.error(f"Unknown PV: {pv_list}. Use 'vr', 'kr', 'v', 'k', 'd', or 'all'")
        raise ValueError("Invalid PV name")