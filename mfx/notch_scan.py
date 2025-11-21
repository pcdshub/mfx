"""
DCCM notch filter energy scanning for MFX beamline.

Provides automated energy scanning using DCCM monochromator for energy
calibration, edge scans, and spectroscopy experiments.
"""

import logging
from time import sleep
from typing import Optional

logger = logging.getLogger(__name__)


class NotchScan:
    """
    DCCM-based energy scanning controller.

    Provides automated energy scanning using Double Crystal Channel-cut
    Monochromator for applications including energy calibration, XANES,
    and edge scans.

    Attributes
    ----------
    dccm : DCCM
        DCCM monochromator device
    th1 : BeckhoffAxis
        Upstream crystal motor
    th2 : BeckhoffAxis
        Downstream crystal motor

    Methods
    -------
    set_energy(energy_eV, wait)
        Move to specific energy
    series(start, end, steps, run_length, tag, picker, record)
        Execute energy scan series

    Notes
    -----
    DCCM Energy Scanning:
    - Double crystal monochromator
    - Si(111) crystals
    - Energy range: ~4-25 keV
    - Resolution: ΔE/E ~ 1.4×10⁻⁴
    - Channel-cut design for stability

    Energy Conversion:
    - User specifies energy in eV
    - Converted to Bragg angle
    - Both crystals move together
    - Maintains beam path

    Scan Applications:
    - XANES (X-ray Absorption Near Edge Structure)
    - EXAFS energy calibration
    - Edge position determination
    - Energy-dependent studies

    Coordination:
    - DCCM crystals (coarse energy)
    - Optional vernier adjustment
    - Automated data collection
    - Elog documentation

    Examples
    --------
    Create notch scanner:
    >>> notch = NotchScan()

    Move to single energy:
    >>> notch.set_energy(9000, wait=True)
    Moving DCCM to 9.000 keV...

    Energy scan series:
    >>> notch.series(
    ...     energy_scan_start_eV=8950,
    ...     energy_scan_end_eV=9050,
    ...     energy_scan_steps=10,
    ...     run_length=30,
    ...     record=True
    ... )

    See Also
    --------
    DCCM : Monochromator control
    xas : XAS scanning utilities
    vernier : Energy fine control
    """

    def __init__(self):
        """
        Initialize NotchScan controller.

        Creates DCCM device and sets up energy control interfaces.
        """
        from mfx.dccm import DCCM

        self.dccm = DCCM(name='dccm')
        self.th1 = self.dccm.th1
        self.th2 = self.dccm.th2

        logger.info("NotchScan initialized")
        logger.info("DCCM energy range: 4000-25000 eV")

    def set_energy(self, energy_eV: float, wait: bool = True):
        """
        Move DCCM to specified energy.

        Converts energy to Bragg angle and moves both crystals
        to achieve requested photon energy.

        Parameters
        ----------
        energy_eV : float
            Target photon energy in eV
        wait : bool, optional
            Block until motion complete.
            Default is True.

        Returns
        -------
        None

        Notes
        -----
        Energy Setting Process:
        1. Convert eV to keV
        2. Calculate Bragg angle via Bragg's law
        3. Move both TH1 and TH2 crystals
        4. Wait for motion complete (if wait=True)
        5. Verify energy reached

        Bragg's Law:
        E (keV) = 12.398 / (2 * d * sin(θ))
        For Si(111): d = 3.1356 Å

        Move Time:
        - Small changes: ~5 seconds
        - Large changes: ~30 seconds
        - Depends on distance

        Accuracy:
        - Position: ±0.0001°
        - Energy: ±0.5 eV (typical)
        - Limited by motor resolution

        Warnings
        --------
        Verify energy is within DCCM range (4-25 keV).
        Large energy changes may take significant time.
        Check beam intensity after move.

        Examples
        --------
        Move to Cu K-edge:
        >>> notch = NotchScan()
        >>> notch.set_energy(8979, wait=True)

        Non-blocking move:
        >>> notch.set_energy(9000, wait=False)
        >>> # Do other things...
        >>> notch.dccm.energy.wait()

        Scan through energies:
        >>> for E in [8950, 9000, 9050]:
        ...     notch.set_energy(E)
        ...     sleep(10)  # Collect data

        See Also
        --------
        series : Automated energy scanning
        DCCM.energy : Direct energy control
        """
        energy_keV = energy_eV / 1000.0

        logger.info(f"Setting DCCM energy to {energy_eV} eV ({energy_keV} keV)")

        # Move DCCM energy (moves both crystals)
        self.dccm.energy.move(energy_keV, wait=wait)

        if wait:
            actual_keV = self.dccm.energy.position
            actual_eV = actual_keV * 1000
            logger.info(
                f"DCCM at {actual_eV:.1f} eV "
                f"(target: {energy_eV:.1f} eV)"
            )

    def series(
            self,
            energy_scan_start_eV: float,
            energy_scan_end_eV: float,
            energy_scan_steps: int,
            run_length: int = 30,
            tag: str = 'dccm',
            picker: Optional[str] = None,
            inspire: bool = False,
            daq_delay: int = 5,
            record: bool = False,
            daq_num: int = 2,
            exp: Optional[str] = None):
        """
        Execute automated DCCM energy scan series.

        Scans through discrete energy points while collecting data
        at each energy using automated DAQ runs.

        Parameters
        ----------
        energy_scan_start_eV : float
            Starting energy in eV
        energy_scan_end_eV : float
            Ending energy in eV
        energy_scan_steps : int
            Energy step size in eV.
            Number of points = (end - start) / steps
        run_length : int, optional
            Data collection time at each energy in seconds.
            Default is 30.
        tag : str, optional
            Run tag for organization.
            Default is 'dccm'.
        picker : str, optional
            Pulse picker mode: 'open', 'flip', or None.
            Default is None.
        inspire : bool, optional
            Add inspirational quotes to elog.
            Default is False.
        daq_delay : int, optional
            Delay between energy points in seconds.
            Allows system to settle.
            Default is 5.
        record : bool, optional
            Enable data recording.
            Default is False.
        daq_num : int, optional
            DAQ station: 1 (LCLS-I) or 2 (LCLS-II).
            Default is 2.
        exp : str, optional
            Experiment name. If None, auto-detects.
            Default is None.

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If daq_num not in [1, 2]

        Notes
        -----
        Scan Workflow:
        1. Calculate energy points from start/end/step
        2. Store initial crystal positions
        3. For each energy:
           a. Move DCCM to energy
           b. Wait for settling
           c. Collect data for run_length seconds
           d. Post run information to elog
           e. Wait daq_delay before next point
        4. Prompt to return to initial position
        5. Optionally analyze results

        Energy Point Generation:
        Uses Python range() with step size:
        energies = range(start, end + step, step)

        Actual energies:
        [start, start+step, start+2×step, ..., end]

        The final point equals end if (end - start) is
        divisible by step.

        Data Collection:
        - Uses autorun() for each energy
        - Sample name = energy value
        - Tag groups all runs
        - Run numbers sequential

        Post-Scan Analysis:
        - Prompts to return to initial energy
        - Offers analysis script execution
        - Can process on S3DF or NERSC
        - Generates energy calibration plots

        Typical Applications:
        - Energy calibration using standards
        - XANES edge scans
        - Verifying monochromator accuracy
        - Absorption edge determination

        Warnings
        --------
        - Ensure energy range within DCCM limits
        - Monitor beam intensity during scan
        - Large scans may take hours
        - Verify adequate disk space

        Examples
        --------
        Fe K-edge calibration scan:
        >>> notch = NotchScan()
        >>> notch.series(
        ...     energy_scan_start_eV=7100,
        ...     energy_scan_end_eV=7200,
        ...     energy_scan_steps=5,
        ...     run_length=60,
        ...     tag='Fe_edge',
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

        Fine energy scan:
        >>> notch.series(
        ...     energy_scan_start_eV=8975,
        ...     energy_scan_end_eV=8985,
        ...     energy_scan_steps=1,  # 1 eV steps
        ...     run_length=30,
        ...     record=True
        ... )

        With pulse picker:
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
        set_energy : Single energy positioning
        autorun : Data collection at each point
        DCCM : Monochromator control
        """
        from mfx.db import pp
        from mfx.autorun import autorun
        from mfx.macros import get_exp, get_run

        # Validate DAQ number
        if daq_num not in [1, 2]:
            logger.error('daq_num must be 1 (LCLS-I) or 2 (LCLS-II)')
            raise ValueError('Invalid daq_num')

        # Determine experiment
        if exp is None:
            exp = get_exp()

        # Determine station
        station = 1 if daq_num == 1 else 0

        # Generate energy list
        energies = list(range(
            energy_scan_start_eV,
            energy_scan_end_eV + energy_scan_steps,
            energy_scan_steps
        ))

        # Log scan configuration
        logger.info("\n" + "="*60)
        logger.info("DCCM ENERGY SCAN SERIES")
        logger.info("="*60)
        logger.info(f"Experiment: {exp}")
        logger.info(f"Energy range: {energy_scan_start_eV} - "
                    f"{energy_scan_end_eV} eV")
        logger.info(f"Step size: {energy_scan_steps} eV")
        logger.info(f"Number of points: {len(energies)}")
        logger.info(f"Energies: {energies}")
        logger.info(f"Run length: {run_length}s per point")
        logger.info(f"Total time: ~{len(energies) * (run_length + daq_delay) / 60:.1f} min")
        logger.info(f"Recording: {record}")
        logger.info("="*60 + "\n")

        # Store initial crystal positions
        original_th1 = self.th1.position
        original_th2 = self.th2.position
        logger.info(
            f"Initial positions: TH1={original_th1:.4f}°, "
            f"TH2={original_th2:.4f}°"
        )

        # Configure pulse picker
        if picker == 'open':
            logger.info("Opening pulse picker")
            pp.open()
        elif picker == 'flip':
            logger.info("Setting pulse picker to flip-flop")
            pp.flipflop()

        # Get starting run number
        run_number = get_run(station=station) + 1

        # Execute energy scan
        try:
            for idx, energy_eV in enumerate(energies):
                logger.info(f"\n{'='*60}")
                logger.info(f"ENERGY POINT {idx + 1}/{len(energies)}")
                logger.info(f"{'='*60}")

                # Move to energy
                logger.info(f"Setting energy: {energy_eV} eV")
                self.set_energy(energy_eV, wait=True)

                # Wait for settling
                logger.info(f"Settling for {daq_delay}s...")
                sleep(daq_delay)

                # Collect data
                logger.info(f"Collecting data for {run_length}s...")
                autorun(
                    sample=str(energy_eV),
                    tag=tag,
                    run_length=run_length,
                    record=record,
                    runs=1,
                    inspire=inspire,
                    picker=picker,
                    close=False,  # Don't close between points
                    daq_num=daq_num
                )

                logger.info(f"Completed energy point: {energy_eV} eV")

        except KeyboardInterrupt:
            logger.warning("\nEnergy scan interrupted by user")

        finally:
            # Close pulse picker
            if picker:
                pp.close()

        # Scan complete
        logger.info("\n" + "="*60)
        logger.info("ENERGY SCAN COMPLETE")
        logger.info("="*60)
        logger.info(f"Scanned {len(energies)} energy points")
        logger.info(f"Energy range: {energy_scan_start_eV} - "
                    f"{energy_scan_end_eV} eV")
        logger.info("="*60)

        # Offer to analyze
        if record:
            logger.info("\nData analysis command:")
            logger.info(
                f"ssh -Yt djr@s3dflogin "
                f"python /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/"
                f"energy_calib_output.py "
                f"-f s3df -t series -e {exp} -r {run_number} "
                f"-z {energy_scan_start_eV} -s {energy_scan_steps} "
                f"-n {len(energies)}"
            )

        # Prompt to return to initial position
        answer = input("\nReturn to initial crystal positions? (y/n): ")
        if answer.lower() == 'y':
            logger.info(
                f"Returning to initial positions: "
                f"TH1={original_th1:.4f}°, TH2={original_th2:.4f}°"
            ) self.th1.move(original_th1, wait=True)
            self.th2.move(original_th2, wait=True)
            logger.info("Returned to initial positions")

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
    Analysis and output for notch scan data.

    Provides methods to analyze energy calibration data and
    generate plots on computing facilities.

    Methods
    -------
    series(user, facility, exp, run, energy, step, num)
        Analyze energy scan series data

    Notes
    -----
    Analysis Process:
    1. Retrieve data from DAQ files
    2. Extract detector intensities vs. energy
    3. Identify absorption edge
    4. Compare to reference energy
    5. Calculate energy offset
    6. Generate calibration plots

    Output Products:
    - Energy vs. intensity plots
    - Edge position determination
    - Calibration offset value
    - Statistical uncertainties

    Computing Facilities:
    - S3DF: Interactive analysis
    - NERSC: Batch processing

    Examples
    --------
    >>> output = NotchOutput()
    >>> output.series(
    ...     user='myuser',
    ...     facility='S3DF',
    ...     exp='mfxls1234',
    ...     run=100,
    ...     energy=7112,
    ...     step=5,
    ...     num=20
    ... )

    See Also
    --------
    NotchScan.series : Data collection
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