"""
To run for real, import get_xopt_obj and try to random_evaluate() and step() the Xopt object.
To test with sim, ipython -i mfx/optimize/xopt_scans.py for an interactive test
Or python -m mfx.optimize.xopt_scans for a default sim run-through
"""
from __future__ import annotations

import matplotlib.pyplot as plt
from xopt import VOCS, Evaluator, Xopt
from xopt.generators.bayesian import ExpectedImprovementGenerator

from mfx.optimize.mirror_hw import MIRROR_NOMINAL, DG1_WAVE8_XPOS, DG2_WAVE8_XPOS, init_devices, sim_devices


def get_vocs(
    mirror_nominal: float = MIRROR_NOMINAL,
    search_delta: float = 5,
    wave8_max_value: float = 10,
) -> VOCS:
    return VOCS(
        variables={
            "mirror_pitch": [mirror_nominal - search_delta, mirror_nominal + search_delta]
        },
        objectives={
            "objective": "MINIMIZE",
        },
        constraints={
            "abs_xpos": ["LESS_THAN", wave8_max_value],
        },
    )


def get_evaluator(
    wave8: str = "dg1",
    wave8_xpos: float | None = None,
) -> Evaluator:
    if wave8_xpos is None:
        if wave8 == "dg1":
            wave8_xpos = DG1_WAVE8_XPOS
        elif wave8 == "dg2":
            wave8_xpos = DG2_WAVE8_XPOS
        else:
            raise ValueError(f"Invalid wave8 {wave8}, expected dg1 or dg2")

    def evaluate(input: dict[str, float]) -> dict[str, float]:
        print(f"Trying {input['mirror_pitch']}")
        devices = init_devices()
        devices["mr1l4_homs"].pitch.set(input["mirror_pitch"]).wait(timeout=20)
        xpos_device = devices[f"mfx_{wave8}_wave8"].xpos
        xpos_device.trigger().wait(timeout=10)
        xpos = xpos_device.get()
        results = {}
        results["xpos"] = xpos
        results["abs_xpos"] = abs(xpos)
        results["objective"] = abs(xpos - wave8_xpos)
        return results

    return Evaluator(function=evaluate)


def get_xopt_obj(
    wave8: str = "dg1",
    mirror_nominal: float = MIRROR_NOMINAL,
    search_delta: float = 5,
    wave8_xpos: float | None = None,
    wave8_max_value: float = 10,
) -> Xopt:
    """
    Create an appropriate xopt optimization object.

    When you have this object, it can be used to optimize the position of
    the MFX flat mirror.

    xopt.random_evaluate(3)
    xopt.step()
    xopt.step()
    etc.

    Parameters
    ----------
    wave8 : str
        Whether to use the dg1 or dg2 wave8
    mirror_nominal : float
        The starting mirror pitch position and midpoint of the optimization search.
    search_delta : float
        How far +/- we check away from the mirror nominal pitch position
    wave8_xpos : float
        The goal x position on the wave8
    wave8_max_value : float
        The maximum absolute wave8 value that is considered "reasonable".
    """
    vocs = get_vocs(
        mirror_nominal=mirror_nominal,
        search_delta=search_delta,
        wave8_max_value=wave8_max_value,
    )
    evaluator = get_evaluator(
        wave8=wave8,
        wave8_xpos=wave8_xpos,
    )
    generator = ExpectedImprovementGenerator(vocs=vocs)
    generator.gp_constructor.use_low_noise_prior = False
    return Xopt(
        vocs=vocs,
        generator=generator,
        evaluator=evaluator,
    )


def setup_sim_test() -> None:
    """
    Prep offline test without using mfx hardware or mfx3 startup script
    """
    plt.ion()
    print("Creating sim devices")
    globals().update(**sim_devices())
    print(f"devices: {list(init_devices().keys())}")
    print("Xopt factory: get_xopt_obj")
    print("Canned test: run_sim_test")


def run_sim_test() -> Xopt:
    print("Create Xopt")
    xopt = get_xopt_obj()
    print("Randomly evaluate 3 points")
    xopt.random_evaluate(3)
    print("Step xopt object 10 times")
    for num in range(10):
        print(f"Step {num + 1}")
        xopt.step()
    print("Get best point")
    _, val, params = xopt.vocs.select_best(xopt.data)
    print(f"Best objective value {val}")
    print(f"Best point {params}")
    print("Move to best point")
    mirror_pitch = init_devices()["mr1l4_homs"].pitch
    mirror_pitch.set(params["mirror_pitch"]).wait(timeout=20)
    print(f"pitch is at {mirror_pitch.position}")
    print("Generating plots")
    xopt.data.plot(y=xopt.vocs.objective_names)
    return xopt


if __name__ == "__main__":
    from IPython import get_ipython
    ip = get_ipython()
    if ip is not None:
        ip.run_line_magic("matplotlib", "qt")
    setup_sim_test()
    if ip is None:
        # If we're not using ipython, just run the canned sim test
        # Otherwise we'll set up and then do nothing
        run_sim_test()
