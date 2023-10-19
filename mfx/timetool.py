"""
Contains function definitions for managing the timetool and ultrafast timing
during experiments.

Functions
----------
correct_timing_drift(amplitude_thresh: float, ipm_thresh: float,
                     drift_adjustment_thresh: float, fwhm_threshs: Tuple,
                     num_events: int, will_log: bool)
    Automate the correction of long-term drift in timing by monitoring the mean
    edge position on the timetool camera.
"""

__all__ = ["correct_timing_drift"]

import sys
import os
import socket
import logging
import time
import json
from typing import Tuple

import numpy as np

logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)

def write_log(msg: str, logfile: str = "") -> None:
    """
    Log messages both via the standard logger and optionally to a file.
    """
    timestamped_msg: str =f"[{time.ctime()}] {msg}"
    logger.info(timestamped_msg)

    if logfile:
        with open(logfile, "a") as f:
            f.write(timestamped_msg)

def is_good_measurement(
        tt_data: np.ndarray,
        amplitude_thresh: float,
        ipm_thresh: float,
        fwhm_threshs: Tuple[float, float]
):
    timetool_amp: float = tt_data[2]
    ipm_dg2: float = tt_data[8]
    fwhm: float = tt_data[5]

    if timetool_amp < amplitude_thresh:
        return False
    elif ipm_dg2 < ipm_thresh:
        return False
    elif fwhm < fwhm_threshs[0] or fwhm > fwhm_threshs[1]:
        return False

    return True

def correct_timing_drift(
        amplitude_thresh: float = 0.02,
        ipm_thresh: float = 500.,
        drift_adjustment_thresh: float = 0.05,
        fwhm_threshs: Tuple[float, float] = (30, 130),
        num_events: int = 61,
        will_log: bool = True
) -> None:
    """
    Automate the correction of timing drift. Will adjust the stages to
    center the timetool edge on the camera and compensate the laser delay to
    maintain the desired nominal time point. Runs in an infinite loop.

    Parameters
    ----------
    amplitude_thresh : float, optional
        The minimum amplitude of the fitted timetool peak to include the
        data point in the rolling average used for drift correction.
        Default: 0.02.
    ipm_thresh : float, optional
        The minimum ipm DG2 value to perform drift correction. Setting a
        reasonable value prevents attempts at drift correction when X-rays
        are very weak or down. Default: 500.
    drift_adjustment_thresh : float, optional
        The minimum drift value to correct for in picoseconds. E.g. a value
        of 0.05 means any time the rolling average finds that the timetool
        center is off by 50 fs in either direction it will compensate. Default:
        0.05 ps.
    fwhm_threshs : Tuple[float, float], optional
        Minimum and maximum FWHM of detected edge to consider for a timetool
        measurement as "good."
    num_events : int, optional
        The number of "good" timetool edge measurements to include in the
        rolling average. Ideally a prime number to remove effects from
        sytematic errors. Default 61 measurements.
    will_log : bool, optional
        Log timing corrections to a file.
    """
    logfile: str = ""
    if will_log:
        logfile = input("Please enter a file to log correction info to: ")

    timetool_edges: np.ndarray = np.zeros([num_events])

    write_log(f"Entering timing correction loop", logfile)
    while True:
        try:
            num_curr_edges: int = 0

            while (num_curr_edges < num_events):
                # EVENTBUILD PV contains 10 fields. TTALL makes up the first 8.
                # (indices 0-7), and IPM DG1 and DG2 makeup the final 2.
                # See `is_good_measurement` function for more accesses.
                timetool: EpicsSignal = EpicsSignal("MFX:TT:01:EVENTBUILD")
                tt_data: np.ndarray = timetool.get()

                timetool_edge_ps: float = tt_data[1]

                if is_good_measurement(
                        tt_data,
                        amplitude_thresh,
                        ipm_thresh,
                        fwhm_threshs
                ):
                    timetool_edges[num_curr_edges] = timetool_edge_ps
                    num_curr_edges += 1

                time.sleep(0.01)

            tt_edge_average_ps: float = np.mean(timetool_edges)
            write_log(f"Current average: {tt_edge_average_ps}", logfile)

            if np.abs(tt_edge_average_ps) > drift_adjustment_thresh:
                tt_average_seconds: float = -(tt_edge_average_ps*1e-12)
                write_log(
                    f"Making adjustment to {tt_average_seconds}!",
                    logfile
                )
                lxt.mvr(tt_average_seconds)

        except KeyboardInterrupt as e:
            write_log(f"Breaking out of timing correction loop", logfile)
            break
