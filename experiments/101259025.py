from subprocess import check_output

import json
import sys
import time
import os

import numpy as np
from hutch_python.utils import safe_load
from ophyd import EpicsSignalRO
from ophyd import EpicsSignal
from bluesky import RunEngine
from bluesky.plans import scan
from bluesky.plans import list_scan
from bluesky.plan_stubs import configure
#from bluesky.plans import list_grid_scan
from ophyd import Component as Cpt
from ophyd import Device
from pcdsdevices.epics_motor import Newport, IMS, MMC100, BeckhoffAxis
from pcdsdevices.interface import BaseInterface
from pcdsdevices.device_types import Trigger
from pcdsdevices.areadetector import plugins
from mfx.db import daq
from mfx.db import sequencer as seq
from mfx.db import camviewer
from mfx.db import RE
#from cxi.db import foil_x, foil_y
from mfx.db import mfx_pulsepicker as pp
from mfx.db import bp, bpp, bps
from mfx.plans import serp_seq_scan
from time import sleep

class User():
    def __init__(self):
        self._sync_markers = {0.5:0, 1:1, 5:2, 10:3, 30:4, 60:5, 120:6, 360:7}
        self.evr_pp = Trigger('XRT:EVR:R48:TRIG1',name='evr_pp')
        self.pp_delay = EpicsSignal('XRT:EVR:R48:TRIG1:TDES', name='pp_delay')

        with safe_load('sam_x'):
            self.sam_x = BeckhoffAxis('MFX:LJH:JET:X', name='sam_x')
        with safe_load('sam_y'):
            self.sam_y = BeckhoffAxis('MFX:LJH:JET:Y', name='sam_y')
        with safe_load('sam_z'):
            self.sam_z = BeckhoffAxis('MFX:LJH:JET:Z', name='sam_z')
        #with safe_load('sam_pitch'):
        #    self.sam_pitch = MMC100('CXI:USR:MMC:01', name='sam_pitch')
        #with safe_load('post_sam_x'):
        #    self.post_sam_x = IMS('CXI:USR:MMS:27', name='post_sam_x')
        #with safe_load('post_sam_y'):
        #    self.post_sam_y = MMC100('CXI:USR:MMC:02', name='post_sam_y')
        #with safe_load('post_sam_z'):
        #    self.post_sam_z = MMC100('CXI:USR:MMC:03', name='post_sam_z')
        #with safe_load('op_focus'):
        #    self.wfs_focus = IMS('CXI:USR:MMS:26', name='wfs_focus')
        #with safe_load('op_x'):
        #    self.wfs_x = Newport('CXI:USR:MMN:09', name='wfs_x')
        #with safe_load('op_y'):
        #    self.wfs_v = IMS('CXI:USR:MMS:25', name='wfs_v')


    def takeRun(self, nEvents, record=True):
        daq.configure(events=120, record=record)
        daq.begin(events=nEvents)
        daq.wait()
        daq.end_run()

    def get_ascan(self, motor, start, end, nsteps, nEvents, record=True):
        daq.configure(nEvents, record=record, controls=[motor])
        return scan([daq], motor, start, end, nsteps)

    def get_dscan(self, motor, start, end, nsteps, nEvents, record=True):
        daq.configure(nEvents, record=record)
        currPos = motor.wm()
        return scan([daq], motor, currPos+start, currPos+end, nsteps)

    def ascan(self, motor, start, end, nsteps, nEvents, record=True):
        daq.configure(nEvents, record=record, controls=[motor])
        RE(scan([daq], motor, start, end, nsteps))

    def listscan(self, motor, posList, nEvents, record=True):
        daq.configure(nEvents, record=record, controls=[motor])
        RE(list_scan([daq], motor, posList))

    def dscan(self, motor, start, end, nsteps, nEvents, record=True):
        daq.configure(nEvents, record=record, controls=[motor])
        currPos = motor.wm()
        RE(scan([daq], motor, currPos+start, currPos+end, nsteps))

    def setupSequencer(self, flymotor, distance, deltaT_shots, pp_shot_delay=2):
        ## Setup sequencer for requested rate
        #sync_mark = int(self._sync_markers[self._rate])
        #leave the sync marker: assume no dropping.
        sync_mark = int(self._sync_markers[120])
        seq.sync_marker.put(sync_mark)
        #seq.play_mode.put(0) # Run sequence once
        seq.play_mode.put(1) # Run sequence N Times
    
        # Determine the different sequences needed
        beamDelay = int(120*deltaT_shots)-pp_shot_delay
        if (beamDelay+pp_shot_delay)<4:
            print('PP cannot go faster than 40 Hz in flip-flip mode, quit!')
            return
        fly_seq = [[185, beamDelay, 0, 0],
                   [187, pp_shot_delay, 0, 0]]
        #logging.debug("Sequence: {}".format(fly_seq))                  

        #calculate how often to shoot in requested distance
        flyspeed = flymotor.velocity.get()
        flytime = distance/flyspeed
        flyshots = int(flytime/deltaT_shots)
        seq.rep_count.put(flyshots) # Run sequence N Times

        seq.sequence.put_seq(fly_seq) 

    def setPP_flipflip(self, nshots=20, deltaShots=30):
        ## Setup sequencer for requested rate
        #sync_mark = int(self._sync_markers[self._rate])
        #leave the sync marker: assume no dropping.
        sync_mark = int(self._sync_markers[120])
        seq.sync_marker.put(sync_mark)
        #seq.play_mode.put(0) # Run sequence once
        seq.play_mode.put(1) # Run sequence N Times
        seq.rep_count.put(nshots) # Run sequence N Times
    
        # Determine the different sequences needed
        beamDelay = int(delta_shots)-pp_shot_delay
        if (beamDelay+pp_shot_delay)<4:
            print('PP cannot go faster than 40 Hz in flip-flip mode, quit!')
            return
        ff_seq = [[185, beamDelay, 0, 0],
                   [187, pp_shot_delay, 0, 0]]
        #logging.debug("Sequence: {}".format(fly_seq))                  
        seq.sequence.put_seq(ff_seq) 

    def set_pp_flipflop(self):
        pp.flipflop(wait=True)

    def runflipflip(self, start, end, nsteps,nshots=20, deltaShots=30):
        self.set_pp_flipflop()
        #self.setPP_flipflip(nshots=20, deltaShots=6)
        for i in nsteps:
            self.evr_pp.ns_delay.set(start+delta*i)
            seq.start()
            time.sleep(5)

    def run_evr_seq_scan(self, start, env, nsteps, record=None, use_l3t=None):
        """RE the plan."""
        self.set_pp_flipflop()
        RE(evr_seq_plan(daq, seq, self.evr_pp, start, env, nsteps,
                        record=record, use_l3t=use_l3t))

    def evr_seq_plan(self, daq, seq, evr, start, end, nsteps,
                     record=None, use_l3t=None):
        """Configure daq and do the scan, trust other code to set up the sequencer."""
        yield from configure(daq, events=None, duration=None, record=record,
                             use_l3t=use_l3t, controls=[evr])
        yield from scan([daq, seq], evr, start, end, nsteps)

    def run_serp_seq_scan(self, shiftStart, shiftStop, shiftSteps, flyStart, flyStop, deltaT_shots, record=False, pp_shot_delay=2):
        daq.disconnect() #make sure we start from fresh point.
        shiftMotor=foil_y
        flyMotor=foil_x
        self.setupSequencer(flyMotor, abs(flyStop-flyStart), deltaT_shots, pp_shot_delay=pp_shot_delay)
        daq.configure(-1, record=record, controls=[foil_x, foil_y])
        #daq.begin(-1)
            
        if isinstance(shiftSteps, int):
             RE(serp_seq_scan(shiftMotor, np.linspace(shiftStart, shiftStop, shiftSteps), flyMotor, [flyStart, flyStop], seq))
        else:
             RE(serp_seq_scan(shiftMotor, np.arange(shiftStart, shiftStop, shiftSteps), flyMotor, [flyStart, flyStop], seq))

    def PPburst_sequence(self, nShots=None, nOffShots=2):
        if nOffShots < 2:
            raise ValueError('Minimum offshots is 2')
        ff_seq = [[185, 0, 0, 0]]
        ff_seq.append([179, 1 , 0, 0])
        ff_seq.append([179, 1 , 0, 0])
        if nShots is not None:
            if isinstance(nShots , int):
                ff_seq.append([185, nShots-2, 0, 0])
            else:
                ff_seq.append([185, int(nShots*120)-2, 0, 0])
        ff_seq.append([179, 2, 0, 0])
        if nShots is not None:
            if isinstance(nShots , int):
                for i in range(nOffShots-2):
                    ff_seq.append([179, 1, 0, 0])
            else:
                for i in range(int(nOffShots*120)-2):
                    ff_seq.append([179, 1, 0, 0])
        return ff_seq

    def prepare_seq_PPburst(self, nShots=None, nOffShots=None):
        ## Setup sequencer for requested rate
        #sync_mark = int(self._sync_markers[self._rate])
        #leave the sync marker: assume no dropping.
        sync_mark = int(self._sync_markers[120])
        seq.sync_marker.put(sync_mark)
        seq.play_mode.put(0) # Run sequence once
        #seq.play_mode.put(1) # Run sequence N Times
        #seq.rep_count.put(nshots) # Run sequence N Times
    
        ff_seq = self.PPburst_sequence(nShots=nShots, nOffShots=nOffShots)
        seq.sequence.put_seq(ff_seq)

    def PPburst_sequence_pattern(self, nShots=None, nOffShots=None, nTimes=1):
        single_burst = self.PPburst_sequence(nShots=nShots, nOffShots=nOffShots)
        ff_seq = []
        for i in range(nTimes):
            ff_seq += single_burst
        return ff_seq

    def prepare_seq_PPburst_pattern(self, nShots=None, nOffShots=None, nTimes=1):
        ## Setup sequencer for requested rate
        #sync_mark = int(self._sync_markers[self._rate])
        #leave the sync marker: assume no dropping.
        sync_mark = int(self._sync_markers[120])
        seq.sync_marker.put(sync_mark)
        seq.play_mode.put(0) # Run sequence once
        #seq.play_mode.put(1) # Run sequence N Times
        #seq.rep_count.put(nshots) # Run sequence N Times

        ff_seq = self.PPburst_sequence_pattern(nShots=nShots, nOffShots=nOffShots, nTimes=nTimes)
        seq.sequence.put_seq(ff_seq)
        
    def dumbSnake(self, xStart, xEnd, yDelta, zStart, zEnd, nRoundTrips, sweepTime):
        """ 
        simple rastering for running at 120Hz with shutter open/close before
        and after motion stop.
         
        Need some testing how to deal with intermittent motion errors.
        
        Edit June 2025: added zStart and zEnd to compensate for chips that are under an angle. Can combine this with rotation to correct for Z offset in vertical direction.
        
        Edit October 2025: edited zStart and zEnd so it compensates in the vertical direction instead of the horizontal direction for XRD+XES at MFX
        """
        zDelta = (zEnd - zStart)/nRoundTrips
        self.sam_x.umv(xStart)
        self.sam_z.umv(zStart)
        #daq.connect()
        #daq.begin()
        sleep(2)
        print('Reached horizontal start position')
        # looping through n round trips
        for i in range(nRoundTrips):
            try:
                print('starting round trip %d' % (i+1))
                sleep(1)
                pp.open()
                sleep(1)
                self.sam_x.mv(xEnd)
                #sleep(0.1)
                #pp.open()
                sleep(sweepTime)
                pp.close()
                self.sam_x.wait()
                self.sam_y.mvr(yDelta)
                self.sam_z.mvr(zDelta)
                sleep(1)#orignal was 1.2
                pp.open()
                sleep(1)
                self.sam_x.mv(xStart)
                #sleep(0.1)
                #pp.open()
                sleep(sweepTime)
                pp.close()
                self.sam_x.wait()
                self.sam_y.mvr(yDelta)
                self.sam_z.mvr(zDelta)
                #print('ypos',x.sam_y.wm())
                #sleep(2)#original was 1.2
            except:
                print('round trip %d didn not end happily' % i)
#        daq.end_run()
#        daq.disconnect()

    def dumbSnake_burst(self, xStart, xEnd, yDelta, nRoundTrips):
        """ 
        simple rastering for running at 120Hz with shutter open/close before
        and after motion stop.
         
        Need some testing how to deal with intermittent motion errors.
        """
        self.sam_x.umv(xStart)
        daq.connect()
        daq.begin()
        sleep(2)
        print('Reached horizontal start position')
        # looping through n round trips
        for i in range(nRoundTrips):
            try:
                print('starting round trip %d' % (i+1))
                self.sam_x.mv(xEnd)
                sleep(0.02)
                seq.start()
                #sleep(sweepTime)
                #pp.close()
                self.sam_x.wait()
                self.sam_y.mvr(yDelta)
                self.sam_y.wait()
                sleep(1.2)#orignal was 1
                self.sam_x.mv(xStart)
                sleep(0.02)
                #pp.open()
                #sleep(sweepTime)
                #pp.close()
                seq.start()
                self.sam_x.wait()
                self.sam_y.mvr(yDelta)
                self.sam_y.wait()
                print('ypos',x.sam_y.wm())
                sleep(1.2)#original was 1
            except:
                print('round trip %d didn not end happily' % i)
        daq.end_run()
        daq.disconnect()
    def dumbSnake_v(self, yStart, yEnd, xDelta, nRoundTrips, sweepTime):
        """ 
        simple rastering for running at 120Hz with shutter open/close before
        and after motion stop.
         
        Need some testing how to deal with intermittent motion errors.
        """
        self.sam_y.umv(yStart)
        daq.connect()
        daq.begin()
        sleep(2)
        print('Reached horizontal start position')
        # looping through n round trips
        for i in range(nRoundTrips):
            try:
                print('starting round trip %d' % (i+1))
                self.sam_y.mv(yEnd)
                sleep(0.05)
                pp.open()
                sleep(sweepTime)
                pp.close()
                self.sam_y.wait()
                self.sam_x.mvr(xDelta)
                sleep(1.2)#orignal was 1
                self.sam_y.mv(yStart)
                sleep(0.05)
                pp.open()
                sleep(sweepTime)
                pp.close()
                self.sam_y.wait()
                self.sam_x.mvr(xDelta)
                sleep(1.2)#original was 1
            except:
                print('round trip %d didn not end happily' % i)
        daq.end_run()
        daq.disconnect()




    def dumbSnake_burst_window(self,xStart,xEnd,yDelta, nRoundTrips, sweepTime,windowlist):#for burst mode
        """ 
        simple rastering for running at 120Hz with shutter open/close before
        and after motion stop.
         
        Need some testing how to deal with intermittent motion errors.
        """
        #windowList = np.zeros([numYwindow,numXwindow],dtype=object)
        
        self.sam_x.umv(xStart)
        daq.connect()
        daq.begin()
        sleep(2)
        print('Reached horizontal start position')
        # looping through n round trips
        for j in (windowList):
            self.sam_y.umv(windowList)
            self.sam_y.wait()
            print('Windos position %f'%(self.sam_w.wm()))
            for i in range(nRoundTrips):
                try:
                    print('starting round trip %d' % (i+1))
                    self.sam_x.mv(xEnd)
                    sleep(0.05)
                    seq.start()#start sequence Need to be set 
                    #sleep(sweepTime)
                    #pp.close()
                    self.sam_x.wait()
                    self.sam_y.mvr(yDelta)
                    sleep(1)#wait for turning around 
                    self.sam_x.mv(xStart)
                    sleep(0.05)
                    #pp.open()
                    seq.start()#start sequence 
                    #sleep(sweepTime)
                    #pp.close()
                    self.sam_x.wait()
                    self.sam_y.mvr(yDelta)
                    sleep(1)
                except:
                    print('round trip %d didn not end happily' % i)
        daq.end_run()
        daq.disconnect()

    def dumbSnake_burst_window_dev(self, xStart, xEnd, yDelta, nRoundTrips, sweepTime,windowList,startgrid):#for burst mode
        """ 
        simple rastering for running at 120Hz with shutter open/close before
        and after motion stop.
        sleeptime is the pp close time between window 
        Need some testing how to deal with intermittent motion errors.
        """
        self.sam_x.umv(xStart)
        self.sam_y.umv(windowList[startgrid])
        daq.connect()
        daq.begin()
        sleep(2)
        print('Reached horizontal start position')
        # looping through n round trips
        
        for j in range(len(windowList)-startgrid):
            self.sam_y.umv(windowList[startgrid+j])
            self.sam_y.wait()
            print('Window position %f'%(self.sam_y.wm()))

            for i in range(nRoundTrips):
                try:
                    print('starting round trip %d' % (i+1))
                    self.sam_x.mv(xEnd)
                    sleep(0.1)
                    seq.start()#start sequence Need to be set 
                    #sleep(sweepTime)
                    #pp.close()
                    self.sam_x.wait()
                    self.sam_y.mvr(yDelta)
                    print('yposition',self.sam_y.wm())
                    sleep(1.2)#wait for turning around 
                    self.sam_x.mv(xStart)
                    sleep(0.1)
                    #pp.open()
                    seq.start()#start sequence 
                    #sleep(sweepTime)
                    #pp.close()
                    self.sam_x.wait()
                    self.sam_y.mvr(yDelta)
                    print('yposition',self.sam_y.wm())
                    sleep(1.2)
                except:
                    print('round trip %d didn not end happily' % i)
                 
        daq.end_run()
        daq.disconnect()


    def dumbSnake_burst_dev(self, xStart, xEnd, yDelta, nRoundTrips, sweepTime,windowList,startgrid,mergin = 0.3):#for burst mode
        """ 
        simple rastering for running at 120Hz with shutter open/close before
        and after motion stop.
        sleeptime is the pp close time between window 
        Need some testing how to deal with intermittent motion errors.
        """
        self.sam_x.umv(xStart-mergin)#make the mergin for the acceleration
        self.sam_y.umv(windowList[startgrid])# go to the grid we want to start
        daq.connect()
        daq.begin()
        sleep(2)
        print('Reached horizontal start position')
        # looping through n round trips
        if(xEnd < xStart):
            mergin = mergin *(-1)
        for j in range(len(windowList)-startgrid):
            self.sam_y.umv(windowList[startgrid+j])
            self.sam_y.wait()
            print('Windos position %f'%(self.sam_y.wm()))

            for i in range(nRoundTrips):
                try:
                    print('starting round trip %d' % (i+1))
                    self.sam_x.mv(xEnd+mergin)
                    sleep(0.3)#wait for mergin and getting the constant velocity
                    seq.start()#start sequence Need to be set 
                    #sleep(sweepTime)
                    #pp.close()
                    self.sam_x.wait()
                    self.sam_y.mvr(yDelta)
                    print('yposition',self.sam_y.wm())
                    sleep(1.2)#wait for turning around 
                    self.sam_x.mv(xStart-mergin)
                    sleep(0.3)
                    #pp.open()
                    seq.start()#start sequence 
                    #sleep(sweepTime)
                    #pp.close()
                    self.sam_x.wait()
                    self.sam_y.mvr(yDelta)
                    print('yposition',self.sam_y.wm())
                    sleep(1.2)
                except:
                    print('round trip %d didn not end happily' % i)
                 
        daq.end_run()
        daq.disconnect()

        #daq.end()

    #def run_serp_seq_scan_expl(self, yStart, yStop, ySteps, flyStart, flyStop, deltaT_shots, record=False, pp_shot_delay=1):
    #    daq.disconnect() #make sure we start from fresh point.
    #    self.setupSequencer(foil_y, abs(flyStop-flyStart), deltaT_shots, pp_shot_delay=pp_shot_delay)
    #    daq.configure(-1, record=record, controls=[foil_x, foil_y])
        #daq.begin(-1)
            
    #    if isinstance(ySteps, int):
    #         RE(serp_seq_scan(foil_x, np.linspace(yStart, yStop, ySteps), foil_y, [flyStart, flyStop], seq))
    #    else:
    #         RE(serp_seq_scan(foil_x, np.arange(yStart, yStop, ySteps), foil_y, [flyStart, flyStop], seq))
     #   #daq.end()

### Sandra test

#    def autorun(self, sample_name='?', run_length=300, record=True, runs=5, delay=5, picker=None):
#        """
#        Automate runs (no quotes ever!)
#    
#        Parameters
#        ----------
#        sample_name: str, optional
#            Sample Name
#    
#        run_length: int, optional
#            number of seconds for run 300 is default
#
#        record: bool, optional
#            set True to record
#
#        runs: int, optional
#            number of runs 5 is default
#
#        delay: int, optional
#            delay time between runs. Default is 5 second but increase if the DAQ is being slow.
#
#        picker: str, optional
#            If 'open' it opens pp before run starts. If 'flipflop' it flipflops before run starts
#
#        Operations
#        ----------
#
#        """
#        from time import sleep
#        from cxi.db import cxi_pulsepicker as pp 
#        from cxi.db import daq, elog
#        import sys
#
#        if picker=='open':
#            pp.open()
#        if picker=='flipflop':
#            pp.flipflop()
#        try:
#            for i in range(runs):
#                print(f"Run Number: {daq.run_number() + 1}, Sample: {sample_name}")
#                daq.begin(duration = run_length, record = record, wait = True, end_run = True)
#                if record:
#                        elog.post(f"Sample: {sample_name}", run=(daq.run_number()))
#                sleep(delay)
#            pp.close()
#            daq.end_run()
#            daq.disconnect()

#        except KeyboardInterrupt:
#            print(f"[*] Stopping Run {daq.run_number()} and exiting",'\n')
#            pp.close()
#            daq.stop()
#            daq.disconnect()
#            sys.exit()



