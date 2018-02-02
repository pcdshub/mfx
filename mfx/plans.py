from bluesky.plan_stubs import open_run, mv, close_run

from hutch_python import hutch
from .beamline import tfs_trans


def tfs_scan(start, stop, min_energy=None):
    hutch.daq.configure(always_on=True)
    yield from open_run()
    yield from mv(tfs_trans, start)
    yield from mv(tfs_trans, stop)
    yield from close_run()
