from collections import defaultdict
import time

import bluesky.plan_stubs as bps
import bluesky.preprocessors as bpp
from ophyd.device import Device, Component as Cpt
from ophyd.signal import EpicsSignal
from scipy.constants import speed_of_light

from pcdsdaq.preprocessors import daq_during_wrapper
from pcdsdevices.interface import BaseInterface

def delay_scan(daq, time_motor, time_points, sweep_time, duration=None, 
               record=None, use_l3t=False, controls=None):
    """
    Bluesky plan that sets up and executes the delay scan.

    Parameters
    ----------
    daq: Daq
        The daq

    time_motor: DelayNewport
        The movable device in seconds

    time_points: list of float
        The times in second to move between

    sweep_time: float
        The duration we take to move from one end of the range to the other.

    record: bool, optional
        Whether or not to record in the daq

    duration: float, optional
        If provided, the time to run in seconds. If omitted, we'll run forever.

    use_l3t: bool, optional
        If True, events argument will be interpreted to only count events that
        pass the level 3 trigger

    controls: dict or list of devices, optional
        If provided, values will make it to DAQ data stream as variables
    """

    spatial_pts = []
    for time_pt in time_points:
        pseudo_tuple = time_motor.PseudoPosition(delay=time_pt)
        real_tuple = time_motor.forward(pseudo_tuple)
        spatial_pts.append(real_tuple.motor)

    space_delta = abs(spatial_pts[0] - spatial_pts[1])
    velo = space_delta/sweep_time

    yield from bps.abs_set(time_motor.motor.velocity, velo)

    scan = infinite_scan([], time_motor, time_points, duration=duration)

    if daq is not None:
        yield from daq_during_wrapper(scan, record=record, use_l3t=use_l3t,
                                      controls=controls)
    else:
        yield from scan


# def delay_scan(daq, raw_motor, points, sweep_time):
#     """
#     Bluesky plan that sets up and executes the delay scan.
# 
#     Parameters
#     ----------
#     daq: Daq
#         The daq
# 
#     raw_motor: Newport
#         The movable device in mm
# 
#     points: list of float
#         The times in second to move between
# 
#     sweep_time: float
#         The duration we take to move from one end of the range to the other.
#     """
#     conv = (speed_of_light / 2) * 1000 # mm/s, 2 bounces
# 
#     # Figure out the velocity
#     # First, we need to check what the distance is given the time points
#     time_delta = abs(points[0] - points[1])
#     space_delta = time_delta * conv
#     velo = space_delta/sweep_time
# 
#     yield from bps.abs_set(raw_motor.velocity, velo)
# 
#     space_points = [pt * conv for pt in points]
# 
#     scan = infinite_scan([], raw_motor, space_points)
# 
#     if daq is not None:
#         yield from daq_during_wrapper(scan)
#     else:
#         yield from scan


def infinite_scan(detectors, motor, points, duration=None,
                  per_step=None, md=None):
    """
    Bluesky plan that moves a motor among points until interrupted.

    Parameters
    ----------
    detectors: list of readables
        Objects to read into Python in the scan.

    motor: settable
        Object to move in the scan.

    points: list of floats
        Positions to move between in the scan.

    duration: float
        If provided, the time to run in seconds. If omitted, we'll run forever.
    """
    if per_step is None:
        per_step = bps.one_nd_step

    if md is None:
        md = {}

    md.update(motors=[motor.name])
    start = time.time()

    #@bpp.stage_decorator(list(detectors) + [motor])
    @bpp.reset_positions_decorator()
    @bpp.run_decorator(md=md)
    def inner():
        # Where last position is stored
        pos_cache = defaultdict(lambda: None)
        while duration is None or time.time() - start < duration:
            for pt in points:
                step = {motor: pt}
                yield from per_step(detectors, step, pos_cache)

    return (yield from inner())


class USBEncoder(BaseInterface, Device):
    tab_component_names = True
    zero = Cpt(EpicsSignal, ':ZEROCNT')
    pos = Cpt(EpicsSignal, ':POSITION')
    scale = Cpt(EpicsSignal, ':SCALE')
    offset = Cpt(EpicsSignal, ':OFFSET')
    def set_zero(self):
       self.zero.put(1)
