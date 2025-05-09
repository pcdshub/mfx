class Scan:
    def __init__(self):
        pass


    def scan(
            self,
            scan_start: float,
            scan_end: float,
            scan_steps: int,
            events_per_step: int = 120,
            sample: str = '?',
            tag: str = None,
            picker: str = None,
            runs: int = 1,
            inspire: bool = False,
            record: bool = False,
            pv: str = 'lxt_fast',
            close: bool = True,
            daq_num: int = 2,
            exp: str = None):
        """Perform scan.

        Parameters:
            scan_start (float): 
                start the scan at.

            scan_end (float): 
                end the scan at.

            scan_steps (int): 
                Number of steps in scan.

            events_per_step (int): 
                Number of events per step. Optional. Default: 120.

            sample: str, optional
                Sample Name

            tag: str, optional
                Run group tag

            picker: str, optional
                If 'open' it opens pp before run starts. If 'flip' it flipflops before run starts

            runs: int, optional
                number of runs 5 is default

            inspire: bool, optional
                Set false by default because it makes Sandra sad. Set True to inspire

            record (bool): 
                whether to record the scan or not. Optional. Default: False.

            pv (str): 
                PV or motor name. Required. Example 'MFX:LAS:MMN:08'

            close: bool, optional
                If False does not close pulse picker after when all runs finish
                but still closes when a run is canceled. True by default for safety.

            daq_num: int, optional
                Switch between daq 1 and 2. Default 2

            exp: str, optional
                Experiment name if needed
        

        """
        from ophyd import EpicsSignal
        import logging
        logger = logging.getLogger(__name__)
        from mfx.macros import get_run
        try:
            from mfx.db import RE, pp, daq, lxt_fast
            from mfx.autorun import quote, post
            from mfx.macros import get_exp
        except ImportError:
            from bluesky import RunEngine
            RE = RunEngine({})
        from nabs.plans import daq_scan

        try:
            import bluesky.plans as bp
        except ImportError:
            print("could not import bp")

        run_number = get_run(station=1) + 1

        if picker=='open':
            pp.open()
        if picker=='flip':
            pp.flipflop()

        if tag is None:
            tag = sample
        
        try:
            for i in range(runs):
                logger.info(f"Run Number {run_number} Running {sample}......{quote()['quote']}")

                daq.configure(motors=[lxt_fast], group_mask=0x1, events=events_per_step, record=True)
                RE(
                    bp.scan(
                        [daq],
                        lxt_fast,
                        scan_start,
                        scan_end,
                        scan_steps),
                        record=record)
                if record: 
                    post(
                        sample=sample, 
                        tag=tag, 
                        run_number=run_number, 
                        post=record, 
                        inspire=inspire,
                        daq_num=daq_num,
                        add_note=f'pv: {pv}, scan_start: {scan_start}, scan_end: {scan_end}, scan_steps: {scan_steps}')

        except KeyboardInterrupt:
            daq.control.setState("configured")
            while daq.control.getState() != "configured":
                ...
            daq.control.setRecord(False)
            daq.control.setState("running")
            pp.close()
            if record:
                post(
                    sample=sample, 
                    tag=tag, 
                    run_number=run_number, 
                    post=record, 
                    inspire=inspire,
                    daq_num=daq_num, 
                    add_note=f'Run ended prematurely. Probably sample delivery problem. ' +
                    f'pv: {pv}, scan_start: {scan_start}, scan_end: {scan_end}, scan_steps: {scan_steps}')
            logger.warning("[*] Stopping Run and exiting???...")
            logger.warning('Run ended prematurely. Probably sample delivery problem')

            if close is True:
                pp.close()
            daq.control.setState("configured")
            while daq.control.getState() != "configured":
                ...
            daq.control.setRecord(False)
            daq.control.setState("running")
            logger.warning('Finished with all runs thank you for choosing the MFX beamline!\n')


    def series(
            self,
            pv_values: list = [],
            daq_delay: int = 5,
            scan_start: float = None,
            scan_end: float = None,
            scan_steps: int = None,
            events_per_step: int = 120,
            sample: str = '?',
            tag: str = None,
            picker: str = None,
            runs: int = 1,
            inspire: bool = False,
            record: bool = False,
            pv: str = 'lxt_fast',
            close: bool = True,
            daq_num: int = 2,
            exp: str = None):
        """Perform Series scan.

        Parameters:
            pv_values (list): 
                List pv values as [1,2,3...]

            daq_delay: int, optional
                delay time between runs. Default is 5 second but increase is the DAQ is being slow.

            scan_start (float): 
                start the scan at.

            scan_end (float): 
                end the scan at.

            scan_steps (int): 
                Number of steps in scan.

            events_per_step (int): 
                Number of events per step. Optional. Default: 120.

            sample: str, optional
                Sample Name

            tag: str, optional
                Run group tag

            picker: str, optional
                If 'open' it opens pp before run starts. If 'flip' it flipflops before run starts

            runs: int, optional
                number of runs 5 is default

            inspire: bool, optional
                Set false by default because it makes Sandra sad. Set True to inspire

            record (bool): 
                whether to record the scan or not. Optional. Default: False.

            pv (str): 
                PV or motor name. Required. Example 'MFX:LAS:MMN:08'

            close: bool, optional
                If False does not close pulse picker after when all runs finish
                but still closes when a run is canceled. True by default for safety.

            daq_num: int, optional
                Switch between daq 1 and 2. Default 2

            exp: str, optional
                Experiment name if needed
        """
        import os
        import logging
        from mfx.db import pp, daq
        from mfx.autorun import quote
        from mfx.macros import get_exp
        from time import sleep
        logger = logging.getLogger(__name__)

        original_val = self.get.set1()

        for val in pv_values:
            self.put.set1(val)
            sleep(daq_delay)
            self.scan(
                scan_start=scan_start,
                scan_end=scan_end,
                scan_steps=scan_steps,
                events_per_step=events_per_step,
                sample=f'pv value: {val}',
                tag=tag,
                picker=picker,
                runs=runs,
                inspire=inspire,
                record=record,
                pv=pv,
                close=close,
                daq_num=daq_num,
                exp=exp)

        logger.warning('Finished with all runs thank you for choosing the MFX beamline!\n')

        logger.info(f'Moving energy back to original energy: {original_val}')
        self.put.set1(original_val)


    class get:
        def __init__(self):
            pass

        def set1():
            import os
            os.system(f'caget MFX:LAS:MMN:08')
            pv = int(os.popen("caget MFX:LAS:MMN:08 | awk '{print $2}'").read().strip())
            return pv

    class put:
        def __init__(self):
            pass

        def set1(energy):
            import os
            os.system(f'caput MFX:LAS:MMN:08 {energy}')