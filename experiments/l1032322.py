import sys
import numpy as np
import logging
import time

from ophyd import EpicsSignal, EpicsSignalRO
from ophyd import Device, Component

from pcdsdevices.lasers.shutters import LaserShutter, LaserShutterMPOD

from xpp.db import daq, seq
try:
    from xpp.db import elog
except:
    print("Cannot import elog for now. Perhaps run as opr?")
from xpp.db import xpp_pulsepicker as pp
from xpp.db import xpp_ccm as ccm
from xpp.db import lp, cp, ep

# defined in qs
from xpp.db import trig_free_space, trig_main

sys.path.append('/cds/group/pcds/pyps/apps/hutch-python/xpp/experiments')
from lens_for_escan import CcmLens, lens_stack

logger = logging.getLogger(__name__)

evo_shutter1 = LaserShutterMPOD('XPP:R39:MPD:CH:0', name='evo_shutter1')
evo_shutter2 = LaserShutterMPOD('XPP:R39:MPD:CH:1', name='evo_shutter2')
evo_shutter3 = LaserShutterMPOD('XPP:R39:MPD:CH:2', name='evo_shutter3')

# events codes
PP = 94
DAQ = 95
WATER = 190
SAMPLE = 191

# laser delay and trigger variables
_las_trig = trig_free_space
_ec_short = SAMPLE
_ec_long = WATER
min_evr_delay = 669800 #may depend on evr. min_evr_delay = 0 ticks for code 4
t0 = 675058.8

class User:
    _evo_shutter1 = evo_shutter1
    _evo_shutter2 = evo_shutter2
    _evo_shutter3 = evo_shutter3
    _fs_shutter = lp
    
    delay = None
    t0 = t0
    ccm_lens = CcmLens(ccm, lens_stack, name='ccm_lens') # combined ccm and lens motion 
    
    @property
    def shutter_status(self):
        """Show current shutter status"""
        status = []
        for shutter in (self._evo_shutter1, self._evo_shutter2,
                        self._evo_shutter3):
            status.append(shutter.state.get())
        return status
    
    
    def configure_shutters(self, pulse1=False, pulse2=False, pulse3=False):
        """
        Configure all four laser shutters

        True means that the pulse will be used and the shutter is removed.
        False means that the pulse will be blocked and the shutter is inserted
           - default for evo laser pulse1, pulse2, pulse3
        None means that the shutter will not be changed
           - default for opo laser

        Parameters
        ----------
        pulse1: bool
            Controls ``evo_shutter1``

        pulse2: bool
            Controls ``evo_shutter2``

        pulse3: bool
            Controls ``evo_shutter3``
        """
        for state, shutter in zip((pulse1, pulse2, pulse3),
                                  (self._evo_shutter1, self._evo_shutter2,
                                   self._evo_shutter3)):
            if state == True or state == 'OUT' or state == 2:
                shutter('OUT')
            else:
                shutter('IN')
        time.sleep(1)
        return

    def zero_flash(self):
        return configure_shutters(pulse1=False, pulse2=False, pulse3=False)

    def one_flash(self):
        return configure_shutters(pulse1=False, pulse2=False, pulse3=True)

    def two_flash(self):
        return configure_shutters(pulse1=False, pulse2=True, pulse3=True)

    def three_flash(self):
        return configure_shutters(pulse1=True, pulse2=True, pulse3=True)

    
    def configure_sequencer(self):
        """
        EMPTY: used to clean up sequence and make GUI more readable
        DAQ: every pulse (120 Hz)
        WATER / SAMPLE: 60 Hz each, out-of-phase.
        """
        s_EMPTY = [0,0,0,0]
        s_DAQ = [DAQ,0,0,0]
        s_WATER = [WATER,1,0,0]
        s_SAMPLE = [SAMPLE,1,0,0]
        #sequence = [s_WATER, s_DAQ, s_SAMPLE, s_DAQ]
        sequence = [s_WATER, s_SAMPLE] # DAQ run on event code 40

        seq.sequence.put_seq([s_EMPTY for ii in range(100)])
        seq.sync_marker.put(5)
        seq.sequence.put_seq(sequence)
        seq.sequence_length.put(len(sequence))
        time.sleep(1)
        return


    def set_delay(self, delay):
        """
        Set the delay

        Parameters
        ----------
        delay: float
            Requested laser delay in nanoseconds. Must be less that 15.5 ms
        """ 
        logger.info("Setting delay %s ns (%s us)", delay, delay/1000.)
        self.delay = delay
        delay = self.t0 - delay
        ec = _ec_short
        if delay < min_evr_delay: # go to previous bucket for long delays
            delay += 1e9/120
            ec = _ec_long
        _las_trig.ns_delay.put(delay)
        _las_trig.eventcode.put(ec)
        logger.info("Setting laser ec %s", ec)
        logger.info(self._delaystr)
        return


    @property
    def _delaystr(self):
        """
        Free-sspace laser delay string
        """
        delay = self.delay
        if self._fs_shutter.state.get() == 'IN':
            return 'No free-space laser.'
        elif delay==None:
            return 'Delay not set.'
        elif delay >= 1e6:
            return 'Laser delay is set to {:10.6f} ms'.format(delay/1.e6)
        elif delay >= 1e3:
            return 'Laser delay is set to {:7.3f} us'.format(delay/1.e3)
        elif delay >= 0:
            return 'Laser delay is set to {:4.0f} ns'.format(delay)
        else:
            return 'Laser delay is set to {:8.0f} ns (AFTER X-ray pulse)'.format(delay)

    
    def continuous_ccmscan(self,
                           energies,
                           pointTime=1,
                           move_vernier=True,
                           wait_acr=False,
                           bidirectional=False,
                           is_daq=False,
                           initial_energy=None):
        """
        Scan the CCM
        
        Parameters
        ----------
        energies: list, np.ndarray
            Energies point to go over
        pointTime: float, default=1
            Time in second to spend at each point
        move_vernier: bool, default=True
            Does an energy request to ACR as the ccm is moved.
        wait_acr: bool, default=False
            Wait for ACR to return the done move status after an energy 
            request change was made. Useful for slow motion (undulator)
        bidirectional: bool, default=False
        """
        if wait_acr:
            ccm_e = ccm.energy_with_acr_status
        elif move_vernier:
            ccm_e = ccm.energy_with_vernier
        else:
            ccm_e = ccm.energy

        if initial_energy is None:
            initial_energy = ccm_e.energy.position
        
        try:
            self.ccm_sweep(ccm_e, energies, pointTime)
            if bidirectional:
                energies = energies[::-1]
                self.ccm_sweep(ccm_e, energies, pointTime)
            
        except KeyboardInterrupt:
            # Handle pausing or stopping the ccm scan.
            inp = 'q'
            if is_daq:
                daq.pause()
                current_energy = ccm_e.energy.position
                print(f"\nKeyboardInterrupt received. Run is paused at energy {current_energy}.")
                inp = input("Type \"q\" to finish the run or \"r\" to resume acquisition\n")
                
            if inp == 'q':
                print('\nScan end signal received.')
                ccm_e.move(initial_energy)
            elif inp == 'r':
                idx = np.where( np.isclose(energies, current_energy, atol=5e-3) )[0][0]
                #idx = np.where(energies >= current_energy)[0]
                energies = energies[idx:]
                print(f"Resuming scan with energies: {energies}")
                daq.resume()
                self.continuous_ccmscan(
                    energies,
                    pointTime=pointTime,
                    move_vernier=move_vernier,
                    wait_acr=wait_acr,
                    bidirectional=bidirectional,
                    is_daq=is_daq,
                    initial_energy=initial_energy
                )

        finally:
            print(f'Returning ccm to energy before scan: {initial_energy}')
            ccm_e.move(initial_energy)
            time.sleep(pointTime)
        return


    @staticmethod
    def ccm_sweep(ccm_e, energies, pointTime):
        for E in energies:
            ccm_e.move(E)
            time.sleep(pointTime)
        return


    def perform_run_with_escan(self, 
                               energies,
                               record=True,
                               comment='', 
                               pointTime=1,
                               post=True, 
                               move_vernier=True, 
                               wait_acr=False,
                               bidirectional=False,
                               **kwargs):
        """
        Perform a single run of the experiment

        Parameters
        ----------
        energies: List[float] a list of energies to scan over

        record: bool, optional
            Whether to record the run

        comment : str, optional
            Comment for ELog

        pointTime : int, optional
            how long in seconds to wait at a given energy before moving

        post: bool, optional
            Whether to post to the experimental ELog or not. Will not post if
            not recording

        move_vernier: bool, optional
            Whether or not to move the vernier while scanning the channel cut mono.
    
        wait_acr: bool, optional
            Wait for acr to complete the energy change

        kwargs:
            Used to control the laser shutters. See ``configure_shutters`` for more
            information

        Note
        ----
        This does not configure the laser parameters. Either use ``loop`` or
        ``configure_evr`` and ``configure_sequencer`` to set these parameters
        """
        # configure the shutters
        if 'pulse1' in kwargs or 'pulse2' in kwargs or 'pulse3' in kwargs: 
            self.configure_shutters(**kwargs)

        # Create descriptive message
        comment = comment or ''
        logger.info("Starting DAQ run, -> record=%s", record)
        daq.disconnect()
        daq.configure()
        
        try:
            daq.record = record
            daq.begin() #note we do not specify # of events, so it records until we stop
            runnum = daq._control.runnumber()
            time.sleep(1) # give DAQ a second
            if post and record:
                info = [runnum, comment, self._delaystr, min(energies), max(energies)]
                info.extend(self.shutter_status)
                post_msg = post_template_escan.format(*info)
                print('\n' + post_msg + '\n')
                elog.post(msg=post_msg, run=runnum)
            self.continuous_ccmscan(energies, 
                                    pointTime=pointTime,
                                    move_vernier=move_vernier, 
                                    wait_acr=wait_acr,
                                    bidirectional=bidirectional,
                                    is_daq=True)
        except KeyboardInterrupt:
            print('Interrupt signal received. Stopping run and DAQ')
        finally:
            daq.end_run()
            logger.info("Run complete!")
            daq.disconnect()

post_template = """\
Run Number: {} {}

Acquiring {} events

{}

While the laser shutters are:
EVO Pulse 1 ->  {}
EVO Pulse 2 ->  {}
EVO Pulse 3 ->  {}
"""


post_template_escan = """\
Run Number: {} {}

{}
\n
Minimum photon_energy -> {}
Maximum photon_energy -> {}

While the laser shutters are:
EVO Pulse 1 ->  {}
EVO Pulse 2 ->  {}
EVO Pulse 3 ->  {}
"""

def quote():
    import json,random
    from os import path
    _path = path.dirname(__file__)
    _path = path.join(_path,"/cds/home/d/djr/scripts/quotes.json")
    _quotes = json.loads(open(_path, 'rb').read())
    _quote = _quotes[random.randint(0,len(_quotes)-1)]
    _res = {'quote':_quote['text'],"author":_quote['from']}
    return _res


def autorun(sample='?', run_length=300, record=True, runs=5, inspire=False, delay=5, picker=None):
    """ 
    Automate runs.... With optional quotes

    Parameters
    ----------
    sample: str, optional
        Sample Name

    run_length: int, optional
        number of seconds for run 300 is default

    record: bool, optional
        set True to record

    runs: int, optional
        number of runs 5 is default

    inspire: bool, optional
        Set false by default because it makes Sandra sad. Set True to inspire

    delay: int, optional
        delay time between runs. Default is 5 second but increase is the DAQ is being slow.

    picker: str, optional
        If 'open' it opens pp before run starts. If 'flip' it flipflops before run starts

    Operations
    ----------

    """
    from time import sleep
    from mfx.db import daq, elog, pp
    import sys

    if sample.lower()=='water' or sample.lower()=='h2o':
        inspire=True
    if picker=='open':
        pp.open()
    if picker=='flip':
        pp.flipflop()
    try:
        for i in range(runs):
            print(f"Run Number {daq.run_number() + 1} Running {sample}......{quote()['quote']}")
            daq.begin(duration = run_length, record = record, wait = True, end_run = True)
            if record:
                if inspire:
                    elog.post(f"Running {sample}......{quote()['quote']}", run=(daq.run_number()))
                else:
                    elog.post(f"Running {sample}", run=(daq.run_number()))
            sleep(delay)
        pp.close()
        daq.end_run()
        daq.disconnect()

    except KeyboardInterrupt:
        print(f"[*] Stopping Run {daq.run_number()} and exiting...",'\n')
        pp.close()
        daq.stop()
        daq.disconnect()
        sys.exit()



















