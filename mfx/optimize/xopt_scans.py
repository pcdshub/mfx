"""
To run for real, import get_xopt_obj and try to random_evaluate() and step() the Xopt object.
To test with sim, ipython -i mfx/optimize/xopt_scans.py for an interactive test
Or python -m mfx.optimize.xopt_scans for a default sim run-through
"""
from __future__ import annotations

from typing import Optional

import numpy as np

import time
import datetime
from pathlib import Path

from xopt import VOCS, Evaluator, Xopt
from xopt.generators.bayesian import ExpectedImprovementGenerator, UpperConfidenceBoundGenerator

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
def get_variables(mover: Movers, narrow: bool = False):
    """
    Apply info in constraints module for movers to xopt variables

    Parameters
    ----------
    mover : str
        mirr or und
    narrow : bool, optional
        If False (default), we'll use the range/delta constraints.
        If True, we'll use the max_travel_distance constraint to give
        an even narrower range.
    """
    variables = {}
    if mover == "mirr":
        center = constraint_data.mirr.range_center
        if narrow and constraint_data.mirr.max_travel_distance is not None:
            delta = constraint_data.mirr.max_travel_distance
        else:
            delta = constraint_data.mirr.range_delta
        variables[MP_KEY] = [center - delta, center + delta]
    elif mover == "und":
        # Use fixed absolute bounds for undulator positions
        variables[UNDP_KEY_X] = [0, 200] # [-100, 150]
        variables[UNDP_KEY_Y] = [-450, -200] # [-750, -350]
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
            "objective": "MINIMIZE", # RYAN R: SOMETHING TO CONSIDER TO SPEED THINGS UP. ONLY ONE GP
            #"roi_radius": "MINIMIZE",
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
        devices["und_abs"].move((input[UNDP_KEY_X], input[UNDP_KEY_Y]), wait=True, timeout=20)


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
    num_frames: int = 1,
    save_dir: Optional[str] = None,
) -> tuple[ImageProjectionFitResult, str]:
    """
    Shared image collection and fitting for use in yag evaluators.
    
    Parameters
    ----------
    diagnostic : Diagnostics
        The diagnostic location (e.g., "dg1", "dg2", "xcs1", "ip")
    fit : ImageProjectionFit
        The fit object to use for image analysis
    num_frames : int, optional
        Number of frames to average. Default is 1 (no averaging).
        If > 1, will trigger the camera multiple times and average the results.
    """
    image_device = select_diagnostic("yag", diagnostic).image1.shaped_image
    
    if num_frames == 1:
        # Single frame original behavior
        image_device.trigger().wait(timeout=10)
        image = image_device.get()
        print(f"image shape: {image.shape}")
    else:
        # Multiple frames collect and average
        print(f"Collecting {num_frames} frames for averaging...")
        images = []
        
        for i in range(num_frames):
            image_device.trigger().wait(timeout=10)
            frame = image_device.get()
            images.append(frame)
            print(f"Frame {i+1}/{num_frames} collected, shape: {frame.shape}")
        
        # Average the frames
        image = np.mean(images, axis=0)
        print(f"Averaged image shape: {image.shape}")

    images_root = Path(save_dir)
    images_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%y-%m-%d-%H:%M:%S")
    filename = f"yag_{str(diagnostic).lower()}_{timestamp}.npz"
    file_path = images_root / filename
    try:
        np.savez_compressed(file_path, image=image)
    except Exception as exc:
        print(f"Warning: failed to save NPZ image to {file_path}: {exc}")
    
    return fit.fit_image(image), str(file_path)


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
    num_frames: int = 1,
    images_dir: Optional[str] = None,
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

    def evaluate(input: dict[str, float]) -> dict[str, float | str]:
        evaluator_move(mover=mover, input=input)
        fit_result, npz_path = evaluate_yag_processing(yag, fit, num_frames=num_frames, save_dir=images_dir)
        results = evaluate_yag_results(yag, fit_result)
        results["objective"] = abs(fit_result.centroid[0] - goal)
        results["image_npz_path"] = npz_path
        print(f"Distance from goal is {results['objective']}")
        return results

    return Evaluator(function=evaluate)


@validate_w_lowercase_args
def get_evaluator_yag_2d(
    yag: Diagnostics,
    goal: tuple[float, float],
    mover: Movers,
    num_frames: int = 1,
    images_dir: Optional[str] = None,
) -> Evaluator:
    """
    Alternate evaluator in 2d space.
    """
    fit = ImageProjectionFit()

    def evaluate(input: dict[str, float]) -> dict[str, float | str]:
        evaluator_move(mover=mover, input=input)
        time.sleep(5) # WAIT FOR MOTORS TO STOP MOTION 
        fit_result, npz_path = evaluate_yag_processing(yag, fit, num_frames=num_frames, save_dir=images_dir)
        results = evaluate_yag_results(yag, fit_result)
        results["objective"] = distance2d(fit_result.centroid, goal)
        results["image_npz_path"] = npz_path
        try:
            w8 = select_diagnostic("wave8", yag)
            w8.xpos.trigger().wait(timeout=10)
            w8.ypos.trigger().wait(timeout=10)
            w8.sum.trigger().wait(timeout=10)
            results["wave8_x"] = float(w8.xpos.get())
            results["wave8_y"] = float(w8.ypos.get())
            results["wave8_sum"] = float(w8.sum.get())
        except Exception as exc:
            print(f"Warning: failed to read wave8 x/y/sum: {exc}")
        print(f"Distance from goal is {results['objective']}")
        return results

    return Evaluator(function=evaluate)


@validate_w_lowercase_args
def get_evaluator_wave8_2d(
    wave8: Diagnostics,
    goal: tuple[float, float],
    mover: Movers,
) -> Evaluator:
    """
    2D evaluator for wave8 using xpos and ypos.
    """
    def evaluate(input: dict[str, float]) -> dict[str, float]:
        evaluator_move(mover=mover, input=input)
        time.sleep(5) # WAIT FOR MOTORS TO STOP MOTION 
        device = select_diagnostic("wave8", wave8)
        device.xpos.trigger().wait(timeout=10)
        device.ypos.trigger().wait(timeout=10)
        device.sum.trigger().wait(timeout=10)
        x = device.xpos.get()
        y = device.ypos.get()
        sum_ = device.sum.get()
        results = {
            "centroid_x": x,
            "centroid_y": y,
            "intensity": sum_,
            "objective": distance2d((x, y), goal),
        }
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
    num_frames: int = 1,
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
    num_frames: int, optional
        Number of frames to average for YAG image collection. Default is 1 (no averaging).
        Only applies when device_type is "yag".
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
    #vocs.constraints = {}
    if device_type == "yag":
        # Create per run images directory
        images_root = Path.home() #Path("/cds/home/opr/mfxopr")
        images_root.mkdir(parents=True, exist_ok=True)
        run_dir_name = Path(dump_file).stem
        run_images_dir = images_root / run_dir_name
        run_images_dir.mkdir(parents=True, exist_ok=True)
        if isinstance(goal_value, tuple):
            evaluator = get_evaluator_yag_2d(
                yag=location,
                goal=goal_value,
                mover=mover,
                num_frames=num_frames,
                images_dir=str(run_images_dir),
            )
        else:
            evaluator = get_evaluator_yag(
                yag=location,
                goal=goal_value,
                mover=mover,
                num_frames=num_frames,
                images_dir=str(run_images_dir),
            )
    else:
        if isinstance(goal_value, tuple):
            evaluator = get_evaluator_wave8_2d(
                wave8=location,
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
    generator.turbo_controller.restrict_model_data = False
    generator.turbo_controller.length_min = 0.05 # 5 percent of the input space
    #generator = UpperConfidenceBoundGenerator(vocs=vocs, beta=0.01) #0.1)
    generator.gp_constructor.use_low_noise_prior = False
    generator.numerical_optimizer.max_iter = max_iter
    if mover == "mirr":
        constr = constraint_data.mirr
        if constr.max_travel_distance is not None:
            # 1d, one distance
            vd = vocs.variables
            var_dist = vd[MP_KEY][1] - vd[MP_KEY][0]
            generator.max_travel_distances = [constr.max_travel_distance / var_dist]
    elif mover == "und":
        constr = constraint_data.und
        if constr.max_travel_distance is not None:
            # 2d, two distances
            vd = vocs.variables
            var_dist_x = vd[UNDP_KEY_X][1] - vd[UNDP_KEY_X][0]
            var_dist_y = vd[UNDP_KEY_Y][1] - vd[UNDP_KEY_Y][0]
            generator.max_travel_distances = [constr.max_travel_distance / var_dist_x, constr.max_travel_distance / var_dist_y]
    print(f"Max travel distances {generator.max_travel_distances}")
    print(generator.vocs)
    return Xopt(
        vocs=vocs,
        generator=generator,
        evaluator=evaluator,
        dump_file=dump_file,
    )


def test_write_permissions():
    """
    Simple test function to check if we can write to /cds/home/opr/mfxopr (or your home)
    """

    test_dir = Path.home() #Path("/cds/home/opr/mfxopr")
    test_dir.mkdir(parents=True, exist_ok=True)
    test_file = test_dir / f"test_write.txt"

    try:
        with open(test_file, 'w') as f:
            f.write("This is a test to verify write permissions.\n")
        print(f"SUCCESS: Successfully wrote test file to {test_file}")
        return True
    except Exception as e:
        print(f"ERROR: Failed to write test file: {e}")
        return False
