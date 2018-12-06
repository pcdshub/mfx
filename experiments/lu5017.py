import os
import time
import os.path
import logging
import subprocess

import numpy as np

from mfx.devices import LaserShutter
from mfx.db import daq, elog, sequencer, rayonix
from ophyd.status import wait as status_wait
from pcdsdevices.sequencer import EventSequencer
from pcdsdevices.evr import Trigger

# WAIT A WHILE FOR THE DAQ TO START
import pcdsdaq.daq
pcdsdaq.daq.BEGIN_TIMEOUT = 5


logger = logging.getLogger(__name__)


###########################
# Configuration Functions #
###########################

class User:
    """Generic User Object"""
    sequencer = sequencer
    # Use our standard Rayonix sequences
    configure_sequencer = rayonix.configure_sequencer

    @property
    def current_rate(self):
        """Current configured EventSequencer rate"""
        return rayonix.current_rate

    ######################
    # Scanning Functions #
    ######################
    def perform_run(self, events, record=True, comment='', post=True):
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
        """
        # Create descriptive message
        comment = comment or ''
        # Start recording
        logger.info("Starting DAQ run, -> record=%s", record)
        daq.begin(events=events, record=record)
        # Post to ELog if desired
        runnum = daq._control.runnumber()
        info = [runnum, comment, events, self.current_rate]
        post_msg = post_template.format(*info)
        print(post_msg)
        if post and record:
            elog.post(post_msg, run=runnum)
        # Wait for the DAQ to finish
        logger.info("Waiting or DAQ to complete %s events ...", events)
        daq.wait()
        logger.info("Run complete!")
        daq.end_run()
        logger.debug("Stopping Sequencer ...")


    def loop(self, events=3000, nruns=1, record=True, comment='', post=True):
        """
        Perform a series of runs

        Parameters
        ----------
        events: int, optional
            Number of events to sample for each run

        nruns: int, optional
            Number of iterations to run requested delays

        record: bool, optional
            Choice to record or not

        comment: str, optional
            Comment for ELog

        post : bool, optional
            Whether to post to ELog or not. Will not post if not recording.
        """
        try:
            for irun in range(nruns):
                run = irun+1
                logger.info("Beginning run %s of %s", run, nruns)
                self.perform_run(events, record=record,
                                 post=post, comment=comment)
            logger.info("All requested scans completed!")
        except KeyboardInterrupt:
            logger.warning("Scan interrupted by user request!")
            logger.info("Stopping DAQ ...")
            daq.stop()
        # Return the DAQ to the original state
        finally:
            logger.info("Disconnecting from DAQ ...")
            daq.disconnect()


post_template = """\
Run Number: {} {}

Acquiring {} events at {} Hz
"""

