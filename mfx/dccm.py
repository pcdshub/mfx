from pcdsdevices.epics_motor import BeckhoffAxis

class DCCMono():
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


    def series(
            self,
            energy_scan_start_eV: float,
            energy_scan_end_eV: float,
            energy_scan_steps: int,
            run_length: int = 30,
            tag: str = None,
            picker: str = None,
            inspire: bool = False,
            daq_delay: int = 5,
            record: bool = False):
        """Perform Vernier scan.

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
                Run group tag/sample name

            picker: str, optional
                If 'open' it opens pp before run starts. If 'flip' it flipflops before run starts

            inspire: bool, optional
                Set false by default because it makes Sandra sad. Set True to inspire

            daq_delay: int, optional
                delay time between runs. Default is 5 second but increase is the DAQ is being slow.

            record (bool): 
                whether to record the scan or not. Optional. Default: False.
        """
        import os
        import logging
        from mfx.db import pp, daq
        from mfx.autorun import quote, autorun
        from mfx.macros import get_exp, determine_dccm_bragg
        from time import sleep
        logger = logging.getLogger(__name__)

        if picker=='open':
            pp.open()
        if picker=='flip':
            pp.flipflop()

        run_number = daq.run_number() + 1

        energies = list(range(energy_scan_start_eV, energy_scan_end_eV + energy_scan_steps, energy_scan_steps))
        logger.info(energies)

        original_th1 = self.th1()
        original_th2 = self.th2()

        for ev in energies: 
            bragg_angle = determine_dccm_bragg(ev)
            self.th1.umv(bragg_angle)
            self.th2.umv(bragg_angle)

            # autorun(
            #     sample=str(ev), 
            #     tag=tag, 
            #     run_length=run_length, 
            #     record=record,
            #     runs=1,
            #     inspire=inspire, 
            #     picker=picker,
            #     close=False)
            # sleep(daq_delay)

        logger.warning('Finished with all runs thank you for choosing the MFX beamline!\n')

        logger.info(f'Moving energy back to original bragg angle: {original_th1}')
        self.th1.umv(original_th1)
        self.th2.umv(original_th2)

        logging.warning(f"Series completed. Would you like to analyze the output?")
        answer = input("(y/n)? ")

        if answer.lower() == "y":
            facility = input("Enter facility (s3df or nersc) to continue: ")
            user = input("Enter username to continue: ")
            exp = str(get_exp())
            self.output.series(
                user=user, 
                facility=facility, 
                run_type='series', 
                exp=exp, 
                run=run_number, 
                energy=energy_scan_start_eV, 
                step=energy_scan_steps, 
                num=len(energies))


    class output:
        def __init__(self):
            pass


        def series(
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
                f"ssh -Yt {user}@s3dflogin "
                f"python /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/energy_calib_output.py "
                f"-f {facility} -t {run_type} -e {exp} -r {run} -z {energy} -s {step} -n {num}"
                ]

            logging.info(proc)
            os.system(proc[0])