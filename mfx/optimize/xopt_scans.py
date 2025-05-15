"""
To run for real, import get_xopt_obj and try to random_evaluate() and step() the Xopt object.
To test with sim, ipython -i mfx/optimize/xopt_scans.py for an interactive test
Or python -m mfx.optimize.xopt_scans for a default sim run-through
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from xopt import VOCS, Evaluator, Xopt
from xopt.generators.bayesian import ExpectedImprovementGenerator

from lcls_tools.common.frontend.plotting.image import plot_image_projection_fit
from lcls_tools.common.image.fit import ImageProjectionFit, ImageProjectionFitResult

from .beamline_hw import (
    DG1_WAVE8_XPOS,
    DG2_WAVE8_XPOS,
    IP_YAG_XPOS,
    init_devices,
)
from .constraints import constraint_data
from .type_checking import validate_w_lowercase_args, Devices, Diagnostics, Turbo, Movers
from .user_select import select_diagnostic, select_goal, MP_KEY, UNDP_KEY_X, UNDP_KEY_Y


@validate_w_lowercase_args
def get_variables(mover: Movers):
    """Apply info in constraints module for movers to xopt variables"""
    variables = {}
    if mover == "mirr":
        center = constraint_data.mirr.range_center
        delta = constraint_data.mirr.range_delta
        variables[MP_KEY] = [center - delta, center + delta]
    elif mover == "und":
        undp = init_devices()["undp"]
        pos = undp.position
        delta = constraint_data.und.xy_delta
        variables[UNDP_KEY_X] = [pos[0] - delta, pos[0] + delta]
        variables[UNDP_KEY_Y] = [pos[1] - delta, pos[1] + delta]
    return variables


@validate_w_lowercase_args
def get_constraints(diagnostic: Diagnostics, device: Devices) -> dict[str, list]:
    """Apply info in constraints module for diagnostics to xopt constraints"""
    if device == "yag":
        try:
            yag_constraint = constraint_data.yag[diagnostic]
        except KeyError:
            return {}
        if yag_constraint.roi_center is not None and yag_constraint.roi_radius is not None:
            return {"roi_radius": ["LESS_THAN", yag_constraint.roi_radius]}
    return {}


@validate_w_lowercase_args
def get_vocs(
    mover: Movers,
    diagnostic: Diagnostics,
    device: Devices,
) -> VOCS:
    return VOCS(
        variables=get_variables(mover),
        objectives={
            "objective": "MINIMIZE",
        },
        constraints=get_constraints(diagnostic, device),
    )


@validate_w_lowercase_args
def evaluator_move(mover: Movers, input: dict):
    """
    Re-usable XOpt move primitive.

    Takes XOpt's input and moves the applicable device.
    """
    if mover == "mirr":
        print(f"Trying {input[MP_KEY]}")
    elif mover == "und":
        print(f"Trying ({input[UNDP_KEY_X]}, {input[UNDP_KEY_Y]})")
    else:
        raise NotImplementedError(f"Mover type {mover} not implemented in evaluator_move.")
    devices = init_devices()
    if mover == "mirr":
        devices["mr1l4_homs"].pitch.set(input["mirror_pitch"]).wait(timeout=20)
    elif mover == "und":
        devices["undp"].move((input[UNDP_KEY_X], input[UNDP_KEY_Y]), wait=True, timeout=20)


@validate_w_lowercase_args
def get_evaluator_wave8(
    wave8: str = "dg1",
    wave8_xpos: Optional[float] = None,
    mover: Movers = "mirr",
) -> Evaluator:
    if wave8_xpos is None:
        if wave8 == "dg1":
            wave8_xpos = DG1_WAVE8_XPOS
        elif wave8 == "dg2":
            wave8_xpos = DG2_WAVE8_XPOS
        else:
            raise ValueError(f"Invalid wave8 {wave8}, expected dg1 or dg2")

    def evaluate(input: dict[str, float]) -> dict[str, float]:
        evaluator_move(mover=mover, input=input)
        xpos_device = select_diagnostic("wave8", wave8).xpos
        xpos_device.trigger().wait(timeout=10)
        xpos = xpos_device.get()
        results = {}
        results["centroid_x"] = xpos
        results["abs_centroid_x"] = abs(xpos)
        results["objective"] = abs(xpos - wave8_xpos)
        print(f"Distance from goal is {results['objective']}")
        return results

    return Evaluator(function=evaluate)


def evaluate_yag_processing(
    diagnostic: Diagnostics,
    fit: ImageProjectionFit,
) -> ImageProjectionFitResult:
    """
    Shared image collection and fitting for use in yag evaluators.
    """
    image_device = select_diagnostic("yag", diagnostic).image1.shaped_image
    image_device.trigger().wait(timeout=10)
    image = image_device.get()
    print(f"image shape: {image.shape}")
    # NOTE/TODO: consider adding an averaging step here before fitting
    return fit.fit_image(image)


def distance2d(pt1: tuple[float, float], pt2: tuple[float, float]) -> float:
    return np.sqrt((pt1[0] - pt2[0])**2 + (pt1[1] - pt2[1])**2)


def evaluate_yag_results(
    diagnostic: Diagnostics,
    fit_result: ImageProjectionFitResult,
) -> dict[str, float]:
    """
    Shared unpacking of the fit result for use in yag evaluators.
    """
    results = {}
    results["centroid_x"] = fit_result.centroid[0]
    results["centroid_y"] = fit_result.centroid[1]
    results["rms_size_x"] = fit_result.rms_size[0]
    results["rms_size_y"] = fit_result.rms_size[1]
    results["total_intensity"] = fit_result.total_intensity
    try:
        yag_constr = constraint_data.yag[diagnostic]
    except KeyError:
        ...
    else:
        if yag_constr.roi_center is not None:
            results["roi_radius"] = distance2d(fit_result.centroid, yag_constr.roi_center)
    return results


@validate_w_lowercase_args
def get_evaluator_yag(
    yag: str = "dg1",
    goal: Optional[float] = None,
    mover: Movers = "mirr",
) -> Evaluator:
    yag = yag.lower()
    if yag not in ("xcs1", "dg1", "dg2", "ip"):
        raise ValueError("Can only use xcs1, dg1, dg2, ip yags.")
    if goal is None:
        if yag == 'xcs1':
            goal = constraint_data.yag["xcs1"].roi_center[0]
        elif yag == "dg1":
            goal = constraint_data.yag["dg1"].roi_center[0]
        elif yag == "dg2":
            goal = constraint_data.yag["dg2"].roi_center[0]
        else:
            goal = IP_YAG_XPOS
    fit = ImageProjectionFit()

    def evaluate(input: dict[str, float]) -> dict[str, float]:
        evaluator_move(mover=mover, input=input)
        fit_result = evaluate_yag_processing(yag, fit)
        results = evaluate_yag_results(yag, fit_result)
        results["objective"] = abs(fit_result.centroid[0] - goal)
        print(f"Distance from goal is {results['objective']}")
        return results

    return Evaluator(function=evaluate)


@validate_w_lowercase_args
def get_evaluator_yag_2d(
    yag: Diagnostics,
    goal: tuple[float, float],
    mover: Movers,
) -> Evaluator:
    """
    Alternate evaluator in 2d space.
    """
    fit = ImageProjectionFit()

    def evaluate(input: dict[str, float]) -> dict[str, float]:
        evaluator_move(mover=mover, input=input)
        fit_result = evaluate_yag_processing(yag, fit)
        results = evaluate_yag_results(yag, fit_result)
        results["objective"] = distance2d(fit_result.centroid, goal)
        print(f"Distance from goal is {results['objective']}")
        return results

    return Evaluator(function=evaluate)


@validate_w_lowercase_args
def get_xopt_obj(
    device_type: Devices,
    location: Diagnostics,
    mover: Movers,
    goal: Optional[float] = None,
    xopt_generator_turbo_controller: Optional[Turbo] = None,
    use_2d_markers: bool = False,
    goal_2d: Optional[tuple[float, float]] = None,
    max_iter: Optional[int] = None,
    dump_file: Optional[str] = None,
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
    device_type : Devices
        One of "yag" or "wave8"
    location : Diagnostics
        One of "xcs1", "dg1", "dg2", "ip"
    mover : str
        One of "mirr" or "und", the kind of movement we'll be doing.
    goal : float, optional
        Either the wave8 xpos to aim for, or the x coordinate to aim for on a yag.
    xopt_generator_turbo_controller : str, optional
        Which turbo controller to use. Options: "safety, optimize"
    use_2d_markers: bool, optional
        Run a 2D YAG optimization using camera markers
    goal_2d: tuple[float, float] or None, optional
        The 2D optimization goal if running a 2D YAG optimization
    max_iter: int, optional
        Max number of steps for maximizing the acquisition function
    dump_file: str, optional
        Filepath to write data too. See Xopt's dump_file docs.
    """
    goal_value = select_goal(
        device_type=device_type,
        location=location,
        goal=goal,
        goal_2d=goal_2d,
        use_2d_markers=use_2d_markers,
    )
    vocs = get_vocs(
        mover=mover,
        diagnostic=location,
        device=device_type,
    )
    print(vocs)
    if device_type == "yag":
        if isinstance(goal_value, tuple):
            evaluator = get_evaluator_yag_2d(
                yag=location,
                goal=goal_value,
                mover=mover,
            )
        else:
            evaluator = get_evaluator_yag(
                yag=location,
                goal=goal_value,
                mover=mover,
            )
    else:
        evaluator = get_evaluator_wave8(
            wave8=location,
            wave8_xpos=goal_value,
            mover=mover,
        )
    generator = ExpectedImprovementGenerator(vocs=vocs, turbo_controller=xopt_generator_turbo_controller)
    generator.gp_constructor.use_low_noise_prior = False
    generator.numerical_optimizer.max_iter = max_iter
    if mover == "mirr":
        constr = constraint_data.mirr
        if constr.max_travel_distance is not None:
            # 1d, one distance
            generator.max_travel_distances = [constr.max_travel_distance]
    elif mover == "und":
        constr = constraint_data.und
        if constr.max_travel_distance is not None:
            # 2d, two distances
            generator.max_travel_distances = [constr.max_travel_distance, constr.max_travel_distance]
    return Xopt(
        vocs=vocs,
        generator=generator,
        evaluator=evaluator,
        dump_file=dump_file,
    )
