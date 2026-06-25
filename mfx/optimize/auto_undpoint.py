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

YAG_PV = {"dg1": "MFX:GIGE:DG1:YAG:", "dg2": "MFX:GIGE:DG2:YAG:",
          "xcs1": "XCS:GIGE:YAG1:", "im3l0": "IM3L0:PPM:CAM:"}

_SIM_YAG = {"dg1": "mfx_dg1_yag", "dg2": "mfx_dg2_yag",
            "xcs1": "xcs_yag1", "im3l0": "mfx_dg1_yag"}


def align_with_undulator(diagnostic="dg1", probe=20.0, points=5, num_frames=10,
                         tol=5.0, max_step=50.0, max_iter=5, sim=False):
    """Align the beam onto a chosen diagnostic by steering horizontally with undp_x
    and vertically with undp_y.

    Parameters
    ----------
    diagnostic : str
        YAG diagnostic to align on; one of "dg1", "dg2", "xcs1", "im3l0".
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
        yag = devs[_SIM_YAG[diagnostic]]
    else:
        devs = init_devices(force=True)
        yag = YagWithCentroid(YAG_PV[diagnostic], name=f"mfx_{diagnostic}_yag")
    und = devs["und_abs"]
    yag.image1.kind = "omitted"
    yag.num_frames = num_frames
    und.delta_xy.kind = "omitted"
    goal_x, goal_y = yag.coords.standard_two_corners_target()
    print(f"goal: ({goal_x:.1f}, {goal_y:.1f})")

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


def align_with_mirror_and_undulator(pitch_window=5.0, undp_window=20.0, points=5,
                                    num_frames=10, tol=5.0, max_iter=5, sim=False):
    """Align the beam onto IM3L0 by steering horizontally with the MR1L4 pitch
    and vertically with the undulator undp_y.

    Parameters
    ----------
    pitch_window : float
        Half-range of the MR1L4 pitch calibration scan, in microradians.
    undp_window : float
        Half-range of the undp_y calibration scan, in microns.
    points : int
        Number of points sampled across each calibration scan.
    num_frames : int
        Camera frames averaged per centroid measurement.
    tol : float
        Convergence threshold; iteration stops once the centroid is within this
        many pixels of the goal.
    max_iter : int
        Maximum number of correction iterations per axis before returning.
    sim : bool
        If True, run against simulated devices instead of live hardware.

    Returns
    -------
    tuple of float
        The final (cx, cy) beam centroid on IM3L0, in pixels.
    """
    if sim:
        devs = sim_devices()
        yag = devs[_SIM_YAG["im3l0"]] 
    else:
        devs = init_devices(force=True)
        yag = YagWithCentroid(YAG_PV["im3l0"], name="im3l0_yag")
    und = devs["und_abs"]
    pitch = devs["mr1l4_homs"].pitch
    yag.image1.kind = "omitted"
    yag.num_frames = num_frames
    und.delta_xy.kind = "omitted"
    goal_x, goal_y = yag.coords.standard_two_corners_target()
    print(f"goal: ({goal_x:.1f}, {goal_y:.1f})")

    # horizontal: scan the MR1L4 pitch, slope = px of cx per urad
    ps, cxs = [], []

    def pitch_scan():
        prev = 0.0
        for p in np.linspace(-pitch_window, pitch_window, points):
            yield from bps.mvr(pitch, p - prev)
            prev = p
            r = yield from bps.trigger_and_read([pitch, yag])
            ps.append(p)
            cxs.append(r[yag.centroid_x.name]["value"])
        yield from bps.mvr(pitch, -prev)

    RE = RunEngine({})
    RE.subscribe(BestEffortCallback())
    RE(run_wrapper(pitch_scan()))
    calib_x = np.polyfit(ps, cxs, 1)[0]
    print(f"horizontal calib: {calib_x:.3f} px/urad")

    for i in range(max_iter):
        yag.trigger()
        ex = yag.centroid_x.get() - goal_x
        print(f"  horizontal iter {i + 1}: err={ex:.1f}")
        if abs(ex) < tol:
            break
        pitch.set(pitch.position + float(np.clip(-ex / calib_x, -pitch_window, pitch_window))).wait()

    # vertical: scan undp_y, slope = px of cy per um
    us, cys = [], []

    def undp_scan():
        prev = 0.0
        for u in np.linspace(-undp_window, undp_window, points):
            yield from bps.mv(und.delta_xy, (0.0, u - prev))
            prev = u
            r = yield from bps.trigger_and_read([und, yag])
            us.append(u)
            cys.append(r[yag.centroid_y.name]["value"])
        yield from bps.mv(und.delta_xy, (0.0, -prev))

    RE = RunEngine({})
    RE.subscribe(BestEffortCallback())
    RE(run_wrapper(undp_scan()))
    calib_y = np.polyfit(us, cys, 1)[0]
    print(f"vertical calib: {calib_y:.3f} px/um")

    for i in range(max_iter):
        yag.trigger()
        ey = yag.centroid_y.get() - goal_y
        print(f"  vertical iter {i + 1}: err={ey:.1f}")
        if abs(ey) < tol:
            break
        und.delta_xy.move((0.0, float(np.clip(-ey / calib_y, -undp_window, undp_window))), wait=True)

    return (yag.centroid_x.get(), yag.centroid_y.get())
