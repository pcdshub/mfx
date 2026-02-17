from bluesky import RunEngine
from bluesky.callbacks.best_effort import BestEffortCallback
import bluesky.plans as bp
import bluesky.plan_stubs as bps
import numpy as np

from mfx.optimize.devices import YagWithCentroid
from mfx.optimize.beamline_hw import init_devices


UNDULATOR_CONFIG = {
    "xcs1": {"x": (0, 200), "y": (-450, -200), "pv": "XCS:GIGE:YAG1:"},
    "dg1":  {"x": (-100, 150), "y": (-750, -350), "pv": "MFX:GIGE:DG1:YAG:"},
    "dg2":  {"x": None, "y": None, "pv": "MFX:GIGE:DG2:YAG:"},
}


def optimize_undulator_pointing(
    diagnostic="dg1",
    grid_points=5,
    num_frames=10,
    sim=False,
    safe=False,
):
    if diagnostic not in UNDULATOR_CONFIG:
        raise ValueError(
            f"Unknown diagnostic '{diagnostic}', expected one of {list(UNDULATOR_CONFIG)}"
        )

    config = UNDULATOR_CONFIG[diagnostic]
    if config["x"] is None or config["y"] is None:
        raise ValueError(f"Undulator ranges for '{diagnostic}' have not been determined yet.")

    if sim:
        from mfx.optimize.beamline_hw import sim_devices
        devs = sim_devices()
        und = devs["und_abs"]
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

    RE(
        bp.grid_scan(
            [yag],
            und.xpos, *config["x"], grid_points,
            und.ypos, *config["y"], grid_points,
            snake_axes=True,
        ),
        collect,
    )

    A = np.column_stack([np.ones(len(scan_data["ux"])), scan_data["ux"], scan_data["uy"]])
    cx = np.linalg.lstsq(A, scan_data["cx"], rcond=None)[0]
    cy = np.linalg.lstsq(A, scan_data["cy"], rcond=None)[0]

    print(f"centroid_x = {cx[0]:.2f} + {cx[1]:.4f}*ux + {cx[2]:.4f}*uy")
    print(f"centroid_y = {cy[0]:.2f} + {cy[1]:.4f}*ux + {cy[2]:.4f}*uy")

    M = np.array([[cx[1], cx[2]], [cy[1], cy[2]]])
    rhs = np.array([goal_x - cx[0], goal_y - cy[0]])
    sol = np.linalg.solve(M, rhs)

    print(f"Solution: undp_x={sol[0]:.2f}, undp_y={sol[1]:.2f}")

    RE(bps.mv(und.xpos, sol[0], und.ypos, sol[1]))
    print(f"Moved undulator to ({sol[0]:.2f}, {sol[1]:.2f})")

    return (sol[0], sol[1])
