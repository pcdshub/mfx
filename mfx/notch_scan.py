"""Notch scan utilities for energy-dependent measurements at MFX beamline."""

import logging
from time import sleep

from pcdsdevices.epics_motor import BeckhoffAxis
from epics import caput

logger = logging.getLogger(__name__)


class NotchScan:
    """
    Energy scan controller for DCCM notch filter measurements.

    Performs automated scans through discrete energy points while
    collecting data. Useful for:
    - Resonant scattering studies
    - Absorption edge mapping
    - Energy-dependent diffraction
    - Filter transmission measurements

    The scan moves the DCCM (Double Crystal Cut Monochromator) through
    specified energies and collects data at each point.

    Components
    ----------
    th1 : BeckhoffAxis
        Upstream crystal Bragg angle motor
    th2 : BeckhoffAxis
        Downstream crystal Bragg angle motor
    tx : BeckhoffAxis
        DCCM translation X motor

    Attributes
    ----------
    tab_component_names : bool
        Enable tab completion for motors

    Notes
    -----
    DCCM Configuration:
    - Crystal: Silicon (111)
    - D-spacing: 3.136 Å
    - Bragg angle range: ~5° to 30°
    - Energy range: ~4 keV to 25 keV

    Energy-to-Angle Conversion:
    Uses Bragg's law via determine_dccm_bragg() function.

    Typical Scan Parameters:
    - Energy step: 5-50 eV
    - Run length: 10-120 seconds per point
    - Total points: 5-100 depending on range

    Examples
    --------
    Create notch scan controller:
    >>> notch = NotchScan()

    Perform energy scan:
    >>> notch.series(
    ...     energy_scan_start_eV=7100,
    ...     energy_scan_end_eV=7200,
    ...     energy_scan_steps=20,
    ...     run_length=30,
    ...     record=True
    ... )

    Set DCCM to specific energy:
    >>> notch.set_energy(7112)  # Fe K-edge

    See Also
    --------
    autorun : Automated data collection
    determine_dccm_bragg : Energy to Bragg angle conversion
    """

    tab_component_names = True

    def __init__(self):
        """
        Initialize NotchScan controller.

        Creates motor objects for DCCM control:
        - th1: Upstream crystal angle
        - th2: Downstream crystal angle
        - tx: Translation stage
        """
        # Bragg angle motors
        self.th1 = BeckhoffAxis("SP1L0:DCCM:MMS:TH1", name='th1')
        self.th2 = BeckhoffAxis("SP1L0:DCCM:MMS:TH2", name='th2')
        # Translation motor
        self.tx = BeckhoffAxis("SP1L0:DCCM:MMS:TX", name='tx')

    def set_energy(self, energy: float) -> bool:
        """
        Set DCCM to specific photon energy.

        Calculates required Bragg angle and moves both crystals
        to select the requested energy.

        Parameters
        ----------
        energy : float
            Target photon energy in eV
            Typical range: 4000-25000 eV

        Returns
        -------
        bool
            True if move completed successfully
            False if timeout or motion error occurred

        Raises
        ------
        None
            Errors are logged but not raised

        Notes
        -----
        Motion Sequence:
        1. Calculate Bragg angle from energy
        2. Move th1 (non-blocking)
        3. Move th2 (blocking)
        4. Wait for both to reach position
        5. Verify positions (±0.01°)

        Timeout:
        - 30 seconds maximum
        - Prevents hanging on stuck motors
        - Returns False on timeout

        Position Tolerance:
        - 0.01° (about 1 eV at 9 keV)
        - Both crystals must be within tolerance

        Energy-to-Angle Conversion:
        Uses determine_dccm_bragg() which implements:
        θ = arcsin(12.39842 / (2 × d × E))
        where d = 3.136 Å for Si(111)

        Examples
        --------
        Set to Fe K-edge:
        >>> notch = NotchScan()
        >>> success = notch.set_energy(7112)
        >>> if success:
        ...     print("Energy set successfully")

        Set to Cu K-edge:
        >>> notch.set_energy(8979)

        See Also
        --------
        determine_dccm_bragg : Energy to angle conversion
        series : Automated energy scan
        """
        from time import time
        from mfx.macros import determine_dccm_bragg

        start_time = time()
        timeout = 30.0  # seconds
        tolerance = 0.01  # degrees

        # Calculate required Bragg angle
        bragg_angle = determine_dccm_bragg(energy)
        logger.info(f"Setting energy to {energy} eV (θ = {bragg_angle:.4f}°)")

        # Move both crystals
        self.th1.mv(bragg_angle)  # Non-blocking
        self.th2.umv(bragg_angle)  # Blocking (user move)

        # Wait for both to reach position
        status = False
        while round(self.th1(), 2) != round(bragg_angle, 2) or \
              round(self.th2(), 2) != round(bragg_angle, 2):

            sleep(0.1)

            # Check timeout
            if time() - start_time > timeout:
                logger.error(
                    f"Timeout: DCCM could not move to {energy} eV. "
                    f"th1: {self.th1():.4f}° vs {bragg_angle:.4f}°, "
                    f"th2: {self.th2():.4f}° vs {bragg_angle:.4f}°"
                )
                status = False
                break
        else:
            # Both motors reached target
            logger.warning(
                f"DCCM positioned at {energy} eV "
                f"(θ = {bragg_angle:.3f}°)"
            )
            status = True

        return status

    def series(
            self,
            energy_scan_start_eV: float,
            energy_scan_end_eV: float,
            energy_scan_steps: int,
            run_length: int = 30,
            tag: str = 'dccm',
            picker: str = None,
            inspire: bool = False,
            daq_delay: int = 5,
            record: bool = False,
            daq_num: int = 2,
            exp: str = None):
        """
        Perform automated energy scan series.

        Moves DCCM through discrete energy points while collecting
        data at each point using automated DAQ runs.

        Parameters
        ----------
        energy_scan_start_eV : float
            Starting energy in eV
        energy_scan_end_eV : float
            Ending energy in eV
        energy_scan_steps : int
            Energy step size in eV
            Actual number of points = (end - start) / step + 1
        run_length : int, optional
            Data collection time per energy point in seconds (default: 30)
        tag : str, optional
            Run tag for data organization (default: 'dccm')
        picker : str or None, optional
            Pulse picker mode: 'open', 'flip', or None
            - 'open': All pulses pass
            - 'flip': Alternating pulses (for background)
            - None: No pulse picker operation
        inspire : bool, optional
            Add inspirational quotes to elog (default: False)
        daq_delay : int, optional
            Delay between runs in seconds (default: 5)
        record : bool, optional
            Enable data recording (default: False)
        daq_num : int, optional
            DAQ version: 1 (LCLS-I) or 2 (LCLS-II) (default: 2)
        exp : str or None, optional
            Experiment name for analysis (default: None)
            If None, uses current experiment from get_exp()

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If daq_num not in [1, 2]

        Notes
        -----
        Scan Sequence:
        1. Generate energy list from start/end/step
        2. Store initial crystal positions
        3. For each energy:
           a. Move DCCM to energy
           b. Collect data for run_length seconds
           c. Post run information to elog
           d. Wait daq_delay before next point
        4. Prompt to return to initial position
        5. Optionally analyze results

        Energy List Generation:
        Uses Python range() so actual energies are:
        [start, start+step, start+2*step, ..., end]

        The final point may not exactly equal end if
        (end - start) is not divisible by step.

        Pulse Picker Modes:
        - 'open': Maximum flux, no background subtraction
        - 'flip': Background subtraction capability
        - None: Uses current picker state

        Data Analysis:
        After scan completion, prompts to:
        - Return to initial position (optional)
        - Launch analysis script (optional)
        - Specify computing facility (S3DF or NERSC)

        Station Selection:
        - daq_num=1: Station 1 (LCLS-I DAQ)
        - daq_num=2: Station 0 (LCLS-II DAQ)

        Examples
        --------
        Scan across Fe K-edge:
        >>> notch = NotchScan()
        >>> notch.series(
        ...     energy_scan_start_eV=7100,
        ...     energy_scan_end_eV=7200,
        ...     energy_scan_steps=5,
        ...     run_length=60,
        ...     record=True
        ... )

        Quick test scan:
        >>> notch.series(
        ...     energy_scan_start_eV=9000,
        ...     energy_scan_end_eV=9100,
        ...     energy_scan_steps=10,
        ...     run_length=10,
        ...     record=False
        ... )

        Scan with background subtraction:
        >>> notch.series(
        ...     energy_scan_start_eV=8950,
        ...     energy_scan_end_eV=9050,
        ...     energy_scan_steps=10,
        ...     run_length=30,
        ...     picker='flip',
        ...     record=True
        ... )

        See Also
        --------
        set_energy : Move to single energy
        output : Analyze scan results
        autorun : Data collection function
        """
        from mfx.db import pp
        from mfx.autorun import autorun
        from mfx.macros import get_exp, get_run
        from time import sleep

        # Validate DAQ number
        if daq_num == 1:
            station = 1
        elif daq_num == 2:
            station = 0
        else:
            logger.error('daq_num must be 1 (LCLS-I) or 2 (LCLS-II)')
            raise ValueError('Invalid daq_num')

        # Get experiment name
        if exp is None:
            exp = get_exp()

        # Operate pulse picker
        if picker == 'open':
            pp.open()
        elif picker == 'flip':
            pp.flipflop()

        # Get starting run number
        run_number = get_run(station=station) + 1

        # Generate energy list
        energies = list(range(
            energy_scan_start_eV,
            energy_scan_end_eV + energy_scan_steps,
            energy_scan_steps
        ))
        logger.info(f"Energy scan: {energies}")

        # Store initial positions
        original_th1 = self.th1()
        original_th2 = self.th2()

        # Perform scan
        for ev in energies:
            # Move to energy
            status = self.set_energy(ev)

            # Prepare sample label
            if status:
                sample = f'Notch scan at {ev} eV'
            else:
                sample = f'Notch scan at {ev} eV (possible error)'

            # Collect data
            autorun(
                sample=sample,
                tag=tag,
                run_length=run_length,
                record=record,
                runs=1,
                inspire=inspire,
                picker=picker,
                close=False,
                daq_num=daq_num
            )

            sleep(daq_delay)

        logger.warning(
            'Scan complete. Thank you for choosing the MFX beamline!\n'
        )
        logger.warning(
            f"ssh -Yt djr@s3dflogin "
            f"python /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/energy_calib_output.py "
            f"-f s3df -t series -e {exp} -r {run_number} -z {energy_scan_start_eV} -s "
            f"{energy_scan_steps} -n {len(energies)}"
            )
        # Prompt to return to initial position
        answer = input("Return to original Bragg angle? (y/n): ")
        if answer.lower() == "y":
            logger.info(
                f'Returning to initial position: '
                f'th1={original_th1:.4f}°, th2={original_th2:.4f}°'
            )
            self.th1.umv( original_th1)
            self.th2.umv(original_th2)
            logger.info("Returned to initial position")

        # Prompt for analysis
        answer = input("Would you like to analyze the scan? (y/n): ")
        if answer.lower() == "y":
            facility = input("Which facility? (S3DF/NERSC): ")
            if facility.upper() in ['S3DF', 'NERSC']:
                user = input("Enter username to continue: ")
                self.output(
                    user=user,
                    facility=facility,
                    exp=exp,
                    run=run_number,
                    energy=energy_scan_start_eV,
                    step=energy_scan_steps,
                    num=len(energies),
                    daq_num=daq_num)
            else:
                logger.warning(f"Unknown facility: {facility}")

    def output(
        self,
        user: str,
        facility: str = 'S3DF',
        exp: str = None,
        run: str = None,
        energy: float = None,
        step: float = None,
        num: int = None,
        daq_num: int = 2):
        """
        Launch analysis script for notch scan results.

        Submits batch job to analyze collected data and generate
        plots of energy-dependent signals.

        Parameters
        ----------
        exp : str
            Experiment name (e.g., 'mfxls1234')
        facility : str, optional
            Computing facility: 'S3DF' or 'NERSC' (default: 'S3DF')

        Returns
        -------
        None

        Notes
        -----
        Analysis Scripts:
        - S3DF: /cds/home/d/djr/scripts/hsd/Notch_Scan_S3DF.sh
        - NERSC: /cds/home/d/djr/scripts/hsd/Notch_Scan_NERSC.sh

        The scripts:
        1. Locate data files for experiment
        2. Extract relevant detector signals
        3. Plot intensity vs. energy
        4. Save results to experiment directory

        Output Location:
        - Results saved to experiment analysis directory
        - Plots typically in PNG/PDF format
        - Data tables in CSV format

        Computing Resources:
        - S3DF: SLAC's S3DF cluster (local, faster)
        - NERSC: National facility (more resources)

        Batch System:
        - Jobs submitted via sbatch (SLURM)
        - Check status: squeue -u $USER
        - Typical runtime: 5-30 minutes

        Requirements:
        - Data must be recorded (record=True in series())
        - Valid experiment name
        - Network access to computing facility

        Examples
        --------
        Analyze on S3DF:
        >>> notch = NotchScan()
        >>> notch.output('mfxls1234', facility='S3DF')

        Analyze on NERSC:
        >>> notch.output('mfxls1234', facility='NERSC')

        See Also
        --------
        series : Perform notch scan
        """
        import os
        from mfx.db import daq
        from mfx.macros import get_exp, get_run
        import mfx.cctbx

        if daq_num == 2:
            station=0
        elif daq_num == 1:
            station=1
        else:
            logger.error('Please enter daq 1 or 2.')

        logger.info("Plotting XRT-Spec Output")
        if exp is None:
            exp = str(get_exp(station=station))

        if run is None:
            run = int(get_run(station=station))

        facility = facility.upper()
        if facility == 'NERSC':
            logger.warning(f"Have you renewed your token with sshproxy today?")
            token = input("(y/n)? ")

            if token.lower() == "n":
                cctbx.sshproxy(user)

        proc = [
            f"ssh -Yt {user}@s3dflogin "
            f"python /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/energy_calib_output.py "
            f"-f {facility} -t series -e {exp} -r {run} -z {energy} -s {step} -n {num}"
            ]

        logger.info(proc)
        os.system(proc[0])


# Convenience instance for direct import
notch = NotchScan()


def notch_scan(
        energy_scan_start_eV: float,
        energy_scan_end_eV: float,
        energy_scan_steps: int,
        run_length: int = 30,
        tag: str = 'dccm',
        picker: str = None,
        inspire: bool = False,
        daq_delay: int = 5,
        record: bool = False,
        daq_num: int = 2,
        exp: str = None):
    """
    Convenience function for performing notch scan.

    Wrapper around NotchScan.series() for quick access.

    Parameters
    ----------
    energy_scan_start_eV : float
        Starting energy in eV
    energy_scan_end_eV : float
        Ending energy in eV
    energy_scan_steps : int
        Energy step size in eV
    run_length : int, optional
        Collection time per point in seconds (default: 30)
    tag : str, optional
        Run tag (default: 'dccm')
    picker : str or None, optional
        Pulse picker mode: 'open', 'flip', or None
    inspire : bool, optional
        Add quotes to elog (default: False)
    daq_delay : int, optional
        Delay between runs in seconds (default: 5)
    record : bool, optional
        Enable recording (default: False)
    daq_num : int, optional
        DAQ version: 1 or 2 (default: 2)
    exp : str or None, optional
        Experiment name (default: None)

    Returns
    -------
    None

    Examples
    --------
    >>> notch_scan(7100, 7200, 5, run_length=60, record=True)

    See Also
    --------
    NotchScan.series : Full implementation
    """
    notch.series(
        energy_scan_start_eV=energy_scan_start_eV,
        energy_scan_end_eV=energy_scan_end_eV,
        energy_scan_steps=energy_scan_steps,
        run_length=run_length,
        tag=tag,
        picker=picker,
        inspire=inspire,
        daq_delay=daq_delay,
        record=record,
        daq_num=daq_num,
        exp=exp
    )