class Wire:
    def __init__(self):
        self.x_pv = 'MFX:USR:MMN:41'
        self.y_pv = 'MFX:USR:MMN:42'
        pass


    def scan(
            self,
            start: float,
            end: float,
            num_steps: int,
            num_events: int = 120,
            sample: str = 'wire',
            tag: str = 'wire',
            picker: str = None,
            inspire: bool = False,
            record: bool = False,
            daq_num: int = 2,
            mcc: str = None):
        """Perform wire scan.

        Parameters:
            start (float): 
                Position to start the scan at.

            end (float): 
                Position to end the scan at.

            num_steps (int): 
                Number of steps in scan.

            num_events (int): 
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

            daq_num: int, optional
                Switch between daq 1 and 2. Default 2

            mcc (str): 
                PV type either 'vernier' or 'k'
        

        """
        import sys
        from ophyd import EpicsSignal
        from pcdsdevices.pv_positioner import OnePVMotor
        import logging
        logger = logging.getLogger(__name__)
        try:
            from mfx.db import RE, pp, daq
            from mfx.autorun import quote, post
            from mfx.macros import get_exp, get_run
            import bluesky.plans as bp
        except ImportError:
            from bluesky import RunEngine
            RE = RunEngine({})
        from nabs.plans import daq_scan

        if mcc.lower() == 'x':
            mcc_pv = self.x_pv
        elif mcc.lower() == 'y':
            mcc_pv = self.y_pv
        else:
            logger.error('Please enter either x or y to scan')
            sys.exit()

        if picker=='open':
            pp.open()
        if picker=='flip':
            pp.flipflop()

        if tag is None:
            tag = sample

        if daq_num == 1:
            station = 1
        elif daq_num == 2:
            station = 0
        else:
            logger.error('Please enter daq 1 or 2.')

        run_number = get_run(station=station) + 1
        logger.info(f"Run Number {run_number} Running {sample}......{quote()['quote']}")

        if daq_num == 1:
            mcc_pv_motor = EpicsSignal(mcc_pv, name='mcc')
            RE(
                daq_scan(
                    [],
                    mcc_pv_motor,
                    start,
                    end,
                    num_steps,
                    events=num_events,
                    record=record))
            daq.disconnect()

        elif daq_num == 2:
            mcc_pv_motor = OnePVMotor(mcc_pv, name="mcc")
            mcc_pv_motor.setpoint.kind = "hinted"
            daq.configure(
                motors=[mcc_pv_motor],
                group_mask=0x1,
                events=num_events,
                record=record)

            RE(bp.scan(
                [daq],
                mcc_pv_motor,
                start,
                end,
                num_steps))

        else:
            logger.error('Please enter daq 1 or 2.')

        pp.close()
        post(
            sample=sample, 
            tag=tag, 
            run_number=run_number, 
            post=record, 
            inspire=inspire,
            daq_num=daq_num,
            add_note=f'Motor range:{start}-{end}eV, steps:{num_steps} @ {num_events} events per step for motor:{mcc_pv}')
        logger.warning('Finished with all runs thank you for choosing the MFX beamline!\n')

        logging.warning(f"Scan completed. Would you like to analyze the output?")
        answer = input("(y/n)? ")

        if answer.lower() == "y":
            facility = input("Enter facility (s3df or nersc) to continue: ")
            user = input("Enter username to continue: ")
            exp = str(get_exp())
            self.output.scan(
                user=user, 
                facility=facility, 
                run_type='scan', 
                exp=exp, 
                run=run_number)


    class output:
        def __init__(self):
            pass


        def scan(
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
                f"ssh -Yt {user}@s3dflogin "
                f"python /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/energy_calib_output.py "
                f"-f {facility} -t {run_type} -e {exp} -r {run}"
                ]

            logging.info(proc)
            os.system(proc[0])


    class get:
        def __init__(self):
            pass


        def x():
            import os
            os.system(f'caget MFX:USR:MMN:41')
            value = os.popen("caget MFX:USR:MMN:41 | awk '{print $2}'").read().strip()
            return value

        def y():
            import os
            os.system(f'caget MFX:USR:MMN:42')
            value = os.popen("caget MFX:USR:MMN:42 | awk '{print $2}'").read().strip()
            return value


    class put:
        def __init__(self):
            pass

        def x(value):
            import os
            os.system(f'caput MFX:USR:MMN:41 {value}')

        def y(value):
            import os
            os.system(f'caput MFX:USR:MMN:42 {value}')