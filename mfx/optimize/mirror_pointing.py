from bluesky import RunEngine
from bluesky.callbacks.best_effort import BestEffortCallback
from bluesky.callbacks import LiveFit, LiveFitPlot
from lmfit.models import LinearModel
import bluesky.plans as bp
import bluesky.plan_stubs as bps


def optimize_mirror_pointing(mirror, yag, nominal, goal, window_size=5.0, num_points=10):
    RE = RunEngine({})
    RE.subscribe(BestEffortCallback())

    goal_x, goal_y = goal

    lf_x = LiveFit(LinearModel(), f"{yag.name}_centroid_x", {"x": mirror.name})
    lf_y = LiveFit(LinearModel(), f"{yag.name}_centroid_y", {"x": mirror.name})
    lfp_x = LiveFitPlot(lf_x, color="r")
    lfp_y = LiveFitPlot(lf_y, color="b")

    start = nominal - window_size
    stop = nominal + window_size
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


if __name__ == "__main__":
    import argparse
    from epics import caget
    from mfx.optimize.devices import YagWithCentroid
    from mfx.optimize.beamline_hw import init_devices

    parser = argparse.ArgumentParser(description="Mirror pointing optimization")
    parser.add_argument("--instrument", "-i", choices=["mfx", "mec"], default="mfx")
    parser.add_argument("--diagnostic", "-d", type=str, required=True)
    parser.add_argument("--window", "-w", type=float, default=5.0)
    parser.add_argument("--num-frames", "-n", type=int, default=10)
    parser.add_argument("--num-points", "-p", type=int, default=10)
    args = parser.parse_args()

    devices = init_devices()
    mirror = devices["mr1l4_homs"].pitch

    yag = YagWithCentroid(args.diagnostic, num_frames=args.num_frames, name=f"{args.instrument}_yag")
    yag.image1.kind = "omitted"

    pv = "MR1L4:PITCH:MFX:Coating1" if args.instrument == "mfx" else "MR1L4:PITCH:MEC:Coating1"
    nominal = caget(pv)
    goal = yag.coords.standard_two_corners_target()

    optimize_mirror_pointing(mirror, yag, nominal, goal, args.window, args.num_points)