"""Vernier energy control and calibration utilities for MFX beamline."""

import os
import logging

logger = logging.getLogger(__name__)


class EnergyGet:
    """
    Read vernier energy values from EPICS PVs.

    Provides methods to read current vernier energy settings
    from both reference and setpoint PVs.

    Methods
    -------
    vernier_ref() : float
        Read reference energy 1
    k_ref() : float
        Read reference energy 2
    vernier() : float
        Read setpoint energy 1
    k_energy() : float
        Read setpoint energy 2

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

    Reading Methods:
    - Uses caget via os.system()
    - Parses output with awk
    - Returns float value

    Examples
    --------
    >>> vget = EnergyGet()
    >>> vernier_ref = vget.vernier_ref()
    >>> print(f"Reference 1: {vernier_ref} eV")

    >>> vernier = vget.vernier()
    >>> print(f"Setpoint 1: {vernier} eV")
    """

    def __init__(self):
        """Initialize EnergyGet interface."""
        from mfx.dccm import DCCM
        self.dccm = DCCM(name='DCCM')
        pass

    def all(self) -> float:
        """
        Get all PVs energies and references.

        Convenience method to get REF1, REF2, SET1, and SET2
        value simultaneously.

        Returns
        -------
        Energy : float

        Notes
        -----
        Use Cases:
        - Initial setup
        - Reset after experiments
        - Synchronize all PVs

        This ensures all vernier PVs are consistent,
        which is required for some control modes.

        """
        logger.info(f"Get all vernier PVs in eV")
        self.vernier_ref()
        self.k_ref()
        self.vernier()
        self.k_energy()
        self.mono()

    def vernier_ref(self) -> float:
        """
        Read vernier_ref energy.

        Returns
        -------
        float
            vernier_ref energy in eV

        Notes
        -----
        Reference energies store calibration values.
        Typically set during initial beamline setup.

        Examples
        --------
        >>> vget = EnergyGet()
        >>> vernier_ref = vget.vernier_ref()
        """
        energy = float(
            os.popen("caget MFX:USER:MCC:EPHOT:REF1 | awk '{print $2}'")
            .read()
            .strip()
        )
        logger.info(f"vernier_ref: {energy} eV")
        return energy

    def k_ref(self) -> float:
        """
        Read k_ref.

        Returns
        -------
        float
            k_ref energy in eV

        Notes
        -----
        Second reference energy for dual-energy applications
        or backup calibration.

        Examples
        --------
        >>> vget = EnergyGet()
        >>> k_ref = vget.k_ref()
        """
        energy = float(
            os.popen("caget MFX:USER:MCC:EPHOT:REF2 | awk '{print $2}'")
            .read()
            .strip()
        )
        logger.info(f"k_ref: {energy} eV")
        return energy

    def vernier(self) -> float:
        """
        Read vernier energy .

        Returns
        -------
        float
            vernier energy eV

        Notes
        -----
        Setpoint energies are the requested energies.
        MCC uses these to calculate undulator parameters.

        Primary setpoint for most operations.

        Examples
        --------
        >>> vget = EnergyGet()
        >>> vernier = vget.vernier()
        >>> print(f"Requested energy: {vernier} eV")
        """
        energy = float(
            os.popen("caget MFX:USER:MCC:EPHOT:SET1 | awk '{print $2}'")
            .read()
            .strip()
        )
        logger.info(f"vernier: {energy} eV")
        return energy

    def k_energy(self) -> float:
        """
        Read k_energy.

        Returns
        -------
        float
            k_energy in eV

        Notes
        -----
        Secondary setpoint for:
        - Dual-energy experiments
        - K parameter control
        - Independent undulator adjustment

        Examples
        --------
        >>> vget = EnergyGet()
        >>> k_energy = vget.k_energy()
        """
        energy = float(
            os.popen("caget MFX:USER:MCC:EPHOT:SET2 | awk '{print $2}'")
            .read()
            .strip()
        )
        logger.info(f"k_energy: {energy} eV")
        return energy

    def mono(self) -> float:
        """
        Read dccm energy.

        Returns
        -------
        float
            dccm energy in eV

        Notes
        -----
        Reference energies store calibration values.
        Typically set during initial beamline setup.

        Examples
        --------
        >>> vget = EnergyGet()
        >>> mono = vget.mono()
        """
        energy = round(self.dccm.energy() * 1000, 1)
        logger.info(f"dccm: {energy} eV")
        return energy


class EnergyPut:
    """
    Set vernier energy values via EPICS PVs.

    Provides methods to write vernier energy setpoints
    to control undulator K parameter.

    Methods
    -------
    all(energy) : None
        Set all vernier PVs to same energy
    vernier_ref(energy) : None
        Set reference energy 1
    k_ref(energy) : None
        Set reference energy 2
    vernier(energy) : None
        Set setpoint energy 1
    k_energy(energy) : None
        Set setpoint energy 2

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

    Writing Methods:
    - Uses caput via os.system()
    - Non-blocking by default
    - MCC processes requests asynchronously

    Safety:
    - No range checking in this class
    - MCC enforces machine limits
    - Invalid requests logged by MCC

    Examples
    --------
    >>> vput = EnergyPut()
    >>> vput.vernier(9000)  # Request 9 keV

    >>> vput.all(8500)  # Set all PVs to 8.5 keV
    """

    def __init__(self):
        """Initialize EnergyPut interface."""
        from mfx.dccm import DCCM
        self.dccm = DCCM(name='DCCM')
        pass

    def all(self, energy: float):
        """
        Set all vernier PVs to same energy.

        Convenience method to set REF1, REF2, SET1, and SET2
        to the same value simultaneously.

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
        - Initial setup
        - Reset after experiments
        - Synchronize all PVs

        This ensures all vernier PVs are consistent,
        which is required for some control modes.

        Examples
        --------
        Initialize all to 9 keV:
        >>> vput = EnergyPut()
        >>> vput.all(9000)

        Reset to nominal energy:
        >>> vput.all(8000)
        """
        logger.info(f"Setting all energy PVs to {energy} eV")
        self.vernier_ref(energy)
        self.k_ref(energy)
        self.vernier(energy)
        self.k_energy(energy)
        self.mono(energy)

    def vernier_ref(self, energy: float):
        """
        Set vernier_ref.

        Parameters
        ----------
        energy : float
            Reference energy in eV

        Returns
        -------
        None

        Notes
        -----
        Reference energies typically set during calibration.
        Changes persist across sessions.

        Examples
        --------
        >>> vput = EnergyPut()
        >>> vput.vernier_ref(9000)
        """
        os.system(f'caput MFX:USER:MCC:EPHOT:REF1 {energy}')
        logger.info(f"Set vernier_ref to {energy} eV")

    def k_ref(self, energy: float):
        """
        Set k_ref.

        Parameters
        ----------
        energy : float
            Reference energy in eV

        Returns
        -------
        None

        Notes
        -----
        Secondary reference for dual-energy mode
        or calibration backup.

        Examples
        --------
        >>> vput = EnergyPut()
        >>> vput.k_ref(9000)
        """
        os.system(f'caput MFX:USER:MCC:EPHOT:REF2 {energy}')
        logger.info(f"Set k_ref to {energy} eV")

    def vernier(self, energy: float):
        """
        Set vernier energy .

        Parameters
        ----------
        energy : float
            Setpoint energy in eV

        Returns
        -------
        None

        Notes
        -----
        Primary setpoint for energy requests.
        MCC adjusts undulator to match this value.

        Changes take effect within ~1 second.
        Actual energy depends on undulator response.

        Examples
        --------
        Request 9 keV:
        >>> vput = EnergyPut()
        >>> vput.vernier(9000)

        Fine adjustment:
        >>> vput.vernier(9050)  # +50 eV
        """
        os.system(f'caput MFX:USER:MCC:EPHOT:SET1 {energy}')
        logger.info(f"Set vernier to {energy} eV")

    def k_energy(self, energy: float):
        """
        Set k_energy.

        Parameters
        ----------
        energy : float
            Setpoint energy in eV

        Returns
        -------
        None

        Notes
        -----
        Secondary setpoint for:
        - K parameter control
        - Independent undulator tuning
        - Dual-energy experiments

        Examples
        --------
        >>> vput = EnergyPut()
        >>> vput.k_energy(8500)
        """
        os.system(f'caput MFX:USER:MCC:EPHOT:SET2 {energy}')
        logger.info(f"Set k_energy to {energy} eV")

    def mono(self, energy: float):
        """
        Set dccm energy.

        Parameters
        ----------
        energy : float
            Setpoint energy in eV

        Returns
        -------
        None

        Notes
        -----
        Primary setpoint for energy requests.
        MCC adjusts undulator to match this value.

        Changes take effect within ~1 second.
        Actual energy depends on undulator response.

        Examples
        --------
        Request 9 keV:
        >>> vput = EnergyPut()
        >>> vput.mono(9000)

        Fine adjustment:
        >>> vput.mono(9050)  # +50 eV
        """
        self.dccm.energy(energy/1000)
        logger.info(f"Set vernier to {energy} eV")

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