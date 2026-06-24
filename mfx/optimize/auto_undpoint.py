"""
Start from a beam already visible on the YAG. Scan along the diagonal to get the
slope (px of centroid per um of undulator), then Newton-step the centroid onto
the goal.
"""
import numpy as np

from bluesky import RunEngine
from bluesky.callbacks.best_effort import BestEffortCallback
from bluesky.preprocessors import run_wrapper
import bluesky.plan_stubs as bps

from mfx.optimize.devices import YagWithCentroid
from mfx.optimize.beamline_hw import init_devices, sim_devices

YAG_PV = {"dg1": "MFX:GIGE:DG1:YAG:", "dg2": "MFX:GIGE:DG2:YAG:", "xcs1": "XCS:GIGE:YAG1:"}


def optimize_undulator_pointing(diagnostic="dg1", probe=20.0, points=5, num_frames=10,
                                tol=5.0, max_step=50.0, max_iter=5, sim=False):
    """Align the undulator pointing so the beam centroid reaches the YAG goal marker.

    Parameters
    ----------
    diagnostic : str
        YAG diagnostic to align on; one of "dg1", "dg2", "xcs1".
    probe : float
        Half-range of the diagonal calibration scan, in microns.
    points : int
        Number of points sampled across the calibration scan.
    num_frames : int
        Camera frames averaged per centroid measurement.
    tol : float
        Convergence threshold; iteration stops once the centroid is within this
        many pixels of the goal.
    max_step : float
        Maximum magnitude of a single correction, in microns. Bounds the move so
        an erroneous calibration cannot drive the undulator off target.
    max_iter : int
        Maximum number of correction iterations before returning.
    sim : bool
        If True, run against simulated devices instead of live hardware.

    Returns
    -------
    tuple of float
        The final undulator (x, y) position, in microns.
    """
    if sim:
        devs = sim_devices()
        yag = devs[f"mfx_{diagnostic}_yag"]
    else:
        devs = init_devices(force=True)
        yag = YagWithCentroid(YAG_PV[diagnostic], name=f"mfx_{diagnostic}_yag")
    und = devs["und_abs"]
    yag.image1.kind = "omitted"
    yag.num_frames = num_frames
    und.delta_xy.kind = "omitted"
    goal_x, goal_y = yag.coords.standard_two_corners_target()

    # calibrate: diagonal scan, slope = px per um
    ts, cxs, cys = [], [], []

    def scan():
        prev = 0.0
        for t in np.linspace(-probe, probe, points):
            yield from bps.mv(und.delta_xy, (t - prev, t - prev))
            prev = t
            r = yield from bps.trigger_and_read([und, yag])
            ts.append(t)
            cxs.append(r[yag.centroid_x.name]["value"])
            cys.append(r[yag.centroid_y.name]["value"])
        yield from bps.mv(und.delta_xy, (-prev, -prev))

    RE = RunEngine({})
    RE.subscribe(BestEffortCallback())
    RE(run_wrapper(scan()))
    calib_x, calib_y = np.polyfit(ts, cxs, 1)[0], np.polyfit(ts, cys, 1)[0]
    print(f"calib: {calib_x:.3f}, {calib_y:.3f} px/um")

    # correct: Newton steps until on goal
    for i in range(max_iter):
        yag.trigger()
        ex, ey = yag.centroid_x.get() - goal_x, yag.centroid_y.get() - goal_y
        print(f"  iter {i + 1}: err=({ex:.1f}, {ey:.1f})")
        if abs(ex) < tol and abs(ey) < tol:
            break
        und.delta_xy.move((float(np.clip(-ex / calib_x, -max_step, max_step)),
                           float(np.clip(-ey / calib_y, -max_step, max_step))), wait=True)
    return tuple(und.position)
