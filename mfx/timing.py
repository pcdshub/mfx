"""Vernier energy control and calibration utilities for MFX beamline."""
import os
import sys
import logging

logger = logging.getLogger(__name__)


class Timing:
    """

    Attributes
    ----------

    Methods
    -------

    Notes
    -----

    Examples
    --------

    See Also
    --------

    """

    def __init__(self):
        """
        Initialize Timing control system.
        """
        from pcdsdevices.device import ObjectComponent as OCpt
        from pcdsdevices.lxe import LaserTiming
        from pcdsdevices.pseudopos import SyncAxis
        from pcdsdevices.usb_encoder import UsDigitalUsbEncoder
        from mfx.db import mfx_txt
        from mfx.db import mfx_lxt_fast1, mfx_lxt_fast2

        self.lxt = LaserTiming('LAS:FS45', name='lxt')
        self.txt = mfx_txt
        self.lxt_fast1 = mfx_lxt_fast1
        self.lxt_fast2 = mfx_lxt_fast2

        self.lxt_fast1_enc = UsDigitalUsbEncoder(
            'MFX:USDUSB4:01:CH2', name='lxt_fast_enc1', linked_axis=mfx_lxt_fast1)
        self.lxt_fast2_enc = UsDigitalUsbEncoder(
            'MFX:USDUSB4:01:CH1', name='lxt_fast_enc2', linked_axis=mfx_lxt_fast2)

        class LXTTTC(SyncAxis):
            lxt = OCpt(self.lxt)
            txt = OCpt(self.txt)

            tab_component_names = True
            scales = {'txt': -1}
            warn_deadband = 5e-14
            fix_sync_keep_still = 'lxt'
            sync_limits = (-10e-6, 10e-6)

        self.lxt_ttc = LXTTTC('', name='lxt_ttc')

    def scan(
            self,
            start: float,
            end: float,
            steps: int,
            events_per_step: int = 240,
            sample: str = '?',
            tag: str = 'timing',
            picker: str = None,
            inspire: bool = False,
            record: bool = True,
            daq_num: int = 2,
            pv: str = None):
        """Perform Timing scan.

        Parameters:
            start (float):
                Time Point (in s) to start the scan at.

            end (float):
                Time Point (in s) to end the scan at.

            steps (int):
                Number of steps in scan.

            events_per_step (int):
                Number of events per step. Optional. Default: 240.

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

            pv (str):
                PV type Please enter lxt, txt, lxt_ttc, lxt_fast1, or lxt_fast2

        """
        from ophyd import EpicsSignal
        from pcdsdevices.pv_positioner import OnePVMotor
        try:
            from mfx.db import RE, pp, daq
            from mfx.autorun import quote, post
            from mfx.macros import get_exp, get_run
            import bluesky.plans as bp
        except ImportError:
            from bluesky import RunEngine
            RE = RunEngine({})
        from nabs.plans import daq_scan

        if pv.lower() == 'lxt':
            pv = self.lxt
        elif pv.lower() == 'txt':
            pv = self.txt
        elif pv.lower() == 'lxt_ttc':
            pv = self.lxt_ttc
        elif pv.lower() == 'lxt_fast1':
            pv = self.lxt_fast1
        elif pv.lower() == 'lxt_fast2':
            pv = self.lxt_fast2
        else:
            logger.error('Please enter lxt, txt, lxt_ttc, lxt_fast1, or lxt_fast2')
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

        # original_time = pv.get()[0] if pv in [self.lxt, self.txt] else pv.get()[0][0]
        original_time = pv()

        run_number = get_run(station=station) + 1
        logger.info(f"Run Number {run_number} Running {sample}......{quote()['quote']}")

        if daq_num == 1:
            pv_motor = EpicsSignal(pv, name='pv')
            RE(
                daq_scan(
                    [],
                    pv_motor,
                    start,
                    end,
                    steps,
                    events=events_per_step,
                    record=record))
            daq.disconnect()

        elif daq_num == 2:
            pv_motor = OnePVMotor(pv, name="pv")
            pv_motor.setpoint.kind = "hinted"
            daq.configure(
                motors=[pv_motor],
                group_mask=0x1,
                events=events_per_step,
                record=record)

            RE(bp.scan(
                [daq],
                pv_motor,
                start,
                end,
                steps))

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
            add_note=(
                f'Time range:{start}-{end}s, '
                f'steps:{steps} @ {events_per_step} events per step'
                ))

        logger.warning('Finished with all runs thank you for choosing the MFX beamline!\n')

        exp = str(get_exp())
        logger.warning(
                f"timing.output(user='user', facility='s3df', run_type='scan', "
                f"exp='{exp}', run={run_number}")

        logger.info(f'Setting {pv} back to original time: {original_time}')
        pv(original_time)

        logger.warning(f"Scan completed. Would you like to analyze the output?")
        answer = input("(y/n)? ")

        if answer.lower() == "y":
            facility = input("Enter facility (s3df or nersc) to continue: ")
            user = input("Enter username to continue: ")
            self.output(
                user=user,
                facility=facility,
                exp=exp,
                run=run_number)


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
        Analysis and output for timing scan data.

        Provides methods to analyze timing calibration data and
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
        from mfx.macros import get_exp, get_run

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
            f"ssh -Yt {user}@s3dflogin '"
            f"source /sdf/group/lcls/ds/ana/sw/conda2/manage/bin/psconda.sh && "
            f"python /sdf/group/lcls/ds/tools/mfx/scripts/analyze_timing.py "
            f"-f {facility} -t proxy -e {exp} -r {run}'"
            ]

        logger.info(proc)
        os.system(proc[0])