"""
Yano laser control and automated data acquisition for MFX beamline.

This module provides interfaces for controlling OPO and EVO laser systems,
managing laser shutters, configuring timing triggers, and executing
automated pump-probe experiments with optional energy spread measurements.
"""

import os
import sys
import logging
from time import sleep, time

logger = logging.getLogger(__name__)


class Yano:
    """
    Laser control and automated data acquisition system for MFX.

    The Yano class provides comprehensive control of OPO (Optical Parametric
    Oscillator) and EVO (Evolution) laser systems, including shutter
    management, timing configuration, and automated pump-probe experiments
    with optional energy spread (SPREAD) measurements.

    Attributes
    ----------
    opo_shutter : LaserShutter
        OPO free-space laser shutter control
    evo_shutter1 : LaserShutter
        EVO fiber delivery shutter 1
    evo_shutter2 : LaserShutter
        EVO fiber delivery shutter 2
    evo_shutter3 : LaserShutter
        EVO fiber delivery shutter 3
    opo : Trigger
        OPO laser timing trigger (EVR channel 6)
    evo : Trigger
        EVO laser timing trigger (EVR channel 5)
    opo_time_zero : int
        OPO laser time-zero reference in nanoseconds
    opo_ec_short : int
        Event code for short OPO delay (212)
    opo_ec_long : int
        Event code for long OPO delay (211)
    opo_ec_longer : int
        Event code for longer OPO delay (210)
    opo_ec_longest : int
        Event code for longest OPO delay (213)
    PP : int
        Event code for pump-probe experiments (197)
    DAQ : int
        Event code for DAQ trigger (198)
    WATER : int
        Event code for water sample (211)
    SAMPLE : int
        Event code for sample measurement (212)
    rep_rate : int
        Laser repetition rate in Hz
    delay : float or None
        Current laser delay setting

    Methods
    -------
    shutter_status
        Get current status of all laser shutters
    configure_shutters(fiber1, fiber2, fiber3, free_space)
        Configure all laser shutters for experiment
    autorun(num_runs, num_events, run_length, record, use_l3t, controls,
            spread, spread_type, step_time, brewster, daq_num, add_note)
        Execute automated data acquisition with optional SPREAD

    Notes
    -----
    Laser Systems:
    - OPO: Free-space optical parametric oscillator for IR/Vis
    - EVO: Fiber-delivered laser with three independent channels

    Event Codes and Timing:
    - Event codes control laser timing relative to X-rays
    - Different codes provide various delay ranges
    - Time-zero calibration required for pump-probe experiments

    SPREAD Functionality:
    - Automated energy variation during data collection
    - Two modes: 'vernier' (fast) or 'k' (slow undulator change)
    - Enables energy-dependent studies with single command

    Examples
    --------
    Basic initialization and shutter configuration:
    >>> y = Yano()
    >>> y.configure_shutters(fiber1=True, fiber2=False,
    ...                      fiber3=False, free_space=True)

    Simple automated run:
    >>> y.autorun(num_runs=10, num_events=1000, record=True)

    Pump-probe with energy spread:
    >>> y.autorun(num_runs=20, num_events=5000, record=True,
    ...           spread=[8980, 9020, 5], spread_type='vernier',
    ...           brewster=True)

    See Also
    --------
    LaserShutter : Individual shutter control
    Trigger : EVR trigger configuration
    """

    def __init__(self):
        """
        Initialize Yano laser control system.

        Sets up laser shutter objects, timing triggers, event codes,
        and default parameters for laser operation.
        """
        from mfx.devices import LaserShutter
        from pcdsdevices.evr import Trigger
        self._delay = None

        # Initialize shutter objects with hardware PVs
        self._opo_shutter = LaserShutter(
            'MFX:USR:ao1:6',
            name='opo_shutter'
        )
        self._evo_shutter1 = LaserShutter(
            'MFX:USR:ao1:8',
            name='evo_shutter1'
        )
        self._evo_shutter2 = LaserShutter(
            'MFX:USR:ao1:2',
            name='evo_shutter2'
        )
        self._evo_shutter3 = LaserShutter(
            'MFX:USR:ao1:3',
            name='evo_shutter3'
        )

        # Initialize timing trigger objects
        self._opo = Trigger('MFX:LAS:EVR:01:TRIG6', name='opo_trigger')
        self._evo = Trigger('MFX:LAS:EVR:01:TRIG5', name='evo_trigger')

        # Laser timing parameters
        self._opo_time_zero = 671740  # nanoseconds

        # Event code definitions for delay control
        self._opo_ec_short = 212     # Shortest delay
        self._opo_ec_long = 211      # Long delay
        self._opo_ec_longer = 210    # Longer delay
        self._opo_ec_longest = 213   # Longest delay

        # Experiment event codes
        self._PP = 197      # Pump-probe
        self._DAQ = 198     # DAQ trigger
        self._WATER = 211   # Water reference
        self._SAMPLE = 212  # Sample measurement

        # Laser operating parameters
        self._rep_rate = 20  # Hz

    @property
    def shutter_status(self):
        """
        Get current status of all laser shutters.

        Returns
        -------
        list of str
            Status of each shutter in order: [evo_shutter1, evo_shutter2,
            evo_shutter3, opo_shutter]. Each element is either 'OPEN'
            or 'CLOSED'.

        Examples
        --------
        Check all shutter states:
        >>> y = Yano()
        >>> status = y.shutter_status
        >>> print(status)
        ['OPEN', 'CLOSED', 'CLOSED', 'OPEN']

        Use in conditional logic:
        >>> if 'OPEN' in y.shutter_status:
        ...     print("At least one shutter is open")
        """
        status = []
        for shutter in (self._evo_shutter1, self._evo_shutter2,
                        self._evo_shutter3, self._opo_shutter):
            status.append(shutter.state.get())
        return status

    def configure_shutters(self, fiber1=False, fiber2=False,
                           fiber3=False, free_space=None):
        """
        Configure all laser shutters for experimental setup.

        Sets the state (open/closed) of all four laser shutters according
        to the experimental requirements. EVO fiber shutters and OPO
        free-space shutter can be controlled independently.

        Parameters
        ----------
        fiber1 : bool, optional
            EVO fiber 1 shutter state. True=OPEN, False=CLOSED.
            Default is False.
        fiber2 : bool, optional
            EVO fiber 2 shutter state. True=OPEN, False=CLOSED.
            Default is False.
        fiber3 : bool, optional
            EVO fiber 3 shutter state. True=OPEN, False=CLOSED.
            Default is False.
        free_space : bool, optional
            OPO free-space shutter state. True=OPEN, False=CLOSED.
            If None, prompts user for input. Default is None.

        Returns
        -------
        None

        Notes
        -----
        Shutter Configuration Rules:
        - Only open shutters needed for current experiment
        - Keep unused shutters closed for safety
        - Verify laser alignment before opening shutters
        - Allow ~1 second settling time after changes

        Safety Considerations:
        - Free-space beam requires eye protection
        - Fiber delivery is generally safer
        - Always verify beam path before opening shutters
        - Close all shutters when not acquiring data

        Warnings
        --------
        Opening shutters activates laser delivery to experimental area.
        Ensure proper safety protocols are followed.

        Examples
        --------
        Configure for fiber 1 delivery only:
        >>> y = Yano()
        >>> y.configure_shutters(fiber1=True, fiber2=False,
        ...                      fiber3=False, free_space=False)

        Configure multiple fibers with interactive free-space:
        >>> y.configure_shutters(fiber1=True, fiber2=True)
        Open free space shutter? (y/n): n

        Close all shutters:
        >>> y.configure_shutters(fiber1=False, fiber2=False,
        ...                      fiber3=False, free_space=False)

        See Also
        --------
        shutter_status : Check current shutter states
        LaserShutter : Individual shutter control class
        """

        for state, shutter in zip((fiber1, fiber2, fiber3, free_space),
                                  (self._evo_shutter1, self._evo_shutter2,
                                   self._evo_shutter3, self._opo_shutter)):
            if state is not None:
                if state == True or state == 'OUT' or state == 2:
                    shutter('OUT')
                else:
                    shutter('IN')
        sleep(1)
        return


    def fiber_0(self):
        return self.configure_shutters(fiber1=False, fiber2=False, fiber3=False, free_space=None)


    def fiber_1(self):
        return self.configure_shutters(fiber1=False, fiber2=False, fiber3=True, free_space=None)


    def fiber_2(self):
        return self.configure_shutters(fiber1=False, fiber2=True, fiber3=True, free_space=None)


    def fiber_3(self):
        return self.configure_shutters(fiber1=True, fiber2=True, fiber3=True, free_space=None)


    def _delaystr(self, delay):
        """
        OPO delay string
        """
        if self._opo_shutter.state.value == 'IN':
            return 'No OPO Laser'
        elif delay >= 1e6:
            return 'Laser delay is set to {:10.6f} ms'.format(delay/1.e6)
        elif delay >= 1e3:
            return 'Laser delay is set to {:7.3f} us'.format(delay/1.e3)
        elif delay >= 0:
            return 'Laser delay is set to {:4.0f} ns'.format(delay)
        else:
            return 'Laser delay is set to {:8.0f} ns (AFTER X-ray pulse)'.format(delay)


    def _wrap_delay(self, delay, base_rate=120):
        """
        given a delay in units of nanoseconds, wrap the delay so that
        it is strictly less than the period of the base_rate
        """
        if delay*1E-9 > 1/base_rate:
            adjusted_delay = delay - (1/base_rate)*1E9
        else:
            adjusted_delay = delay
        return adjusted_delay


    def set_delay(self, delay, rep=30):
        """
        Set the delay

        Parameters
        ----------
        delay: float
            Requested laser delay in nanoseconds.

        rep: int, optional
            Set repetition rate only 60 and 30 Hz are currently available.
            30 Hz is default
        """


        from mfx.mfx_timing import MFX_Timing
        mfx_timing = MFX_Timing()

        logger = logging.getLogger(__name__)

        # Determine event code of inhibit pulse
        logger.info("Setting delay %s ns (%s us)", delay, delay/1000.)
        logger.info(f"Setting reprate: {rep}")
        self._delay = delay
        opo_delay = self._opo_time_zero - delay
        opo_ec = self._opo_ec_short

        if rep == 30:
            mfx_timing.set_seq(rep=30)
            if delay > self._opo_time_zero + 3e9/120:
                logger.error('Laser delay requested is too long. GO TO A SYNCHROTRON')
                sys.exit()
            elif delay > self._opo_time_zero + 2e9/120:
                opo_delay += 3e9/120
                opo_ec = self._opo_ec_longest
                logger.info('Laser is 3 buckets before the beam')
            elif delay > self._opo_time_zero + 1e9/120:
                opo_delay += 2e9/120
                opo_ec = self._opo_ec_longer
                logger.info('Laser is 2 buckets before the beam')
            elif delay > self._opo_time_zero:
                opo_delay += 1e9/120
                opo_ec = self._opo_ec_long
                logger.info('Laser is 1 bucket before the beam')
            else:
                opo_ec = self._DAQ
                logger.info('Laser is in the same bucket as the beam')

        elif rep == 60:
            mfx_timing.set_seq(rep='60_yano')
            if delay > self._opo_time_zero + 1e9/120:
                logger.error('Laser delay requested is too long at 60 Hz. Switch to 30 Hz')
                sys.exit()
            elif delay > self._opo_time_zero:
                opo_delay += 1e9/120
                opo_ec = self._opo_ec_long
                logger.info('Laser is 1 bucket before the beam')
            else:
                opo_ec = self._DAQ
                logger.info('Laser is in the same bucket as the beam')

        elif rep == 90:
            mfx_timing.set_seq(rep='90_yano')
            if delay > self._opo_time_zero:
                logger.error('Laser delay requested is too long at 60 Hz. Switch to 30 Hz')
                sys.exit()
            else:
                opo_ec = self._DAQ
                logger.info('Laser and drolet in the same bucket as the beam')

        elif rep == 120:
            mfx_timing.set_seq(rep='120_yano')
            if delay > self._opo_time_zero:
                logger.error('Laser delay requested is too long at 120 Hz. Switch to 30 Hz')
                sys.exit()
            else:
                opo_ec = self._DAQ
                logger.info('Laser and drolet in the same bucket as the beam')

        else:
            logger.error('Please enter either 30 or 60 Hz.')


        self._opo.ns_delay.put(opo_delay)
        logger.info("Setting OPO delay %s ns", opo_delay)
        self._opo.eventcode.put(opo_ec)
        logger.info("Setting OPO ec %s", opo_ec)
        logger.info(self._delaystr(delay))
        return


    def get_delay(self):
        """
        Reads the current delay in ns

        Parameters
        ----------
        delay: float
            Requested laser delay in nanoseconds.
        """

        logger = logging.getLogger(__name__)
        if self._opo.eventcode.get() == self._opo_ec_long:
            opo_delay = self._opo.ns_delay.get() - 1e9/120
        else:
            opo_delay = self._opo.ns_delay.get()
        delay = self._opo_time_zero - opo_delay
        logger.info(self._delaystr(delay))
        return delay


    def post(self, sample='?', tag=None, run_number=None, post=False,
             inspire=False, daq_num=2, spread=None, add_note=''):
        """
        Posts a message to the elog

        Parameters
        ----------
        sample: str, optional
            Sample Name

        tag: str, optional
            Run group tag

        run_number: int, optional
            Run Number. By default this is read off of the DAQ

        post: bool, optional
            set True to record/post message to elog

        inspire: bool, optional
            Set false by default because it makes Sandra sad. Set True to inspire

        daq_num: int, optional
            Switch between daq 1 and 2. Default 2

        add_note: string, optional
            adds additional note to elog message

        spread: str, optional
            Special note for running SPREAD
        """
        from mfx.db import elog
        from mfx.autorun import quote
        from mfx.macros import get_exp

        post_template = """\
        Run Number {}: {}

        {}

        While the laser shutters are:
        EVO fiber 1 ->  {}
        EVO fiber 2 ->  {}
        EVO fiber 3 ->  {}
        OPO Shutter ->  {}
        {}
        """
        if daq_num==1:
            from elog import HutchELog
            elog=HutchELog.from_conf(instrument='MFX',station=1)

        if add_note!='':
            add_note = '\n' + add_note
        if tag is None:
            tag = sample
        if inspire:
            comment = f"Running {sample}\n{quote()['quote']}{add_note}"
        else:
            comment = f"Running {sample}{add_note}"
        delay = self.get_delay()
        if run_number is None:
            run_number = get_run(station=0)
        info = [run_number, comment, self._delaystr(delay)]
        info.extend(self.shutter_status)
        if spread is not None:
            info.extend([spread])
        else:
            info.extend(["Spread      -> NO"])
        post_msg = post_template.format(*info)
        print('\n' + post_msg + '\n')
        if post:
            elog.post(msg=post_msg, tags=tag, run=(run_number))
        return post_msg


    def _begin(self, events=None, duration=300,
              record=False, use_l3t=None, controls=None,
              wait=False, end_run=False):
        """
        Start the daq and block until the daq has begun acquiring data.

        Optionally block with ``wait=True`` until the daq has finished aquiring
        data. If blocking, a ``ctrl+c`` will end the run and clean up.

        If omitted, any argument that is shared with `configure`
        will fall back to the configured value.

        Internally, this calls `kickoff` and manages its ``Status`` object.

        Parameters
        ----------
        events: ``int``, optional
            Number events to take in the daq.

        duration: ``int``, optional
            Time to run the daq in seconds, if ``events`` was not provided.

        record: ``bool``, optional
            If ``True``, we'll configure the daq to record data before this
            run.

        use_l3t: ``bool``, optional
            If ``True``, we'll run with the level 3 trigger. This means that
            if we specified a number of events, we will wait for that many
            "good" events as determined by the daq.

        controls: ``dict{name: device}`` or ``list[device...]``, optional
            If provided, values from these will make it into the DAQ data
            stream as variables. We will check ``device.position`` and
            ``device.value`` for quantities to use and we will update these
            values each time begin is called. To provide a list, all devices
            must have a ``name`` attribute.

        wait: ``bool``, optional
            If ``True``, wait for the daq to finish aquiring data. A
            ``KeyboardInterrupt`` (``ctrl+c``) during this wait will end the
            run and clean up.

        end_run: ``bool``, optional
            If ``True``, we'll end the run after the daq has stopped.
        """
        from mfx.db import daq
        from ophyd.utils import StatusTimeoutError, WaitTimeoutError

        logger = logging.getLogger(__name__)

        logger.debug(('Daq.begin(events=%s, duration=%s, record=%s, '
                        'use_l3t=%s, controls=%s, wait=%s)'),
                        events, duration, record, use_l3t, controls, wait)
        status = True
        try:
            if record is not None and record != daq.record:
                old_record = daq.record
                daq.preconfig(record=record, show_queued_cfg=False)
            begin_status = daq.kickoff(events=events, duration=duration,
                                        use_l3t=use_l3t, controls=controls)
            try:
                begin_status.wait(timeout=daq._begin_timeout)
            except (StatusTimeoutError, WaitTimeoutError):
                msg = (f'Timeout after {self._begin_timeout} seconds waiting '
                       'for daq to begin.')
                raise DaqTimeoutError(msg) from None

            # In some daq configurations the begin status returns very early,
            # so we allow the user to configure an emperically derived extra
            # sleep.
            sleep(daq.config['begin_sleep'])
            if wait:
                daq.wait()
                if end_run:
                    daq.end_run()
            if end_run and not wait:
                threading.Thread(target=daq._ender_thread, args=()).start()
            return status
        except KeyboardInterrupt:
                status = False
                return status


    def generate_energy_seq(
        self,
        energy_scan_start_eV,
        energy_scan_end_eV,
        energy_scan_steps,
        run_length,
        step_time,
        brewster=0):
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

            brewster: int, optional
                weights the bottom division of sequence twice.
                ie 2 weights the bottom half.
        """
        if energy_scan_steps <= 0:
            raise ValueError("Step size must be positive")

        run_total = round(run_length / step_time)

        up = list(range(
            energy_scan_start_eV, energy_scan_end_eV, energy_scan_steps))

        down = list(range(
            energy_scan_end_eV - energy_scan_steps,
            energy_scan_start_eV - energy_scan_steps,
            -energy_scan_steps))

        up_down = len(up) + len(down)

        part_up = []
        part_down = []
        if brewster > 0:
            part_up = up[:len(up) // brewster]

            part_down = down[-len(down) // brewster:]

            up_down = len(part_up) + len(part_down) + up_down

        number_iterations = run_total // up_down

        energy_seq = []
        for seq in range(number_iterations):
            energy_seq.extend(part_up)
            energy_seq.extend(part_down)
            energy_seq.extend(up)
            energy_seq.extend(down)

        return energy_seq


    def run(
        self,
        sample='?',
        tag=None,
        run_length=300,
        record=True,
        runs=5,
        inspire=False,
        daq_delay=5,
        picker=None,
        fiber=0,
        free_space=None,
        laser_delay=None,
        rep=30,
        daq_num=2,
        spread=[],
        spread_type=None,
        step_time=None,
        brewster=0):
        """
        Perform a single run of the experiment

        Parameters
        ----------
        sample: str, optional
            Sample Name

        tag: str, optional
            Run group tag

        run_length: int, optional
            number of seconds for run 300 is default

        record: bool, optional
            set True to record

        runs: int, optional
            number of runs 5 is default

        inspire: bool, optional
            Set false by default because it makes Sandra sad. Set True to inspire

        daq_delay: int, optional
            delay time between runs. Default is 5 second but increase is the DAQ is being slow.

        picker: str, optional
            If 'open' it opens pp before run starts. If 'flip' it flipflops before run starts

        fiber: int, optional
            Number of laser fibers. Default is -1. See ``configure_shutters`` for more
            information. Default 0

        free_space: bool, optional
            Sets the free_space laser shutter to Closed (False) or Open (True). Default is None.

        laser_delay: float
            Requested laser delay in nanoseconds.

        rep: int, optional
            Set repitition rate only 120, 60, 30 Hz are currently available.
            90 Hz is available using 2 ADE
            30 Hz is default

        daq_num: int, optional
            Switch between daq 1 and 2. Default 2

        spread: list, optional
            List SPREAD energies to dither over as [start, end, step]

        spread_type: str, optional
            SPREAD type either 'vernier' or 'k'

        step_time: int, optional
            step time for each energy of 'vernier' or 'k'

        brewster: int, optional
            weights the bottom division of SPREAD sequence twice.
            ie 2 weights the bottom half.

        Note
        ----
        0: (fiber1=False, fiber2=False, fiber3=False)
        1: (fiber1=False, fiber2=False, fiber3=True)
        2: (fiber1=False, fiber2=True, fiber3=True)
        3: (fiber1=True, fiber2=True, fiber3=True)

        For alternative laser configurations either use ``configure_shutters`` to set parameters
        """
        from mfx.db import daq, pp
        from mfx.autorun import quote
        from mfx.macros import get_run, get_exp

        logger = logging.getLogger(__name__)

        # Configure the shutters
        if fiber == 0:
            self.fiber_0()
        elif fiber == 1:
            self.fiber_1()
        elif fiber == 2:
            self.fiber_2()
        elif fiber == 3:
            self.fiber_3()
        else:
            logger.warning("No proper fiber number set so defaulting to ``configure_shutters`` settings.")

        if free_space is not None:
            if free_space == True or str(
                free_space).lower()==str('out') or int(
                    free_space) == 2 or str(
                        free_space).lower()==str('open'):
                self._opo_shutter('OUT')
            else:
                self._opo_shutter('IN')

        if laser_delay is not None:
            self.set_delay(laser_delay, rep=rep)
        delay = self.get_delay()
        logger.info(self._delaystr(delay))

        if sample.lower()=='water' or sample.lower()=='h2o':
            inspire=True
        if picker=='open':
            pp.open()
        if picker=='flip':
            pp.flipflop()

        if tag is None:
            tag = sample

        if daq_num == 1:
            for i in range(runs):
                run_number = get_run(station=1) + 1
                logger.info(f"Run Number {get_run(station=1) + 1} Running {sample}......{quote()['quote']}")
                status = self._begin(duration = run_length, record = record, wait = True, end_run = True)
                if status is False:
                    pp.close()
                    self.post(
                        sample=sample,
                        tag=tag,
                        run_number=run_number,
                        post=record,
                        inspire=inspire,
                        daq_num=daq_num,
                        add_note='Run ended prematurely. Probably sample delivery problem')
                    self.configure_shutters(fiber1=False, fiber2=False, fiber3=False, free_space=False)
                    logger.warning("[*] Stopping Run and exiting???...")
                    sleep(5)
                    daq.stop()
                    daq.disconnect()
                    logger.warning('Run ended prematurely. Probably sample delivery problem')
                    break

                self.post(
                    sample=sample,
                    tag=tag,
                    run_number=run_number,
                    post=record,
                    inspire=inspire,
                    daq_num=daq_num)
                try:
                    sleep(daq_delay)
                except KeyboardInterrupt:
                    pp.close()
                    self.configure_shutters(fiber1=False, fiber2=False, fiber3=False, free_space=False)
                    logger.warning("[*] Stopping Run and exiting???...")
                    sleep(5)
                    daq.disconnect()
                    status = False
                    if status is False:
                        logger.warning('Run ended prematurely. Probably sample delivery problem')
                        break
            if status:
                pp.close()
                self.configure_shutters(fiber1=False, fiber2=False, fiber3=False, free_space=False)
                daq.end_run()
                daq.disconnect()
                logger.warning('Finished with all runs thank you for choosing the MFX beamline!\n')

        elif daq_num == 2:
            try:
                for i in range(runs):
                    run_number = get_run(station=0) + 1
                    from psdaq.control.DaqControl import DaqControl  # NOQA
                    daq.control = DaqControl(
                        host=daq.control.host,
                        platform=daq.control.platform,
                        timeout=10000,
                    )
                    instr = daq.control.getInstrument()
                    if instr is None:
                        logger.error('Failed to connect to LCLS-II DAQ')
                        break
                    start_state = daq.control.getState()
                    if start_state == 'error':
                        logger.error('DAQ is in an error state.')
                        break

                    logger.info(f"Run Number {run_number} Running {sample}......{quote()['quote']}")

                    daq.control.setState("configured")
                    while daq.control.getState() != "configured":
                        ...
                    if record:
                        daq.control.setRecord(True)
                    else:
                        daq.control.setRecord(False)

                    daq.control.setState("running")
                    while daq.control.getState() != "running":
                        ...
                    start_time = time()
                    end_time = start_time + run_length

                    if len(spread) == 3 and spread_type is not None:
                        if spread_type.lower() == 'vernier':
                            spread_pv = 'MFX:USER:MCC:EPHOT:SET1'
                            spead_ref = "caget MFX:USER:MCC:EPHOT:SET1 | awk '{print $2}'"
                            if step_time is None:
                                step_time=1
                        elif spread_type.lower() == 'k':
                            spread_pv = 'MFX:USER:MCC:EPHOT:SET2'
                            spead_ref = "caget MFX:USER:MCC:EPHOT:SET2 | awk '{print $2}'"
                            if step_time is None:
                                step_time=10
                        else:
                            logger.error('Please enter spread type of vernier or k only')
                            sys.exit()
                        spread_comment = f'SPREAD Conditions: type:{spread_type}, range:{spread[0]}-{spread[1]}eV, step:{spread[2]}eV @ {step_time}s, Brewster: {brewster}'
                        energy_seq = self.generate_energy_seq(spread[0], spread[1], spread[2], run_length, step_time, brewster)

                        if brewster > 0:
                            energy = int(os.popen(spead_ref).read().strip())
                            try:
                                ind = energy_seq.index(energy)
                                energy_seq = energy_seq[ind:]
                            except ValueError:
                                logger.error(f"{energy} not found in the sequence. Starting with first energy")

                        for eng in energy_seq:
                            os.system(f'caput {spread_pv} {eng}')
                            sleep(step_time)

                    else:
                        spread_comment = None
                        while time() < end_time:
                            elapsed_time = time() - start_time
                            progress = min(elapsed_time / run_length, 1)  # Ensure progress doesn't exceed 1

                            filled_length = int(60 * progress)
                            bar = '=' * filled_length + '-' * (60 - filled_length)

                            percentage = f"{progress:.0%}"

                            print(f"\rProgress: [{bar}] {percentage}", end="")

                            sleep(1)  # Update frequency

                        print("\rProgress: [" + "="*60 + "] 100%") # Final, complete bar

                    daq.control.setState("configured")
                    while daq.control.getState() != "configured":
                        ...

                    if record:
                        self.post(
                            sample=sample,
                            tag=tag,
                            run_number=run_number,
                            post=record,
                            inspire=inspire,
                            daq_num=daq_num,
                            spread=spread_comment)

                    sleep(daq_delay)

            except KeyboardInterrupt:
                daq.control.setState("configured")
                while daq.control.getState() != "configured":
                    ...
                daq.control.setRecord(False)
                daq.control.setState("running")
                pp.close()
                if record:
                    self.post(
                        sample=sample,
                        tag=tag,
                        run_number=run_number,
                        post=record,
                        inspire=inspire,
                        daq_num=daq_num,
                        spread=spread_comment,
                        add_note='Run ended prematurely. Probably sample delivery problem')
                logger.warning("[*] Stopping Run and exiting???...")
                self.configure_shutters(fiber1=False, fiber2=False, fiber3=False, free_space=False)
                logger.warning('Run ended prematurely. Probably sample delivery problem')

            pp.close()
            self.configure_shutters(fiber1=False, fiber2=False, fiber3=False, free_space=False)
            daq.control.setState("configured")
            while daq.control.getState() != "configured":
                ...
            daq.control.setRecord(False)
            daq.control.setState("running")
            logger.warning('Finished with all runs thank you for choosing the MFX beamline!\n')
        else:
            logger.error('Please enter daq 1 or 2.')

