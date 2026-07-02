"""Vernier energy control and calibration utilities for MFX beamline."""
import os
import logging

from mfx.energy_control import EnergyGet, EnergyPut

logger = logging.getLogger(__name__)


class Vernier:
    """
    Vernier energy control interface for fine energy adjustments.

    The Vernier system provides precise energy tuning via undulator K
    parameter changes, enabling small energy adjustments (typically ±100 eV)
    without moving the main monochromator. This maintains beam position and
    focus while allowing rapid energy scans.

    The vernier uses two PV sets for energy control:
    - REF (Reference): Stores calibration reference energies
    - SET (Setpoint): Stores requested energies for undulator adjustment

    Attributes
    ----------
    get : EnergyGet
        Interface to read current vernier energies from reference and
        setpoint PVs
    put : EnergyPut
        Interface to set vernier energies and control undulator K values
    output : VernierOutput
        Analysis and visualization tools for vernier scan data

    Methods
    -------
    scan(energy_start_eV, energy_end_eV, energy_steps, num_events)
        Execute single vernier energy scan with DAQ recording
    series(energy_scan_start_eV, energy_scan_steps, num_events, num_steps)
        Execute series of vernier scans for energy calibration

    Notes
    -----
    Vernier System Characteristics:
    - Small energy changes via undulator K parameter
    - Maintains beam trajectory and focus
    - Faster than full monochromator repositioning
    - Typical range: ±100 eV around nominal energy
    - Requires initial calibration reference

    The vernier system is particularly useful for:
    - Energy-dependent absorption edge studies
    - Resonant scattering experiments
    - Quick energy optimization
    - Maintaining beam stability during small energy changes

    Examples
    --------
    Create vernier instance and run single scan:
    >>> v = Vernier()
    >>> v.scan(energy_start_eV=8980, energy_end_eV=9020,
    ...        energy_steps=5, num_events=1000)

    Run calibration series:
    >>> v.series(energy_scan_start_eV=9000, energy_scan_steps=10,
    ...          num_events=1000, num_steps=11)

    See Also
    --------
    EnergyGet : Read vernier energy values
    EnergyPut : Set vernier energy values
    VernierOutput : Analyze vernier scan results
    """

    def __init__(self):
        """
        Initialize Vernier control system.

        Sets up energy get/put interfaces and output analysis tools.
        """
        self.get = EnergyGet()
        self.put = EnergyPut()
        self.output = VernierOutput()

    def scan(
            self,
            energy_scan_start_eV: float,
            energy_scan_end_eV: float,
            energy_scan_steps: int,
            events_per_step: int = 120,
            sample: str = '?',
            tag: str = None,
            picker: str = None,
            inspire: bool = False,
            record: bool = False,
            daq_num: int = 2,
            mcc: str = None):
        """Perform Vernier scan.

        Parameters:
            energy_scan_start_eV (float):
                Photon energy (in eV) to start the scan at.

            energy_scan_end_eV (float):
                Photon energy (in eV) to end the scan at.

            energy_scan_steps (int):
                Number of steps in scan.

            events_per_step (int):
                Number of events per step. Optional. Default: 120.

            sample: str, optional
                Sample Name

            tag: str, optional
                Run group tag

            picker: str, optional
                If 'open' it opens mfx_pulsepicker before run starts. If 'flip' it flipflops before run starts

            inspire: bool, optional
                Set false by default because it makes Sandra sad. Set True to inspire

            record (bool):
                whether to record the scan or not. Optional. Default: False.

            daq_num: int, optional
                Switch between daq 1 and 2. Default 2

            mcc (str):
                PV type either 'vernier' or 'k'


        """
        from ophyd import EpicsSignal
        from pcdsdevices.pv_positioner import OnePVMotor
        try:
            from mfx.db import RE, mfx_pulsepicker, daq
            from mfx.autorun import quote, post
            from mfx.macros import get_exp, get_run
            import bluesky.plans as bp
        except ImportError:
            from bluesky import RunEngine
            RE = RunEngine({})
        from nabs.plans import daq_scan

        if mcc.lower() == 'vernier':
            mcc_pv = 'MFX:USER:MCC:EPHOT:SET1'
        elif mcc.lower() == 'k':
            mcc_pv = 'MFX:USER:MCC:EPHOT:SET2'
        else:
            logger.error('Please enter spread type of vernier or k only')
            sys.exit()

        if picker=='open':
            mfx_pulsepicker.open()
        if picker=='flip':
            mfx_pulsepicker.flipflop()

        if tag is None:
            tag = sample

        if daq_num == 1:
            station = 1
        elif daq_num == 2:
            station = 0
        else:
            logger.error('Please enter daq 1 or 2.')

        original_ev = self.get.vernier()
        run_number = get_run(station=station) + 1
        logger.info(f"Run Number {run_number} Running {sample}......{quote()['quote']}")

        if daq_num == 1:
            mcc_pv_motor = EpicsSignal(mcc_pv, name='mcc')
            RE(
                daq_scan(
                    [],
                    mcc_pv_motor,
                    energy_scan_start_eV,
                    energy_scan_end_eV,
                    energy_scan_steps,
                    events=events_per_step,
                    record=record))
            daq.disconnect()

        elif daq_num == 2:
            mcc_pv_motor = OnePVMotor(mcc_pv, name="mcc")
            mcc_pv_motor.setpoint.kind = "hinted"
            daq.configure(
                motors=[mcc_pv_motor],
                group_mask=0x1,
                events=events_per_step,
                record=record)

            RE(bp.scan(
                [daq],
                mcc_pv_motor,
                energy_scan_start_eV,
                energy_scan_end_eV,
                energy_scan_steps))

        else:
            logger.error('Please enter daq 1 or 2.')

        mfx_pulsepicker.close()
        post(
            sample=sample,
            tag=tag,
            run_number=run_number,
            post=record,
            inspire=inspire,
            daq_num=daq_num,
            add_note=(
                f'Energy range:{energy_scan_start_eV}-{energy_scan_end_eV}eV, '
                f'steps:{energy_scan_steps}eV @ {events_per_step} events per step'
                ))

        logger.warning('Finished with all runs thank you for choosing the MFX beamline!\n')

        exp = str(get_exp())
        logger.warning(
                f"vernier.output.scan(user='user', facility='s3df', run_type='scan', "
                f"exp='{exp}', run={run_number}")

        logger.info(f'Moving energy back to original energy: {original_ev}')
        self.put.vernier(original_ev)

        logger.warning(f"Scan completed. Would you like to analyze the output?")
        answer = input("(y/n)? ")

        if answer.lower() == "y":
            facility = input("Enter facility (s3df or nersc) to continue: ")
            user = input("Enter username to continue: ")
            self.output.scan(
                user=user,
                facility=facility,
                run_type='scan',
                exp=exp,
                run=run_number)


    def series(
            self,
            energy_scan_start_eV: float,
            energy_scan_end_eV: float,
            energy_scan_steps: int,
            run_length: int = 10,
            tag: str = None,
            picker: str = None,
            inspire: bool = False,
            daq_delay: int = 5,
            record: bool = False,
            daq_num: int = 2):
        """Perform Vernier scan.

        Parameters:
            energy_scan_start_eV (float):
                Photon energy (in eV) to start the scan at.

            energy_scan_end_eV (float):
                Photon energy (in eV) to end the scan at.

            energy_scan_steps (int):
                Step Size (in eV).

            run_length: int, optional
                number of seconds for run 300 is default

            tag: str, optional
                Run group tag/sample name

            picker: str, optional
                If 'open' it opens mfx_pulsepicker before run starts. If 'flip' it flipflops before run starts

            inspire: bool, optional
                Set false by default because it makes Sandra sad. Set True to inspire

            daq_delay: int, optional
                delay time between runs. Default is 5 second but increase is the DAQ is being slow.

            record (bool):
                whether to record the scan or not. Optional. Default: False.

            daq_num: int, optional
                Switch between daq 1 and 2. Default 2
        """
        import os
        from mfx.db import mfx_pulsepicker, daq
        from mfx.autorun import quote, autorun
        from mfx.macros import get_exp
        from time import sleep

        if picker=='open':
            mfx_pulsepicker.open()
        if picker=='flip':
            mfx_pulsepicker.flipflop()

        if daq_num == 1:
            station = 1
        elif daq_num == 2:
            station = 0
        else:
            logger.error('Please enter daq 1 or 2.')

        run_number = get_run(station=station) + 1

        energies = list(range(energy_scan_start_eV, energy_scan_end_eV + energy_scan_steps, energy_scan_steps))
        logger.info(energies)

        original_ev = self.get.vernier()

        for ev in energies:
            self.put.vernier(ev)
            sleep(2)
            autorun(
                sample=str(ev),
                tag=tag,
                run_length=run_length,
                record=record,
                runs=1,
                inspire=inspire,
                picker=picker,
                close=False,
                daq_num=daq_num)
            sleep(daq_delay)

        logger.warning('Finished with all runs thank you for choosing the MFX beamline!\n')

        exp = str(get_exp())
        logger.warning(
                f"vernier.output.series(user='user', facility='s3df', run_type='series', "
                f"exp={exp}, run={run_number}, energy={energy_scan_start_eV}, "
                f"step={energy_scan_steps}, num={len(energies)})"
            )

        logger.info(f'Moving energy back to original energy: {original_ev}')
        self.put.vernier(original_ev)

        logger.warning(f"Series completed. Would you like to analyze the output?")
        answer = input("(y/n)? ")

        if answer.lower() == "y":
            facility = input("Enter facility (s3df or nersc) to continue: ")
            user = input("Enter username to continue: ")
            self.output.series(
                user=user,
                facility=facility,
                run_type='series',
                exp=exp,
                run=run_number,
                energy=energy_scan_start_eV,
                step=energy_scan_steps,
                num=len(energies))


class VernierOutput:
    """
    Analysis and visualization tools for vernier calibration data.

    Provides methods to analyze vernier scan results and generate
    diagnostic plots showing FEE spectrometer response, energy
    calibration curves, and statistical analysis of vernier performance.

    Methods
    -------
    fee_spec_list(user, facility, exp, run_list)
        Plot FEE spectrometer data from multiple runs for comparison
    series(user, facility, run_type, exp, run, energy, step, num)
        Analyze complete energy calibration series
    scan(user, facility, run_type, exp, run)
        Analyze single vernier energy scan

    Notes
    -----
    Analysis Workflow:
    1. Retrieve raw detector and spectrometer data
    2. Extract energy information from vernier PVs
    3. Correlate FEE spectrometer readings with vernier settings
    4. Generate calibration curves and residual plots
    5. Calculate statistical metrics

    Output Products:
    - Energy vs. FEE spectrometer plots
    - Calibration residuals
    - Statistical summaries
    - Diagnostic overlays

    Analysis runs on:
    - S3DF: Interactive analysis on login nodes
    - NERSC: Batch processing on Perlmutter

    See Also
    --------
    Vernier : Main vernier control interface
    """

    def __init__(self):
        """Initialize VernierOutput analysis interface."""
        pass

    def fee_spec_list(self, user, facility, exp=None, run_list=None):
        """
        Plot FEE spectrometer data from multiple runs.

        Generates overlay plots of FEE (Front End Enclosure) spectrometer
        data from a list of runs, allowing visual comparison of energy
        distributions across different experimental conditions.

        Parameters
        ----------
        user : str
            Username for remote facility access (S3DF or NERSC)
        facility : str
            Computing facility to use for analysis.
            Must be either 's3df' or 'nersc' (case-insensitive)
        exp : str, optional
            Experiment name (e.g., 'mfxls1234'). If None, uses current
            experiment from hutch database
        run_list : list of int, optional
            List of run numbers to analyze. If None, prompts user for input

        Returns
        -------
        None
            Generates plots saved to facility-specific location

        Notes
        -----
        The FEE spectrometer provides independent energy measurement
        useful for:
        - Verifying vernier energy settings
        - Detecting energy drift
        - Calibrating energy readback
        - Quality checking beam energy stability

        Analysis Scripts:
        - S3DF: /sdf/group/lcls/ds/tools/mfx/scripts/
                FEE_Spec_List_S3DF.sh
        - NERSC: /global/cfs/cdirs/lcls/mfxopr/scripts/hsd/
                 FEE_Spec_List_NERSC.sh

        Plot Output:
        - X-axis: Energy (eV)
        - Y-axis: Counts/intensity
        - Multiple runs overlaid with different colors
        - Legend identifying each run
        - Statistical information (mean, std)

        Warnings
        --------
        - Requires valid credentials for specified facility
        - Run list should contain completed runs with FEE data
        - Large run lists may take significant time

        Examples
        --------
        Compare FEE spectra from three runs:
        >>> vout = VernierOutput()
        >>> vout.fee_spec_list(user='myuser', facility='s3df',
        ...                    exp='mfxls1234', run_list=[100, 101, 102])

        Interactive run selection:
        >>> vout.fee_spec_list(user='myuser', facility='nersc')
        Enter run numbers (comma-separated): 50,51,52,53

        See Also
        --------
        scan : Analyze single scan with FEE data
        series : Analyze calibration series
        """
        import mfx.cctbx as cctbx

        logging.info("Plotting XRT-Spec Output")
        if exp is None:
            exp = str(get_exp())

        if len(run_list) == 0:
            run_list = [daq.run_number()]

        exp_run_list=[]

        for run in run_list:
            exp_run_list.append(f"{exp}:{run}")
        exp_run_list = " ".join(exp_run_list)

        facility = facility.upper()
        if facility == 'NERSC':
            logging.warning(f"Have you renewed your token with sshproxy today?")
            token = input("(y/n)? ")

            if token.lower() == "n":
                cctbx.sshproxy(user)

        proc = [
            f"ssh -Yt {user}@psana.sdf '"
            f"source /sdf/group/lcls/ds/ana/sw/conda1/manage/bin/psconda.sh && "
            f"python /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/fee_spec.py "
            f"-e {exp} -f {facility} -r {exp_run_list}'"
            ]

        logging.info(proc)
        os.system(proc[0])

        logger.info("FEE spectrometer analysis complete")

    def series(
            self,
            user: str,
            facility: str = "S3DF",
            run_type: str = 'series',
            exp: str = None,
            run: str = None,
            energy: float = None,
            step: float = None,
            num: int = None):
        """Perform Vernier scan results analysis.

        Parameters:
            facility (str):
                Default: "S3DF". Options: "S3DF, NERSC
            type (str):
                specify whether it is a vernier 'scan' or 'series'
            exp (str):
                experiment number. Current experiment by default
            run (str):
                The run you'd like to process
            energy (float):
                specify the starting energy in eV (only for 'series')
            step (float):
                specify the energy step size in eV (only for 'series')
            num (int):
                specify the total number of runs (only for 'series')
        """
        import logging
        import os
        from mfx.db import daq
        from mfx.macros import get_exp
        import mfx.cctbx
        logger = logging.getLogger(__name__)

        logging.info("Plotting XRT-Spec Output")
        if exp is None:
            exp = str(get_exp())

        if run is None:
            run = [daq.run_number()]

        facility = facility.upper()
        if facility == 'NERSC':
            logging.warning(f"Have you renewed your token with sshproxy today?")
            token = input("(y/n)? ")

            if token.lower() == "n":
                cctbx.sshproxy(user)

        proc = [
            f"ssh -Yt {user}@psana.sdf '"
            f"source /sdf/group/lcls/ds/ana/sw/conda1/manage/bin/psconda.sh && "
            f"python /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/energy_calib_output.py "
            f"-f {facility} -t {run_type} -e {exp} -r {run} -z {energy} -s {step} -n {num}'"
            ]

        logging.info(proc)
        os.system(proc[0])


    def scan(
            self,
            user: str,
            facility: str = "S3DF",
            run_type: str = 'scan',
            exp: str = None,
            run: str = None):
        """Perform Vernier scan results analysis.

        Parameters:
            facility (str):
                Default: "S3DF". Options: "S3DF, NERSC
            type (str):
                specify whether it is a vernier 'scan' or 'series'
            exp (str):
                experiment number. Current experiment by default
            run (str):
                The run you'd like to process
        """
        import logging
        import os
        from mfx.db import daq
        from mfx.macros import get_exp
        import mfx.cctbx
        logger = logging.getLogger(__name__)

        logging.info("Plotting XRT-Spec Output")
        if exp is None:
            exp = str(get_exp())

        if run is None:
            run = [daq.run_number()]

        facility = facility.upper()
        if facility == 'NERSC':
            logging.warning(f"Have you renewed your token with sshproxy today?")
            token = input("(y/n)? ")

            if token.lower() == "n":
                cctbx.sshproxy(user)

        proc = [
            f"ssh -Yt {user}@psana.sdf '"
            f"source /sdf/group/lcls/ds/ana/sw/conda1/manage/bin/psconda.sh && "
            f"python /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/energy_calib_output.py "
            f"-f {facility} -t {run_type} -e {exp} -r {run}'"
            ]

        logging.info(proc)
        os.system(proc[0])

        logger.info("Scan analysis complete")