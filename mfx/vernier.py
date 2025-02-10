class Vernier:
    def __init__(self):
        pass


    def output(
            self,
            user: str,
            exp: str = None,
            run_list: list = [],
            facility: str = "S3DF"):
        """Perform Vernier scan results analysis.

        Parameters:
            user (str): username for computer account at facility.

            exp (str): 
                experiment number. Current experiment by default

            run_list (list): 
                List of run numbers. Last run number by default

            facility (str): Default: "S3DF". Options: "S3DF, NERSC".
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

        if len(run_list) == 0:
            run_list = [daq.run_number()]

        exp_run_list=[]

        for run in run_list:
            exp_run_list.append(f"{exp}:{run}")

        facility = facility.upper()

        proc = [
            f"ssh -Yt {user}@s3dflogin "
            f"python /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/fee_spec.py "
            f"-e {exp} -f {facility} -r {exp_run_list}"
            ]

        logging.info(proc)

        if facility == 'NERSC':
            logging.warning(f"Have you renewed your token with sshproxy today?")
            token = input("(y/n)? ")

            if token.lower() == "n":
                cctbx.sshproxy(user)

        os.system(proc[0])


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
            mcc_pv: str = 'MFX:USER:MCC:EPHOT:SET1'):
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
                If 'open' it opens pp before run starts. If 'flip' it flipflops before run starts

            inspire: bool, optional
                Set false by default because it makes Sandra sad. Set True to inspire

            record (bool): 
                whether to record the scan or not. Optional. Default: False.

            mcc_pv (str): 
                Vernier PV. Optional. Default: 'MFX:USER:MCC:EPHOT:SET1'.
        

        """
        from ophyd import EpicsSignal
        import logging
        logger = logging.getLogger(__name__)
        try:
            from mfx.db import RE, pp, daq
            from mfx.autorun import quote, post
        except ImportError:
            from bluesky import RunEngine
            RE = RunEngine({})
        from nabs.plans import daq_scan

        if picker=='open':
            pp.open()
        if picker=='flip':
            pp.flipflop()

        if tag is None:
            tag = sample

        logger.info(f"Run Number {daq.run_number() + 1} Running {sample}......{quote()['quote']}")
        run_number = daq.run_number() + 1
        RE(
            daq_scan(
                [],
                EpicsSignal(mcc_pv, name='mcc'),
                energy_scan_start_eV,
                energy_scan_end_eV,
                energy_scan_steps,
                events=events_per_step,
                record=record))
        pp.close()
        daq.disconnect()
        post(sample, tag, run_number, record, inspire)
        logger.warning('Finished with all runs thank you for choosing the MFX beamline!\n')


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
            mcc_pv: str = 'MFX:USER:MCC:EPHOT:SET1'):
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
                If 'open' it opens pp before run starts. If 'flip' it flipflops before run starts

            inspire: bool, optional
                Set false by default because it makes Sandra sad. Set True to inspire

            daq_delay: int, optional
                delay time between runs. Default is 5 second but increase is the DAQ is being slow.

            record (bool): 
                whether to record the scan or not. Optional. Default: False.

            mcc_pv (str): 
                Vernier PV. Optional. Default: 'MFX:USER:MCC:EPHOT:SET1'.
        

        """
        import os
        import logging
        from mfx.db import pp, daq
        from mfx.autorun import quote, autorun
        from time import sleep
        logger = logging.getLogger(__name__)

        if picker=='open':
            pp.open()
        if picker=='flip':
            pp.flipflop()

        logger.info(f"Run Number {daq.run_number() + 1} Running {sample}......{quote()['quote']}")
        run_number = daq.run_number() + 1

        energies = list(range(energy_scan_start_eV, energy_scan_end_eV, energy_scan_steps))

        for ev in energies:
            os.system(f'caput MFX:USER:MCC:EPHOT:SET1 {ev}')
            
            autorun(
                sample=str(ev), 
                tag=tag, 
                run_length=run_length, 
                record=record, 
                inspire=inspire, 
                picker=picker)
            sleep(daq_delay)

        logger.warning('Finished with all runs thank you for choosing the MFX beamline!\n')