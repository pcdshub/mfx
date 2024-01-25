from subprocess import check_output

import logging
import time

import numpy as np
import elog
from hutch_python.utils import safe_load
from bluesky.plans import scan
from bluesky.plans import list_scan
from mfx.db import daq
from mfx.db import RE
from mfx.delay_scan import delay_scan
from mfx.db import mfx_lxt_fast1 as lxt_fast
from pcdsdevices.evr import Trigger
from pcdsdevices.evr import Trigger
logger = logging.getLogger(__name__)

def set_current_position(motor, value):
    motor.set_use_switch.put(1)
    motor.set_use_switch.wait_for_connection()
    motor.user_setpoint.put(value, force=True)
    motor.user_setpoint.wait_for_connection()
    motor.set_use_switch.put(0)

def led_scan(start, end, nsteps, duration):
    """
    Function to scan led delays and dwell at each delay. Goes back to original delay after scanning.

    Parameters
    ---------
    start : float
        Start delay in microseconds.
    end : float
        End delay in microseconds.
    nsteps : integer
        number of steps for delay.
    duration : float
        Dwell time at each delay. In seconds.
    """

    with safe_load ('LED'):
    #self.led = Trigger('XCS:R42:EVR:01:TRIG6', name='led_delay')
    led = Trigger('MFX:LAS:EVR:01:TRIG3', name='led_delay')
    #self.led = Trigger('XCS:R44:EVR:44:TRIG6', name='led_delay')
    led_uS = MicroToNano()

    old_led = led.ns_delay.get()
    print('Scanning LED delays...')
    steps = np.linspace(start * 1000.0, end * 1000.0, nsteps)
    for step in steps:
        led.ns_delay.put(step)
        time.sleep(duration)
    led.ns_delay.put(old_led)
    print('Scan complete setting delay back to old value: ' +str(old_led))

def lxt_fast_set_absolute_zero(self):
    currentpos = lxt_fast()
    lxt_fast1_enc = UsDigitalUsbEncoder('MFX:USDUSB4:01:CH0', name='lxt_fast_enc1', linked_axis=lxt_fast)
    currentenc = lxt_fast_enc.get()
    #elog.post('Set current stage position {}, encoder value {} to 0'.format(currentpos,currentenc.pos))
    print('Set current stage position {}, encoder value {} to 0'.format(currentpos,currentenc.pos))
    lxt_fast.set_current_position(0)
    lxt_fast_enc.set_zero()
    return

def takeRun(nEvents=None, duration=None, record=True, use_l3t=False):
    daq.configure(events=120, record=record, use_l3t=use_l3t)
    daq.begin(events=nEvents, duration=duration)
    daq.wait()
    daq.end_run()

def pvascan(motor, start, end, nsteps, nEvents, record=None):
    currPos = motor.get()
    daq.configure(nEvents, record=record, controls=[motor])
    RE(scan([daq], motor, start, end, nsteps))
    motor.put(currPos)

def pvdscan(motor, start, end, nsteps, nEvents, record=None):
    daq.configure(nEvents, record=record, controls=[motor])
    currPos = motor.get()
    RE(scan([daq], motor, currPos + start, currPos + end, nsteps))
    motor.put(currPos)

#def ascan(self, motor, start, end, nsteps, nEvents, record=True, use_l3t=False):
#    self.cleanup_RE()
#    currPos = motor.wm()
#    daq.configure(nEvents, record=record, controls=[motor], use_l3t=use_l3t)
#    try:
#        RE(scan([daq], motor, start, end, nsteps))
#    except Exception:
#        logger.debug('RE Exit', exc_info=True)
#    finally:
#        self.cleanup_RE()
#    motor.mv(currPos)

def listscan(self, motor, posList, nEvents, record=True, use_l3t=False):
    self.cleanup_RE()
    currPos = motor.wm()
    daq.configure(nEvents, record=record, controls=[motor], use_l3t=use_l3t)
    try:
        RE(list_scan([daq], motor, posList))
    except Exception:
        logger.debug('RE Exit', exc_info=True)
    finally:
        self.cleanup_RE()
    motor.mv(currPos)

#def dscan(self, motor, start, end, nsteps, nEvents, record=True, use_l3t=False):
#    self.cleanup_RE()
#    daq.configure(nEvents, record=record, controls=[motor], use_l3t=use_l3t)
#    currPos = motor.wm()
#    try:
#        RE(scan([daq], motor, currPos+start, currPos+end, nsteps))
#    except Exception:
#        logger.debug('RE Exit', exc_info=True)
#    finally:
#        self.cleanup_RE()
#    motor.mv(currPos)

#def a2scan(self, m1, a1, b1, m2, a2, b2, nsteps, nEvents, record=True, use_l3t=False):
#    self.cleanup_RE()
#    daq.configure(nEvents, record=record, controls=[m1, m2], use_l3t=use_l3t)
#    try:
#        RE(scan([daq], m1, a1, b1, m2, a2, b2, nsteps))
#    except Exception:
#        logger.debug('RE Exit', exc_info=True)
#    finally:
#        self.cleanup_RE()

#def a3scan(self, m1, a1, b1, m2, a2, b2, m3, a3, b3, nsteps, nEvents, record=True):
#    self.cleanup_RE()
#    daq.configure(nEvents, record=record, controls=[m1, m2, m3])
#    try:
#        RE(scan([daq], m1, a1, b1, m2, a2, b2, m3, a3, b3, nsteps))
#    except Exception:
#        logger.debug('RE Exit', exc_info=True)
#    finally:
#        self.cleanup_RE()

#def delay_scan(self, start, end, sweep_time, record=True, use_l3t=False,
#               duration=None):
#    """Delay scan with the daq."""
#    self.cleanup_RE()
#    bec.disable_plots()
#    controls = [lxt_fast]
#    try:
#        RE(delay_scan(daq, lxt_fast, [start, end], sweep_time,
#                      duration=duration, record=record, use_l3t=use_l3t,
#                      controls=controls))
#    except Exception:
#        logger.debug('RE Exit', exc_info=True)
#    finally:
#        self.cleanup_RE()
#        bec.enable_plots()

#def empty_delay_scan(self, start, end, sweep_time, record=True,
#                     use_l3t=False, duration=None):
#    """Delay scan without the daq."""
#    self.cleanup_RE()
#    #daq.configure(events=None, duration=None, record=record,
#    #              use_l3t=use_l3t, controls=[lxt_fast])
#    try:
#        RE(delay_scan(None, lxt_fast, [start, end], sweep_time,
#                      duration=duration))
#    except Exception:
#        logger.debug('RE Exit', exc_info=True)
#    finally:
#        self.cleanup_RE()

def cleanup_RE(self):
    if not RE.state.is_idle:
        print('Cleaning up RunEngine')
        print('Stopping previous run')
        try:
            RE.stop()
        except Exception:
            pass

def scanExamples(self):
    print("""
    Absolute Scan
        re.daq_ascan([], sim.fast_motor1, -1, 1, 21, events = 10, record = False)

    Absolute 2D Scan
        re.daq_a2scan([], sim.fast_motor1, -1, 1 , sim.fast_motor2, -1, 1, nsteps = 5, events = 10, record = False)

    Absolute 3D Scan
        re.daq_a3scan([], sim.fast_motor1, -1, 1 , sim.fast_motor2, -1, 1, sim.fast_motor3, -1, 1, nsteps = 5, events = 10, record = False)

    Delta Scan
        re.daq_dscan([], sim.fast_motor1, -1, 1, 21, events = 10, record = False)

    Delay Scan
        re.daq_delay_scan([], lxt_fast, [-1e-12, 1e-12], sweep_time = 5,  duration = 20, record = False)

    Empty Delay Scan (no Daq)
        re.delay_scan([], lxt_fast, [-1e-12,1e-12], sweep_time = 5,  duration = 20)
    """)


##########################
# CCM Scanning Functions #
##########################
def perform_run(events, record=True, comment='', post=True,
                **kwargs):
    """
    Perform a single run of the experiment

    Parameters
    ----------
    events: int
        Number of events to include in run

    record: bool, optional
        Whether to record the run

    comment : str, optional
        Comment for ELog

    post: bool, optional
        Whether to post to the experimental ELog or not. Will not post if
        not recording

    Note
    ----
    """

    comment = comment or ''
    # Start recording
    logger.info("Starting DAQ run, -> record=%s", record)
    daq.begin(events=events, record=record)
    time.sleep(1)
    # Post to ELog if desired
    runnum = daq._control.runnumber()
    info = [runnum, comment, events, self._delaystr]
    post_msg = post_template.format(*info)
    print(post_msg)
    if post and record:
        elog(msg=post_msg, run=runnum)

    # Wait for the DAQ to finish
    logger.info("Waiting or DAQ to complete %s events ...", events)
    daq.wait()
    logger.info("Run complete!")
    daq.end_run()
    time.sleep(0.5)
    return



def dummy_daq_test(events=360, sleep=3, record=False):
    daq.connect()
    while 1:
        daq.begin(events=events, record=record)
        daq.wait()
        daq.end_run()
        time.sleep(sleep)
        print(time.ctime(time.time()))
    return

post_template = """\
Run Number: {} {}

Acquiring {} events

{}
"""


post_template_escan = """\
Run Number: {} {}

{}
Minimum photon_energy -> {}
Maximum photon_energy -> {}
"""

class MicroToNano():
def __init__(self):
    self._offset_nano = 0

def setOffset_nano(self, offset):
    self._offset_nano = offset

def setOffset_micro(self, offset):
    self._offset_nano = offset * 1000

def getOffset_nano(self):
    return self._offset_nano

def __call__(self, micro):
    return (micro * 1000) + self._offset_nano
