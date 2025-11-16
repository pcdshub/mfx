"""Vernier energy control and calibration utilities for MFX beamline."""

import os
import logging

logger = logging.getLogger(__name__)


class Vernier:
    """
    Vernier energy control interface.

    Provides fine energy adjustments via undulator K parameter changes.
    The vernier system allows small energy adjustments (typically ±100 eV)
    without moving the main monochromator, maintaining beam position and focus.

    The vernier uses two PV sets:
    - REF (Reference): Stores calibration reference energies
    - SET (Setpoint): Stores requested energies for undulator adjustment

    Components
    ----------
    get : VernierGet
        Read current vernier energies
    put : VernierPut
        Set vernier energies
    output : VernierOutput
        Analysis and visualization tools

    Notes
    -----
    Vernier System:
    - Small energy changes via undulator K
    - Maintains beam trajectory
    - Faster than full monochromator moves
    - Typical range: ±100 eV around nominal

    Energy PVs:
    - REF1/REF2: Reference energies (eV)
    - SET1/SET2: Setpoint energies (eV)

    MCC Integration:
    - MCC (Machine Control Center) receives requests
    - Adjusts undulator gap and phase
    - Provides feedback on completion

    Typical Applications:
    - EXAFS scans
    - Energy calibration
    - Fast energy switching
    - Maintaining beam position during scans

    Examples
    --------
    Create vernier controller:
    >>> vernier = Vernier()

    Read current energy:
    >>> energy = vernier.get.set1()
    >>> print(f"Current energy: {energy} eV")

    Set new energy:
    >>> vernier.put.set1(9000)  # Request 9000 eV

    Set all PVs:
    >>> vernier.put.all(9000)  # Set all to 9000 eV

    Analyze vernier scan:
    >>> vernier.output.scan(user='myuser', exp='mfxls1234', run=123)

    See Also
    --------
    VernierCalibration : Automated calibration procedures
    DCCMEnergyWithVernier : DCCM with vernier integration
    """

    def __init__(self):
        """Initialize Vernier controller with get, put, and output interfaces."""
        self.get = VernierGet()
        self.put = VernierPut()
        self.output = VernierOutput()


class VernierGet:
    """
    Read vernier energy values from EPICS PVs.

    Provides methods to read current vernier energy settings
    from both reference and setpoint PVs.

    Methods
    -------
    ref1() : float
        Read reference energy 1
    ref2() : float
        Read reference energy 2
    set1() : float
        Read setpoint energy 1
    set2() : float
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
    >>> vget = VernierGet()
    >>> ref1 = vget.ref1()
    >>> print(f"Reference 1: {ref1} eV")

    >>> set1 = vget.set1()
    >>> print(f"Setpoint 1: {set1} eV")
    """

    def __init__(self):
        """Initialize VernierGet interface."""
        pass

    def all(self) -> float:
        """
        Get all vernier PVs to same energy.

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
        os.system(f'caget MFX:USER:MCC:EPHOT:REF1')
        os.system(f'caget MFX:USER:MCC:EPHOT:REF2')
        os.system(f'caget MFX:USER:MCC:EPHOT:SET1')
        os.system(f'caget MFX:USER:MCC:EPHOT:SET2')

    def ref1(self) -> float:
        """
        Read reference energy 1.

        Returns
        -------
        float
            Reference energy 1 in eV

        Notes
        -----
        Reference energies store calibration values.
        Typically set during initial beamline setup.

        Examples
        --------
        >>> vget = VernierGet()
        >>> ref1 = vget.ref1()
        """
        os.system('caget MFX:USER:MCC:EPHOT:REF1')
        energy = float(
            os.popen("caget MFX:USER:MCC:EPHOT:REF1 | awk '{print $2}'")
            .read()
            .strip()
        )
        return energy

    def ref2(self) -> float:
        """
        Read reference energy 2.

        Returns
        -------
        float
            Reference energy 2 in eV

        Notes
        -----
        Second reference energy for dual-energy applications
        or backup calibration.

        Examples
        --------
        >>> vget = VernierGet()
        >>> ref2 = vget.ref2()
        """
        os.system('caget MFX:USER:MCC:EPHOT:REF2')
        energy = float(
            os.popen("caget MFX:USER:MCC:EPHOT:REF2 | awk '{print $2}'")
            .read()
            .strip()
        )
        return energy

    def set1(self) -> float:
        """
        Read setpoint energy 1.

        Returns
        -------
        float
            Setpoint energy 1 in eV

        Notes
        -----
        Setpoint energies are the requested energies.
        MCC uses these to calculate undulator parameters.

        Primary setpoint for most operations.

        Examples
        --------
        >>> vget = VernierGet()
        >>> set1 = vget.set1()
        >>> print(f"Requested energy: {set1} eV")
        """
        os.system('caget MFX:USER:MCC:EPHOT:SET1')
        energy = float(
            os.popen("caget MFX:USER:MCC:EPHOT:SET1 | awk '{print $2}'")
            .read()
            .strip()
        )
        return energy

    def set2(self) -> float:
        """
        Read setpoint energy 2.

        Returns
        -------
        float
            Setpoint energy 2 in eV

        Notes
        -----
        Secondary setpoint for:
        - Dual-energy experiments
        - K parameter control
        - Independent undulator adjustment

        Examples
        --------
        >>> vget = VernierGet()
        >>> set2 = vget.set2()
        """
        os.system('caget MFX:USER:MCC:EPHOT:SET2')
        energy = float(
            os.popen("caget MFX:USER:MCC:EPHOT:SET2 | awk '{print $2}'")
            .read()
            .strip()
        )
        return energy


class VernierPut:
    """
    Set vernier energy values via EPICS PVs.

    Provides methods to write vernier energy setpoints
    to control undulator K parameter.

    Methods
    -------
    all(energy) : None
        Set all vernier PVs to same energy
    ref1(energy) : None
        Set reference energy 1
    ref2(energy) : None
        Set reference energy 2
    set1(energy) : None
        Set setpoint energy 1
    set2(energy) : None
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
    >>> vput = VernierPut()
    >>> vput.set1(9000)  # Request 9 keV

    >>> vput.all(8500)  # Set all PVs to 8.5 keV
    """

    def __init__(self):
        """Initialize VernierPut interface."""
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
        >>> vput = VernierPut()
        >>> vput.all(9000)

        Reset to nominal energy:
        >>> vput.all(8000)
        """
        os.system(f'caput MFX:USER:MCC:EPHOT:REF1 {energy}')
        os.system(f'caput MFX:USER:MCC:EPHOT:REF2 {energy}')
        os.system(f'caput MFX:USER:MCC:EPHOT:SET1 {energy}')
        os.system(f'caput MFX:USER:MCC:EPHOT:SET2 {energy}')
        logger.info(f"Set all vernier PVs to {energy} eV")

    def ref1(self, energy: float):
        """
        Set reference energy 1.

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
        >>> vput = VernierPut()
        >>> vput.ref1(9000)
        """
        os.system(f'caput MFX:USER:MCC:EPHOT:REF1 {energy}')
        logger.info(f"Set REF1 to {energy} eV")

    def ref2(self, energy: float):
        """
        Set reference energy 2.

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
        >>> vput = VernierPut()
        >>> vput.ref2(9000)
        """
        os.system(f'caput MFX:USER:MCC:EPHOT:REF2 {energy}')
        logger.info(f"Set REF2 to {energy} eV")

    def set1(self, energy: float):
        """
        Set setpoint energy 1.

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
        >>> vput = VernierPut()
        >>> vput.set1(9000)

        Fine adjustment:
        >>> vput.set1(9050)  # +50 eV
        """
        os.system(f'caput MFX:USER:MCC:EPHOT:SET1 {energy}')
        logger.info(f"Set SET1 to {energy} eV")

    def set2(self, energy: float):
        """
        Set setpoint energy 2.

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
        >>> vput = VernierPut()
        >>> vput.set2(8500)
        """
        os.system(f'caput MFX:USER:MCC:EPHOT:SET2 {energy}')
        logger.info(f"Set SET2 to {energy} eV")


class VernierOutput:
    """
    Analysis and visualization tools for vernier scans.

    Provides methods to analyze vernier calibration data and
    generate diagnostic plots showing FEE spectrometer response.

    Methods
    -------
    fee_spec_list(user, facility, exp, run_list) : None
        Plot FEE spectrometer data from multiple runs
    series(user, facility, run_type, exp, run, energy, step, num) : None
        Analyze energy calibration series
    scan(user, facility, run_type, exp, run) : None
        Analyze single vernier scan

    Notes
    -----
    Analysis Scripts:
    - Run on S3DF or NERSC computing facilities
    - Process HDF5 data files
    - Generate matplotlib plots
    - Save results to experiment directory

    FEE Spectrometer:
    - Monitors actual photon energy
    - Independent verification of vernier
    - Used for calibration validation

    Requires:
    - SSH access to computing facility
    - Valid experiment data
    - Proper file permissions

    Examples
    --------
    Analyze single scan:
    >>> vout = VernierOutput()
    >>> vout.scan(user='myuser', exp='mfxls1234', run=123)

    Analyze calibration series:
    >>> vout.series(
    ...     user='myuser',
    ...     exp='mfxls1234',
    ...     run=100,
    ...     energy=9000,
    ...     step=10,
    ...     num=11
    ... )
    """

    def __init__(self):
        """Initialize VernierOutput analysis interface."""
        pass

    def fee_spec_list(
            self,
            user: str,
            facility: str = 'S3DF',
            exp: str = None,
            run_list: list = None):
        """
        Plot FEE spectrometer data from multiple runs.

        Generates overlay plots of FEE spectrometer signals
        from a list of runs for comparison and analysis.

        Parameters
        ----------
        user : str
            Username for SSH and computing facility access
        facility : str, optional
            Computing facility: 'S3DF' or 'NERSC' (default: 'S3DF')
        exp : str or None, optional
            Experiment name (e.g., 'mfxls1234')
            If None, uses current experiment
        run_list : list or None, optional
            List of run numbers to analyze
            If None, uses current run

        Returns
        -------
        None

        Notes
        -----
        Analysis Process:
        1. SSH to computing facility
        2. Load run data from HDF5 files
        3. Extract FEE spectrometer signals
        4. Generate overlay plots
        5. Save to experiment directory

        Plot Features:
        - Multiple runs overlaid
        - Color-coded by run number
        - Normalized intensities
        - Energy axis calibration

        Output Files:
        - PNG plots
        - CSV data tables
        - Analysis summary

        SSH Proxy:
        - NERSC requires active SSH proxy
        - Check with: klist
        - Renew with: krenew -b

        Examples
        --------
        Compare three runs:
        >>> vout = VernierOutput()
        >>> vout.fee_spec_list(
        ...     user='myuser',
        ...     exp='mfxls1234',
        ...     run_list=[100, 101, 102]
        ... )

        Analyze on NERSC:
        >>> vout.fee_spec_list(
        ...     user='myuser',
        ...     facility='NERSC',
        ...     run_list=[100, 101, 102]
        ... )

        See Also
        --------
        scan : Analyze single vernier scan
        series : Analyze calibration series
        """
        from mfx.db import daq
        from mfx.macros import get_exp
        import mfx.cctbx as cctbx

        logger.info("Plotting XRT-Spec Output")

        # Get experiment name
        if exp is None:
            exp = str(get_exp())

        # Get run list
        if run_list is None or len(run_list) == 0:
            run_list = [daq.run_number()]

        # Build exp:run list string
        exp_run_list = [f"{exp}:{run}" for run in run_list]
        exp_run_str = " ".join(exp_run_list)

        # Handle facility selection
        facility = facility.upper()
        if facility == 'NERSC':
            # Check SSH proxy
            logger.warning("Have you renewed your token with sshproxy today?")
            token = input("(y/n)? ")

            if token.lower() == "n":
                cctbx.sshproxy(user)

            # Run analysis on NERSC
            cmd = (
                f"ssh {user}@perlmutter-p1.nersc.gov "
                f"'/global/cfs/cdirs/lcls/mfxopr/scripts/hsd/"
                f"Fee_Spec_List_NERSC.sh {exp_run_str}'"
            )
            logger.info(f"Executing: {cmd}")
            os.system(cmd)

        elif facility == 'S3DF':
            # Run analysis on S3DF
            cmd = (
                f"ssh {user}@s3dflogin.slac.stanford.edu "
                f"'/sdf/group/lcls/ds/tools/mfx/scripts/"
                f"Fee_Spec_List_S3DF.sh {exp_run_str}'"
            )
            logger.info(f"Executing: {cmd}")
            os.system(cmd)

        else:
            logger.error(f"Unknown facility: {facility}. Use 'S3DF' or 'NERSC'")

    def series(
            self,
            user: str,
            facility: str = 'S3DF',
            run_type: str = 'series',
            exp: str = None,
            run: int = None,
            energy: float = None,
            step: float = None,
            num: int = None):
        """
        Analyze vernier energy calibration series.

        Processes a series of runs taken at different energies
        to generate calibration curves and diagnostic plots.

        Parameters
        ----------
        user : str
            Username for computing facility access
        facility : str, optional
            'S3DF' or 'NERSC' (default: 'S3DF')
        run_type : str, optional
            Analysis type, must be 'series' (default: 'series')
        exp : str or None, optional
            Experiment name
            If None, uses current experiment
        run : int or None, optional
            First run number in series
            If None, uses current run
        energy : float or None, optional
            Starting energy in eV
            Required for series analysis
        step : float or None, optional
            Energy step size in eV
            Required for series analysis
        num : int or None, optional
            Number of runs in series
            Required for series analysis

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If run_type is not 'series'

        Notes
        -----
        Series Analysis:
        - Expects sequential runs at different energies
        - Energies follow: E₀, E₀+step, E₀+2×step, ..., E₀+(num-1)×step
        - Generates calibration curve
        - Plots vernier response vs. energy

        Required Parameters:
        - energy: Starting energy
        - step: Energy increment
        - num: Number of points

        Output:
        - Calibration curves
        - Residual plots
        - FEE spectrometer overlay
        - Statistical analysis

        Analysis Scripts:
        - S3DF: /sdf/group/lcls/ds/tools/mfx/scripts/Vernier_Series_S3DF.sh
        - NERSC: /global/cfs/cdirs/lcls/mfxopr/scripts/hsd/Vernier_Series_NERSC.sh

        Examples
        --------
        Analyze 11-point series starting at 9000 eV with 10 eV steps:
        >>> vout = VernierOutput()
        >>> vout.series(
        ...     user='myuser',
        ...     exp='mfxls1234',
        ...     run=100,
        ...     energy=9000,
        ...     step=10,
        ...     num=11
        ... )

        See Also
        --------
        scan : Analyze single scan
        fee_spec_list : Plot multiple FEE spectrometer runs
        """
        from mfx.db import daq
        from mfx.macros import get_exp
        import mfx.cctbx as cctbx

        # Validate run type
        if run_type != 'series':
            logger.error("run_type must be 'series' for this method")
            raise ValueError("Invalid run_type")

        logger.info("Plotting XRT-Spec Output for calibration series")

        # Get experiment name
        if exp is None:
            exp = str(get_exp())

        # Get run number
        if run is None:
            run = daq.run_number()

        # Validate required parameters
        if energy is None or step is None or num is None:
            logger.error(
                "For series analysis, must specify: energy, step, and num"
            )
            raise ValueError("Missing required parameters")

        # Handle facility selection
        facility = facility.upper()
        if facility == 'NERSC':
            # Check SSH proxy
            logger.warning("Have you renewed your token with sshproxy today?")
            token = input("(y/n)? ")

            if token.lower() == "n":
                cctbx.sshproxy(user)

            # Run analysis on NERSC
            cmd = (
                f"ssh {user}@perlmutter-p1.nersc.gov "
                f"'/global/cfs/cdirs/lcls/mfxopr/scripts/hsd/"
                f"Vernier_Series_NERSC.sh {exp} {run} {energy} {step} {num}'"
            )
            logger.info(f"Executing: {cmd}")
            os.system(cmd)

        elif facility == 'S3DF':
            # Run analysis on S3DF
            cmd = (
                f"ssh {user}@s3dflogin.slac.stanford.edu "
                f"'/sdf/group/lcls/ds/tools/mfx/scripts/"
                f"Vernier_Series_S3DF.sh {exp} {run} {energy} {step} {num}'"
            )
            logger.info(f"Executing: {cmd}")
            os.system(cmd)

        else:
            logger.error(f"Unknown facility: {facility}. Use 'S3DF' or 'NERSC'")

    def scan(
            self,
            user: str,
            facility: str = 'S3DF',
            run_type: str = 'scan',
            exp: str = None,
            run: int = None):
        """
        Analyze single vernier scan.

        Processes a single run containing vernier scan data
        to generate diagnostic plots and statistics.

        Parameters
        ----------
        user : str
            Username for computing facility access
        facility : str, optional
            'S3DF' or 'NERSC' (default: 'S3DF')
        run_type : str, optional
            Analysis type, must be 'scan' (default: 'scan')
        exp : str or None, optional
            Experiment name
            If None, uses current experiment
        run : int or None, optional
            Run number to analyze
            If None, uses current run

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If run_type is not 'scan'

        Notes
        -----
        Scan Analysis:
        - Single run with energy scan
        - Plots vernier response
        - Shows FEE spectrometer data
        - Calculates statistics

        Output:
        - Energy vs. intensity plots
        - FEE spectrometer spectrum
        - Statistical summary
        - Diagnostic information

        Analysis Scripts:
        - S3DF: /sdf/group/lcls/ds/tools/mfx/scripts/Vernier_Scan_S3DF.sh
        - NERSC: /global/cfs/cdirs/lcls/mfxopr/scripts/hsd/Vernier_Scan_NERSC.sh

        Examples
        --------
        Analyze current run:
        >>> vout = VernierOutput()
        >>> vout.scan(user='myuser')

        Analyze specific run:
        >>> vout.scan(user='myuser', exp='mfxls1234', run=123)

        Analyze on NERSC:
        >>> vout.scan(user='myuser', facility='NERSC', run=123)

        See Also
        --------
        series : Analyze calibration series
        fee_spec_list : Compare multiple runs
        """
        from mfx.db import daq
        from mfx.macros import get_exp
        import mfx.cctbx as cctbx

        # Validate run type
        if run_type != 'scan':
            logger.error("run_type must be 'scan' for this method")
            raise ValueError("Invalid run_type")

        logger.info("Plotting XRT-Spec Output for single scan")

        # Get experiment name
        if exp is None:
            exp = str(get_exp())

        # Get run number
        if run is None:
            run = daq.run_number()

        # Handle facility selection
        facility = facility.upper()
        if facility == 'NERSC':
            # Check SSH proxy
            logger.warning("Have you renewed your token with sshproxy today?")
            token = input("(y/n)? ")

            if token.lower() == "n":
                cctbx.sshproxy(user)

            # Run analysis on NERSC
            cmd = (
                f"ssh {user}@perlmutter-p1.nersc.gov "
                f"'/global/cfs/cdirs/lcls/mfxopr/scripts/hsd/"
                f"Vernier_Scan_NERSC.sh {exp} {run}'"
            )
            logger.info(f"Executing: {cmd}")
            os.system(cmd)

        elif facility == 'S3DF':
            # Run analysis on S3DF
            cmd = (
                f"ssh {user}@s3dflogin.slac.stanford.edu "
                f"'/sdf/group/lcls/ds/tools/mfx/scripts/"
                f"Vernier_Scan_S3DF.sh {exp} {run}'"
            )
            logger.info(f"Executing: {cmd}")
            os.system(cmd)

        else:
            logger.error(f"Unknown facility: {facility}. Use 'S3DF' or 'NERSC'")


# Convenience instance for direct import
vernier = Vernier()


def get_vernier_energy(pv: str = 'all') -> float:
    """
    Get current vernier energy from specified PV.

    Parameters
    ----------
    pv : str, optional
        PV name: 'ref1', 'ref2', 'set1', or 'set2' (default: 'set1')

    Returns
    -------
    float
        Energy in eV

    Examples
    --------
    >>> energy = get_vernier_energy('set1')
    >>> print(f"Current energy: {energy} eV")

    See Also
    --------
    set_vernier_energy : Set vernier energy
    """
    pv = pv.lower()
    if pv == 'ref1':
        return vernier.get.ref1()
    elif pv == 'ref2':
        return vernier.get.ref2()
    elif pv == 'set1':
        return vernier.get.set1()
    elif pv == 'set2':
        return vernier.get.set2()
    elif pv == 'all':
        return vernier.get.all()
    else:
        logger.error(f"Unknown PV: {pv}. Use 'ref1', 'ref2', 'set1', or 'set2'")
        raise ValueError("Invalid PV name")

def set_vernier_energy(energy: float, pv: str = 'all'):
    """
    Set vernier energy to specified value.

    Parameters
    ----------
    energy : float
        Target energy in eV
    pv : str, optional
        PV name: 'ref1', 'ref2', 'set1', or 'set2' (default: 'set1')

    Returns
    -------
    None

    Examples
    --------
    >>> set_vernier_energy(9000)  # Set to 9 keV
    >>> set_vernier_energy(9000, pv='set2')  # Set SET2 PV

    See Also
    --------
    get_vernier_energy : Read vernier energy
    """
    pv = pv.lower()
    if pv == 'ref1':
        vernier.put.ref1(energy)
    elif pv == 'ref2':
        vernier.put.ref2(energy)
    elif pv == 'set1':
        vernier.put.set1(energy)
    elif pv == 'set2':
        vernier.put.set2(energy)
    elif pv == 'all':
        vernier.put.all(energy)
    else:
        logger.error(
            f"Unknown PV: {pv}. "
            "Use 'ref1', 'ref2', 'set1', 'set2', or 'all'"
        )
        raise ValueError("Invalid PV name")


def analyze_vernier_scan(user: str, facility: str = 'S3DF', **kwargs):
    """
    Convenience function to analyze vernier scan data.

    Parameters
    ----------
    user : str
        Username for computing facility
    facility : str, optional
        'S3DF' or 'NERSC' (default: 'S3DF')
    **kwargs
        Additional arguments passed to VernierOutput.scan()

    Returns
    -------
    None

    Examples
    --------
    >>> analyze_vernier_scan('myuser', exp='mfxls1234', run=123)

    See Also
    --------
    VernierOutput.scan : Full implementation
    """
    vernier.output.scan(user=user, facility=facility, **kwargs)


def analyze_vernier_series(
        user: str,
        facility: str = 'S3DF',
        energy: float = None,
        step: float = None,
        num: int = None,
        **kwargs):
    """
    Convenience function to analyze vernier calibration series.

    Parameters
    ----------
    user : str
        Username for computing facility
    facility : str, optional
        'S3DF' or 'NERSC' (default: 'S3DF')
    energy : float
        Starting energy in eV
    step : float
        Energy step in eV
    num : int
        Number of runs
    **kwargs
        Additional arguments passed to VernierOutput.series()

    Returns
    -------
    None

    Examples
    --------
    >>> analyze_vernier_series(
    ...     'myuser',
    ...     energy=9000,
    ...     step=10,
    ...     num=11
    ... )

    See Also
    --------
    VernierOutput.series : Full implementation
    """
    vernier.output.series(
        user=user,
        facility=facility,
        energy=energy,
        step=step,
        num=num,
        **kwargs
    )