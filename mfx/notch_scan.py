from pcdsdevices.epics_motor import BeckhoffAxis

class NotchScan():
    """
    Double Channel Cut Monochrometer controlled with a Beckhoff PLC.
    This includes five axes in total:
        - 2 for crystal manipulation (TH1/Upstream and TH2/Downstream)
        - 1 for chamber translation in x direction (TX)
        - 2 for YAG diagnostics (TXD and TYD)

    Parameters
    ----------
    prefix : str,optional
        Base PV for DCCM motors
    name : str
        A name or alias to refer to the device.
    """
    def __init__(self):
        tab_component_names = True
        # Bragg Upstream/TH1 Axis
        self.th1 = BeckhoffAxis("SP1L0:DCCM:MMS:TH1", name='th1')
        # Bragg Upstream/TH2 Axis
        self.th2 = BeckhoffAxis("SP1L0:DCCM:MMS:TH2", name='th2')
        # Bragg Translation X Axis
        self.tx = BeckhoffAxis("SP1L0:DCCM:MMS:TX", name='tx')


    def insert(self):
        import logging
        logging.info(f'Moving the DCCM IN')
        self.tx.umv(-1.3)


    def remove(self):
        import logging
        logging.info(f'Moving the DCCM OUT')
        self.tx.umv(-10)


    def set_energy(self, energy):
        """
        Changes Bragg angle for DCCM for chosen energy

        Parameters
        ----------
        energy : int,optional
            Select which energy in eV you want for DCCM mono beam

        """
        import logging
        from time import sleep, time
        from mfx.macros import determine_dccm_bragg

        start_time = time()
        bragg_angle = determine_dccm_bragg(energy)
        self.th1.mv(bragg_angle)
        self.th2.umv(bragg_angle)

        while round(self.th1(), 2) != round(bragg_angle, 2) or round(self.th2(), 2) != round(bragg_angle, 2):
            sleep(0.1)

            if time() - start_time > 30:
                logging.error("Timeout occurred: DCCM could not move to correct position. Try again.")
                logging.error(
                    f"th1: {round(self.th1(), 2)} or th2: {round(self.th2(), 2)} vs {round(bragg_angle, 2)}")
                status = False
                break

        if round(self.th1(), 2) == round(bragg_angle, 2) and round(self.th2(), 2) == round(bragg_angle, 2):
            logging.warning(f"DCCM is now in the correct position: {round(bragg_angle, 3)}")
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
        """Perform DCCM scan.

        Parameters:
            energy_scan_start_eV (float): 
                Photon energy (in eV) to start the scan at.

            energy_scan_end_eV (float): 
                Photon energy (in eV) to end the scan at.

            energy_scan_steps (int): 
                Step Size (in eV).

            run_length: int, optional
                number of seconds for run 30 is default

            tag: str, optional
                Run group tag. Default is 'dccm'

            picker: str, optional
                If 'open' it opens pp before run starts. If 'flip' it flipflops before run starts

            inspire: bool, optional
                Set false by default because it makes Sandra sad. Set True to inspire

            daq_delay: int, optional
                delay time between runs. Default is 5 second but increase is the DAQ is being slow.

            record (bool): 
                whether to record the scan or not. Optional. Default: False.

            daq_num: int, optional
                Switch between daq 1 and 2. Default 2

            exp: str, optional
                Experiment name if needed
                """
        import os
        import logging
        from mfx.db import pp, daq
        from mfx.autorun import quote, autorun
        from mfx.macros import get_run, determine_dccm_bragg
        from time import sleep
        logger = logging.getLogger(__name__)

        if picker=='open':
            pp.open()
        if picker=='flip':
            pp.flipflop()

        if daq_num == 1:
            station = 1
        elif daq_num == 2:
            station = 0
        else:
            logger.error('Please enter daq 1 or 2.')

        run_number = get_run(station=station) + 1

        energies = list(range(energy_scan_start_eV, energy_scan_end_eV + energy_scan_steps, energy_scan_steps))
        logger.info(energies)

        original_th1 = self.th1()
        original_th2 = self.th2()

        for ev in energies: 
            status = self.set_energy(ev)

            if status:
                sample=f'Notch scan with energy currently set to {str(ev)} eV'
            else:
                sample=f'Notch scan with energy currently set to {str(ev)} eV with possible error'

            autorun(
                sample=sample, 
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

        logging.warning(f"Series completed. Would you like to move back to original bragg angle?")
        answer = input("(y/n)? ")

        if answer.lower() == "y":
            logger.info(f'Moving back to original bragg angle: {original_th1}')
            self.th1.umv(original_th1)
            self.th2.umv(original_th2)

        logging.warning(f"Series completed. Would you like to analyze the output?")
        answer = input("(y/n)? ")

        if answer.lower() == "y":
            facility = input("Enter facility (s3df or nersc) to continue: ")
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


    def output(
            self,
            user: str,
            facility: str = "NERSC",
            exp: str = None,
            run: str = None,
            energy: float = None,
            step: float = None,
            num: int = None,
            daq_num: int = 2):
        """Perform Vernier scan results analysis.

        Parameters:
            user (str):
                Requires username and password for S3DF.
            facility (str):
                Default: "S3DF". Options: "S3DF", "NERSC"
            exp (str): 
                experiment number. Current experiment by default
            run (str): 
                The first run you'd like to process
            energy (float):
                specify the starting energy in eV
            step (float):
                specify the energy step size in eV
            num (int):
                specify the total number of runs
            daq_num: int, optional
                Switch between daq 1 and 2. Default 2

        """
        import logging
        import os
        from mfx.db import daq
        from mfx.macros import get_exp, get_run
        import mfx.cctbx
        logger = logging.getLogger(__name__)

        if daq_num == 2:
            station=0
        elif daq_num == 1:
            station=1
        else:
            logging.error('Please enter daq 1 or 2.')

        logging.info("Plotting XRT-Spec Output")
        if exp is None:
            exp = str(get_exp(station=station))

        if run is None:
            run = int(get_run(station=station))

        facility = facility.upper()
        if facility == 'NERSC':
            logging.warning(f"Have you renewed your token with sshproxy today?")
            token = input("(y/n)? ")

            if token.lower() == "n":
                cctbx.sshproxy(user)

        proc = [
            f"ssh -Yt {user}@s3dflogin "
            f"python /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/energy_calib_output.py "
            f"-f {facility} -t series -e {exp} -r {run} -z {energy} -s {step} -n {num}"
            ]

        logging.info(proc)
        os.system(proc[0])