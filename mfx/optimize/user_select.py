"""
Standard selectors for going from user inputs to various scan resources and settings.

Re-usable in many different sorts of scans.
"""
from typing import Optional, Union

from pcdsdevices.ipm import Wave8

from .beamline_hw import init_devices
from .devices import YagCamera
from .type_checking import Devices, Diagnostics, Movers, validate_w_lowercase_args


MP_KEY = "mirror_pitch"
UNDP_KEY_X = "undp_x"
UNDP_KEY_Y = "undp_y"


@validate_w_lowercase_args
def select_diagnostic(
    device_type: Devices,
    location: Diagnostics,
) -> Union[YagCamera, Wave8]:
    """
    Standard selector used to assemble the blop/xopt scans.

    From some standard set of options, return the
    diagnostic device we'll be use using in the optimization.

    Parameters
    ----------
    device_type : Devices
        One of "yag" or "wave8"
    location : Diagnostics
        One of "xcs1", "dg1", "dg2", "ip"
    """
    devices = init_devices()
    if device_type == "yag":
        if location == "xcs1":
            return devices["xcs_yag1"]
        else:
            return devices[f"mfx_{location}_yag"]
    elif device_type == "wave8":
        if location in ("dg1", "dg2"):
            return devices[f"mfx_{location}_wave8"]
        else:
            raise ValueError(f"Invalid wave8 {location}, expected dg1 or dg2")
    else:
        raise RuntimeError(
            f"Invalid device_type {device_type} selected, pydantic broke?"
        )


@validate_w_lowercase_args
def select_goal(
    device_type: Devices,
    location: Diagnostics,
    goal: Optional[float] = None,
    goal_2d: Optional[tuple[float, float]] = None,
    use_2d_markers: bool = False,
) -> Union[float, tuple[float, float]]:
    """
    Select a goal for the alignment.

    The goal is either a specific point on a 2d plane or on
    a 1d line.

    Exactly one of goal, goal_2d, and use_2d_markers must be
    provided.

    Some other combinations of arguments are not allowed
    and will raise ValueError.

    Parameters
    ----------
    device_type : Devices
        One of "yag" or "wave8"
    location : Diagnostics
        One of "xcs1", "dg1", "dg2", "ip"
    goal : float, optional
        1D goal to align to
    goal_2d : tuple[float, float], optional
        2D goal to align to
    use_2d_markers : bool, optional
        Set to True to automatically select the goal from the
        camviewer makers.

    Returns
    -------
    goal : float or tuple[float, float]
        The location to align to, given the settings.
    """
    goal_count = sum((goal is not None, goal_2d is not None, use_2d_markers))
    if goal_count != 1:
        raise ValueError(f"Exactly one goal position must be chosen! Recieved {goal_count} goals!")

    # goal is compatible with any hardware
    if goal is not None:
        return goal
    
    # goal_2d is compatible only with yags
    if goal_2d is not None:
        if device_type == "yag":
            return goal_2d
        else:
            raise ValueError(
                f"goal_2d is only compatible with yag, not with {device_type}! "
                "Try providing goal (float) instead."
            )

    # use_2d_markers is compatible only with yags
    if use_2d_markers:
        if device_type == "yag":
            yag_camera = select_diagnostic(device_type=device_type, location=location)
            if location == "xcs1":
                # Shared YAG: uses marker2 at the goal
                return yag_camera.coords.specific_marker_target(2)
            # MFX YAG: uses marker1, marker2 at opposite slit corners
            return yag_camera.coords.standard_two_corners_target()
        else:
            raise ValueError(
                f"use_2d_markers is only compatible with yag, not with {device_type}! "
                "Try providing goal (float) instead."
            )
    
    raise RuntimeError("Invalid codepath in select_goal, how did you get here?")


@validate_w_lowercase_args
def select_var_range(
    mover: Movers,
    search_range: Optional[Union[list[tuple[float, float]], tuple[float, float]]] = None,
    search_delta: Optional[Union[float, tuple[float, float]]] = None,
    search_center: Optional[Union[float, tuple[float, float]]] = None,
) -> dict[str, tuple[float, float]]:
    """
    Select valid move ranges for the mover.

    Parameters
    ----------
    mover : str
        One of "mirr" or "und", the kind of movement we'll be doing.
    search_range : tuple of floats or list of tuple of floats, optional
        Explicit search ranges per dimension, in units of your motion device.
        Either search_range or search_delta must be provided.
    search_delta : float, optional
        The +- around the center to search for, in units of your motion device.
        Either search_range or search_delta must be provided.
    search_center : float or tuple of floats, optional
        If using search_delta, this is the reference point for
        the delta range, in units of your motion device.
        If not provided this will be the mover's current position.

    Returns
    -------
    var_range : dict of str to tuple
        Min, max tuples per dimension of the mover.
        The keys are the ones we use for the optimizer to reference the data.
    """
    if search_range is None and search_delta is None:
        raise ValueError("Must provide either search_range or search_delta!")
    if search_range is not None and search_delta is not None:
        raise ValueError("Must provide only one of search_range and search_delta!")

    if mover == "mirr":
        # 1D mirror
        if search_range is not None:
            if isinstance(search_range, tuple):
                return {MP_KEY: search_range}
            return {MP_KEY: search_range[0]}
        elif search_delta is not None:
            if search_center is None:
                devices = init_devices()
                search_center = devices["mr1l4_homs"].position
            return {MP_KEY: (search_center - search_delta, search_center + search_delta)}
    elif mover == "und":
        # 2D undulator
        if search_range is not None:
            if isinstance(search_range, tuple):
                search_range = [search_range, search_range]
            return {
                UNDP_KEY_X: search_range[0],
                UNDP_KEY_Y: search_range[1],
            }
        elif search_delta is not None:
            if isinstance(search_delta, (float, int)):
                search_delta = (search_delta, search_delta)
            if search_center is None:
                devices = init_devices()
                search_center = devices["undp"].position
            elif isinstance(search_center, (float, int)):
                search_center = (search_center, search_center)
            return {
                UNDP_KEY_X: (search_center[0] - search_delta[0], search_center[0] + search_delta[0]),
                UNDP_KEY_Y: (search_center[1] - search_delta[1], search_center[1] + search_delta[1]),
            }
    else:
        raise NotImplementedError(f"Mover type {mover} not implemented in select_range.")
