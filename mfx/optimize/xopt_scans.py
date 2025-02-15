"""
To run for real, import get_xopt_obj and try to random_evaluate() and step() the Xopt object.
To test with sim, ipython -i mfx/optimize/xopt_scans.py for an interactive test
Or python -m mfx.optimize.xopt_scans for a default sim run-through
"""
from __future__ import annotations

import matplotlib.pyplot as plt
from xopt import VOCS, Evaluator, Xopt
from xopt.generators.bayesian import ExpectedImprovementGenerator

from lcls_tools.common.frontend.plotting.image import plot_image_projection_fit
from lcls_tools.common.image.fit import ImageProjectionFit

from .mirror_hw import (
    DG1_WAVE8_XPOS,
    DG1_YAG_XPOS,
    DG2_WAVE8_XPOS,
    DG2_YAG_XPOS,
    IP_YAG_XPOS,
    MIRROR_NOMINAL,
    init_devices,
    sim_devices,
)


def get_vocs(
    mirror_nominal: float = MIRROR_NOMINAL,
    search_delta: float = 5,
    wave8_max_value: float | None = None,
    yag_size_min: float | None = None,
    yag_size_max: float | None = None,
    yag_intensity_min: float | None = None,
    yag_intensity_max: float | None = None,
) -> VOCS:
    constrants = {}
    if wave8_max_value is not None:
        constrants["abs_xpos"] = ["LESS_THAN", wave8_max_value]
    if yag_size_min is not None:
        constrants["rms_size_x"] = ["GREATER_THAN", yag_size_min]
        constrants["rms_size_y"] = ["GREATER_THAN", yag_size_min]
    if yag_size_max is not None:
        constrants["rms_size_x"] = ["LESS_THAN", yag_size_max]
        constrants["rms_size_y"] = ["LESS_THAN", yag_size_max]
    if yag_intensity_min is not None:
        constrants["total_intensity"] = ["GREATER_THAN", yag_intensity_min]
    if yag_intensity_max is not None:
        constrants["total_intensity"] = ["LESS_THAN", yag_intensity_max]
    return VOCS(
        variables={
            "mirror_pitch": [mirror_nominal - search_delta, mirror_nominal + search_delta]
        },
        objectives={
            "objective": "MINIMIZE",
        },
        constraints=constrants,
    )


def get_evaluator_wave8(
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
        print(f"Distance from goal is {results['objective']}")
        return results

    return Evaluator(function=evaluate)


def get_evaluator_yag(
    yag: str = "dg1",
    yag_xpos: float | None = None,
) -> Evaluator:
    yag = yag.lower()
    if yag not in ("dg1", "dg2", "ip"):
        raise ValueError("Can only use dg1, dg2, ip yags.")
    if yag_xpos is None:
        if yag == "dg1":
            yag_xpos = DG1_YAG_XPOS
        elif yag == "dg2":
            yag_xpos = DG2_YAG_XPOS
        else:
            yag_xpos = IP_YAG_XPOS
    fit = ImageProjectionFit()

    def evaluate(input: dict[str, float]) -> dict[str, float]:
        print(f"Trying {input['mirror_pitch']}")
        devices = init_devices()
        devices["mr1l4_homs"].pitch.set(input["mirror_pitch"]).wait(timeout=20)
        image_device = devices[f"mfx_{yag}_yag"].shaped_image
        image_device.trigger().wait(timeout=10)
        image = image_device.get()
        # NOTE/TODO: consider adding an averaging step here before fitting
        fit_result = fit.fit_image(image)
        results = {}
        results["centroid_x"] = fit_result.centroid[0]
        results["centroid_y"] = fit_result.centroid[1]
        results["rms_size_x"] = fit_result.rms_size[0]
        results["rms_size_y"] = fit_result.rms_size[1]
        results["total_intensity"] = fit_result.total_intensity
        results["objective"] = abs(fit_result.centroid[0] - yag_xpos)
        print(f"Distance from goal is {results['objective']}")
        return results

    return Evaluator(function=evaluate)


def get_xopt_obj(
    device_type: str,
    location: str,
    goal: float,
    mirror_nominal: float = MIRROR_NOMINAL,
    search_delta: float = 5,
    wave8_max_value: float | None = None,
    yag_size_min: float | None = None,
    yag_size_max: float | None = None,
    yag_intensity_min: float | None = None,
    yag_intensity_max: float | None = None,
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
    device_type: str
        One of "yag" or "wave8"
    location : str
        One of "dg1", "dg2", "ip"
    goal : float
        Either the wave8 xpos to aim for, or the x coordinate to aim for on a yag.
    mirror_nominal : float
        The starting mirror pitch position and midpoint of the optimization search.
    search_delta : float
        How far +/- we check away from the mirror nominal pitch position
    yag_size_min : float, optional
        Constraint on minimum yag spot size for data to be valid
    yag_size_max : float, optional
        Constraint on maximum yag spot size for data to be valid
    yag_intensity_min : float, optional
        Constraint on minimum yag total intensity count for data to be valid
    yag_intensity_max : float, optional
        Constraint on maximum yag total intensity count for data to be valid
    """
    device_type = device_type.lower()
    if device_type not in ("yag", "wave8"):
        raise ValueError("device_type must be yag or wave8")
    location = location.lower()
    if location not in ("dg1", "dg2", "ip"):
        raise ValueError("location must be one of dg1, dg2, or ip")
    if device_type == "wave8" and location == "ip":
        raise ValueError("There is no wave8 at the ip")

    vocs = get_vocs(
        mirror_nominal=mirror_nominal,
        search_delta=search_delta,
        wave8_max_value=wave8_max_value,
        yag_size_min=yag_size_min,
        yag_size_max=yag_size_max,
        yag_intensity_min=yag_intensity_min,
        yag_intensity_max=yag_intensity_max,
    )
    if device_type == "yag":
        evaluator = get_evaluator_yag(
            yag=location,
            yag_xpos=goal,
        )
    else:
        evaluator = get_evaluator_wave8(
            wave8=location,
            wave8_xpos=goal,
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
    print("Canned tests: run_sim_test_wave8, run_sim_test_yag")


def run_sim_test_wave8() -> Xopt:
    print("Create Xopt")
    xopt = get_xopt_obj(
        device_type="wave8",
        location="dg1",
        goal=DG1_WAVE8_XPOS,
    )
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


def run_sim_test_yag() -> Xopt:
    print("Create Xopt")
    xopt = get_xopt_obj(
        device_type="yag",
        location="dg1",
        goal=DG1_YAG_XPOS,
    )
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
    imager = init_devices()["mfx_dg1_yag"]
    imager.shaped_image.trigger()
    fit = ImageProjectionFit()
    fit_result = fit.fit_image(imager.shaped_image.get())
    plot_image_projection_fit(fit_result)
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
        run_sim_test_yag()
