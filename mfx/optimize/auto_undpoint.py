from bluesky import RunEngine
from bluesky.callbacks.best_effort import BestEffortCallback
from bluesky.preprocessors import run_wrapper
import bluesky.plan_stubs as bps
import numpy as np

from mfx.optimize.devices import YagWithCentroid
from mfx.optimize.beamline_hw import init_devices


UNDULATOR_CONFIG = {
    "xcs1": {"x": (0, 200),    "y": (-450, -200), "pv": "XCS:GIGE:YAG1:"},
    "dg1":  {"x": (-100, 150), "y": (-750, -350), "pv": "MFX:GIGE:DG1:YAG:"},
    "dg2":  {"x": (-100, 150), "y": (-750, -350), "pv": "MFX:GIGE:DG2:YAG:"},
}


def optimize_undulator_pointing(
    diagnostic="dg1",
    mode="lscan",
    grid_points=5,
    window=20.0,
    num_frames=10,
    sim=False,
    safe=False,
):
    if diagnostic not in UNDULATOR_CONFIG:
        raise ValueError(
            f"Unknown diagnostic '{diagnostic}', expected one of {list(UNDULATOR_CONFIG)}"
        )

    config = UNDULATOR_CONFIG[diagnostic]

    if sim:
        from mfx.optimize.beamline_hw import sim_devices
        devs = sim_devices()
        und = devs["und_abs"]
        yag = devs[f"mfx_{diagnostic}_yag"]
    else:
        devs = init_devices(force=True)
        if safe:
            und = globals().get("und_abs_safe")
            if und is None:
                raise NameError("safe=True but und_abs_safe is not defined in globals().")
        else:
            und = devs["und_abs"]
        yag = YagWithCentroid(config["pv"], name=f"mfx_{diagnostic}_yag")

    yag.image1.kind = "omitted"
    yag.num_frames = num_frames
    und.delta_xy.kind = "omitted"

    goal_x, goal_y = yag.coords.standard_two_corners_target()

    RE = RunEngine({})
    RE.subscribe(BestEffortCallback())

    scan_data = {"ux": [], "uy": [], "cx": [], "cy": []}

    def collect(name, doc):
        if name == "event":
            d = doc["data"]
            scan_data["ux"].append(d[und.xpos.name])
            scan_data["uy"].append(d[und.ypos.name])
            scan_data["cx"].append(d[f"{yag.name}_centroid_x"])
            scan_data["cy"].append(d[f"{yag.name}_centroid_y"])

    if mode == "lscan":
        cur_x, cur_y = und.position

        def scan_plan():
            for x in np.linspace(cur_x - window, cur_x + window, grid_points):
                yield from bps.mv(und, (x, cur_y))
                yield from bps.trigger_and_read([und, yag])
            for y in np.linspace(cur_y - window, cur_y + window, grid_points):
                yield from bps.mv(und, (cur_x, y))
                yield from bps.trigger_and_read([und, yag])

    elif mode == "grid":
        if config["x"] is None or config["y"] is None:
            raise ValueError(f"Undulator ranges for '{diagnostic}' have not been determined yet.")
        x_vals = np.linspace(*config["x"], grid_points)
        y_vals = np.linspace(*config["y"], grid_points)

        def scan_plan():
            for i, x in enumerate(x_vals):
                row = y_vals if i % 2 == 0 else y_vals[::-1]
                for y in row:
                    yield from bps.mv(und, (x, y))
                    yield from bps.trigger_and_read([und, yag])

    else:
        raise ValueError(f"Unknown mode '{mode}', expected 'lscan' or 'grid'")

    RE(run_wrapper(scan_plan()), collect)

    cx_arr = np.array(scan_data["cx"])
    cy_arr = np.array(scan_data["cy"])
    ux_arr = np.array(scan_data["ux"])
    uy_arr = np.array(scan_data["uy"])

    valid = ~(np.isnan(cx_arr) | np.isnan(cy_arr))
    if valid.sum() < 3:
        raise RuntimeError(
            f"Too few valid centroid readings ({valid.sum()}) to fit a model — beam may be off camera for most of the scan range."
        )

    A = np.column_stack([np.ones(valid.sum()), ux_arr[valid], uy_arr[valid]])
    cx = np.linalg.lstsq(A, cx_arr[valid], rcond=None)[0]
    cy = np.linalg.lstsq(A, cy_arr[valid], rcond=None)[0]

    print(f"centroid_x = {cx[0]:.2f} + {cx[1]:.4f}*ux + {cx[2]:.4f}*uy")
    print(f"centroid_y = {cy[0]:.2f} + {cy[1]:.4f}*ux + {cy[2]:.4f}*uy")

    M = np.array([[cx[1], cx[2]], [cy[1], cy[2]]])
    rhs = np.array([goal_x - cx[0], goal_y - cy[0]])
    sol = np.linalg.solve(M, rhs)

    print(f"Solution: undp_x={sol[0]:.2f}, undp_y={sol[1]:.2f}")

    und.move((sol[0], sol[1]), wait=True)
    print(f"Moved undulator to ({sol[0]:.2f}, {sol[1]:.2f})")

    return (sol[0], sol[1])
