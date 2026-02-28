"""Vernier energy control and calibration utilities for MFX beamline."""
import os
import sys
import logging
import random
import numpy as np
import matplotlib.pyplot as plt

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
        from mfx.devices import LaserShutter
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

        # Initialize shutter objects with hardware PVs
        self.shutter1 = LaserShutter(
            'MFX:USR:ao1:6',
            name='shutter1'
        )
        self.shutter2 = LaserShutter(
            'MFX:USR:ao1:8',
            name='shutter2'
        )
        self.shutter3 = LaserShutter(
            'MFX:USR:ao1:2',
            name='shutter3'
        )
        self.shutter4 = LaserShutter(
            'MFX:USR:ao1:3',
            name='shutter4'
        )
        self.shutter5 = LaserShutter(
            'MFX:USR:ao1:4',
            name='shutter5'
        )

    def shutter_status(self):
        """
        Return the status of all laser shutters.
        """
        status = []
        for shutter in (self.shutter1, self.shutter2, self.shutter3, self.shutter4, self.shutter5):
            status.append(shutter.state.get())
            if laser is not None:
                shutter('IN')

        return status

    def check(self):
        """
        Check that all timing devices are responsive.
        """
        print(f"Device {self.lxt}: {self.lxt.position}")

        for device in (self.txt, self.lxt_fast1, self.lxt_fast2):
            print(f"Device {device}: {device.position[0]} s")

        print('shutter1:', self.shutter1.state.get())
        print('shutter2:', self.shutter2.state.get())
        print('shutter3:', self.shutter3.state.get())
        print('shutter4:', self.shutter4.state.get())
        print('shutter5:', self.shutter5.state.get())


    def clustered_points(self, y, z, n, power=2.0, center=None, plot=False):
        """
        n points in [y, z], spaced denser near `center`.
        power > 1 increases clustering strength.

        center: float in [y, z]. If None, uses midpoint.
        """
        y, z = float(y), float(z)
        if y > z:
            y, z = z, y

        c = (y + z) / 2.0 if center is None else float(center)
        if not (y <= c <= z):
            raise ValueError("center must be within [y, z]")

        # Create symmetric parameter space around center
        left = c - y
        right = z - c

        # Generate points in [-1, 1] parameter space
        t = np.linspace(-1.0, 1.0, n)
        u = np.sign(t) * (np.abs(t) ** power)

        # Map to [y, z] with asymmetric scaling
        x = np.where(u < 0, c + left * u, c + right * u)

        if plot:
            xs = np.sort(x)
            dx = np.diff(xs)

            fig, ax = plt.subplots(2, 1, figsize=(7, 4), constrained_layout=True)

            ax[0].plot(xs, np.zeros_like(xs), "o")
            ax[0].axvline(c, color="r", linestyle="--", label="center")
            ax[0].set_yticks([])
            ax[0].set_xlim(y, z)
            ax[0].set_title("Points (denser near chosen center)")
            ax[0].legend()

            ax[1].plot(dx, "-o")
            ax[1].set_title("Adjacent spacing (sorted)")
            ax[1].set_xlabel("Interval index")
            ax[1].set_ylabel("Δx")

            plt.show()

        return x.tolist()

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
            pv: str = None,
            laser: int = None,
            analysis: bool = True,
            randomize: bool = False,
            cluster: bool = False,
            center: float = None,
            delay: bool = False,
            duration: float = 300.0,
            sweep_time: float = 5.0
            ):
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

            laser (int):
                Specify which laser shutter to open (1 - 5). Default None

            analysis (bool):
                Whether to perform analysis and output after the scan. Default: True.

            randomize (bool):
                Whether to randomize the order of the scan points. Default: False.

            cluster (bool):
                Cluster points toward center and mark them on the plot. Default: False.

            center (float):
                Center point for clustering. If None, uses midpoint of start and end. Default: None.

            delay (bool):
                Whether to perform a delay scan with the specified
                duration and sweep time instead of a step scan. Default: False.

            duration (float):
                Total duration of the delay scan in seconds.
                Required if delay is True.

            sweep_time (float):
                Time to spend at each delay point during the delay scan in seconds.
                Required if delay is True.

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

        if laser is not None:
            if laser == 1:
                self.shutter1('OUT')
            elif laser == 2:
                self.shutter2('OUT')
            elif laser == 3:
                self.shutter3('OUT')
            elif laser == 4:
                self.shutter4('OUT')
            elif laser == 5:
                self.shutter5('OUT')
            else:
                logger.error('Please enter a valid laser shutter number (1-5).')

        if tag is None:
            tag = sample

        if daq_num == 1:
            station = 1
        elif daq_num == 2:
            station = 0
        else:
            logger.error('Please enter daq 1 or 2.')

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
            daq.configure(
                motors=[pv],
                group_mask=0x1,
                events=events_per_step,
                record=record)

            if cluster:
                points = self.clustered_points(
                    start, end, steps, power=2.0, center=center,plot=True)
            else:
                points = list(np.linspace(start, end, steps))

            if randomize:
                random.shuffle(points)

            if cluster or randomize:
                logger.info(f"Scan points: clustered {cluster} randomize {randomize}")
                RE(bp.list_scan([daq], pv, points))

            elif delay:
                logger.info(
                    f"Scan points: delay {delay} for duration "
                    f"{duration} with sweep time {sweep_time}")
                RE(
                    bp.delay_scan(
                        [daq], pv, [start, end], sweep_time=sweep_time, duration=duration))

            else:
                RE(bp.scan([daq], pv, start, end, steps))

        else:
            logger.error('Please enter daq 1 or 2.')

        pp.close()
        status = self.shutter_status()

        post(
            sample=sample,
            tag=tag,
            run_number=run_number,
            post=record,
            inspire=inspire,
            daq_num=daq_num,
            add_note=(
                f'Scaning {pv}, '
                f'Time range:{start} to {end}s, '
                f'steps:{steps} @ {events_per_step} events per step'
                f'shutter 1 state: {status[0]}, '
                f'shutter 2 state: {status[1]}, '
                f'shutter 3 state: {status[2]}, '
                f'shutter 4 state: {status[3]}, '
                f'shutter 5 state: {status[4]}, '
                f'{" with clustering at center " + str(center) if cluster else ""}'
                f'{" with randomization" if randomize else ""}'
                f'{" with delay scan" if delay else ""}'
                ))

        logger.warning('Finished with all runs thank you for choosing the MFX beamline!\n')

        exp = str(get_exp())
        logger.warning(
                f"timing.output(user='user', facility='s3df', "
                f"exp='{exp}', run={run_number}, daq_num={daq_num})")

        logger.info(f'Setting {pv} back to original time: {original_time}')
        pv(original_time)

        if analysis:
            logger.warning(f"Scan completed. Would you like to analyze the output?")
            answer = input("(y/n)? ")

            if answer.lower() == "y":
                facility = input("Enter facility (s3df or nersc) to continue: ")
                user = input("Enter username to continue: ")
                self.output(
                    user=user,
                    facility=facility,
                    exp=exp,
                    run=run_number,
                    daq_num=daq_num)

    def output(
        self,
        user: str,
        facility: str = 'S3DF',
        exp: str = None,
        run: str = None,
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