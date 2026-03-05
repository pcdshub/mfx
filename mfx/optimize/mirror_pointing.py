from bluesky import RunEngine
from bluesky.callbacks.best_effort import BestEffortCallback
from bluesky.callbacks import LiveFit, LiveFitPlot
from lmfit.models import LinearModel
import bluesky.plans as bp
import bluesky.plan_stubs as bps
from epics import caget

from mfx.optimize.devices import YagWithCentroid
from mfx.optimize.beamline_hw import init_devices


def optimize_mirror_pointing(instrument="mfx", diagnostic="MFX:GIGE:DG1:YAG:", window=5.0, num_frames=10, num_points=10, sim=False, mec_goal=(296, 228)):
    """
    Scan the MR1L4 mirror pitch and fit beam centroid to find the optimal position.

    Parameters
    ----------
    instrument : str
        Instrument name, "mfx" or "mec".
    diagnostic : str
        PV prefix for the YAG camera.
        MFX: "MFX:GIGE:DG1:YAG:" or "MFX:GIGE:DG2:YAG:"
        MEC: "MEC:GIGE:13:" (MEC_YAG3), "MEC:GIGE:14:" (MEC_YAG1), or "MEC:GIGE:44:" (MEC_YAG2)
    window : float
        Half-width of the scan range around the nominal position, in urad.
    num_frames : int
        Number of frames to average per centroid measurement.
    num_points : int
        Number of scan points across the window.
    sim : bool
        If True, use a simulated mirror instead of real hardware.
    mec_goal : tuple[int, int]
        Hardcoded centroid goal (x, y) to use when instrument == "mec".

    Returns
    -------
    float
        The mirror pitch position the mirror was moved to.
    """
    if sim:
        from mfx.optimize.beamline_hw import sim_devices
        mirror = sim_devices()["mr1l4_homs"].pitch
    else:
        devices = init_devices(force=True)
        mirror = devices["mr1l4_homs"].pitch

    yag = YagWithCentroid(diagnostic, name=f"{instrument}_yag")
    yag.image1.kind = "omitted"
    yag.num_frames = num_frames

    pv = "MR1L4:PITCH:MFX:Coating1" if instrument == "mfx" else "MR1L4:PITCH:MEC:Coating1"
    nominal = caget(pv)

    if instrument == "mec":
        goal = mec_goal
    else:
        goal = yag.coords.standard_two_corners_target()

    RE = RunEngine({})
    RE.subscribe(BestEffortCallback())

    goal_x, goal_y = goal

    lf_x = LiveFit(LinearModel(), f"{yag.name}_centroid_x", {"x": mirror.name})
    lf_y = LiveFit(LinearModel(), f"{yag.name}_centroid_y", {"x": mirror.name})
    lfp_x = LiveFitPlot(lf_x, color="r")
    lfp_y = LiveFitPlot(lf_y, color="b")

    start = nominal - window
    stop = nominal + window
    RE(bp.scan([yag], mirror, start, stop, num_points), [lfp_x, lfp_y])
    solution_x = (goal_x - lf_x.result.params["intercept"].value) / lf_x.result.params["slope"].value
    solution_y = (goal_y - lf_y.result.params["intercept"].value) / lf_y.result.params["slope"].value

    if abs(lf_x.result.params["slope"].value) >= abs(lf_y.result.params["slope"].value):
        solution = solution_x
        print(f"Using x fit, solution={solution:.3f}")
    else:
        solution = solution_y
        print(f"Using y fit, solution={solution:.3f}")

    RE(bps.mv(mirror, solution))
    print(f"Moved mirror to {solution:.3f}")
    return solution