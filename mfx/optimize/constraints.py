"""
Define per-device optimization constraints.

This is intentionally separate from the hardware definitions
and from the optimzer-specific configurations in order to:
- make it easy to find
- keep it optimizer-agnostic

A constraint on an input variable (such as a centroid position)
tells the optimizer that that the point is no good.
The optimizer should avoid such points and not consider them in
the model.
This is intended for points that are invalid data, or otherwise
are correlated with problems.
These are the "constraints" in the XOpt VOCS.
These are "objectives" with constraint= instead of target= in Blop.

A contraint on an output variable (such as allowed range, step sizes)
tells the optimizer which points it is or is not allowed to try.
These are restrictions on "variables" in the XOpt VOCS
(and sometimes, generator kwargs).
These are restrictions on "degress of freedom" in Blop. 
"""
from __future__ import annotations

from dataclasses import dataclass

from type_checking import Diagnostics


@dataclass
class YagConstraints:
    # Disregard points outside of the ROI
    # Use a circular ROI to help the optimizer
    roi_center: tuple[int, int] | None = None
    roi_radius: int | None = None


xcs_yag1_constraints = YagConstraints(
    # red marker is (567, 343) on May 13, 2025
    # image is 728 x 544
    # keep it simple: within 100 (much larger and we fall off the sensor)
    roi_center=(567, 343),
    roi_radius=100,
)
mfx_dg1_yag_constraints = YagConstraints(
    # red marker is (136, 170) on May 13, 2025
    # blue marker is (347, 377) on May 13, 2025
    # image is hardware ROI'd to 512 x 512
    # keep it simple: stay within slits
    roi_center=(240, 270),
    roi_radius=180,
)
mfx_dg2_yag_constraints = YagConstraints(
    # global markers are missing on May 13, 2025!
    # they're all (0, 0)
    # image is hardware ROI'd to 512 x 512
    # keep it simple: stay away from the edge
    roi_center=(256, 256),
    roi_radius=200,
)

yag_constraint_data: dict[Diagnostics, YagConstraints] = {
    "xcs1": xcs_yag1_constraints,
    "dg1": mfx_dg1_yag_constraints,
    "dg2": mfx_dg2_yag_constraints,
}


@dataclass
class MirrorConstraints:
    # Only consider points +- delta from center
    range_center: float
    range_delta: float
    # Do not move more than this distance
    # in real units per step
    max_travel_distance: float | None = None

mfx_mirror_constraints = MirrorConstraints(
    range_center=-544.0,
    range_delta=2,
    max_travel_distance=1,
)


@dataclass
class UndulatorConstraints:
    # Do not try points more than this far away from the start pos
    xy_delta: float
    # Do not move more than this distance (x, y separately)
    # in real units per step
    max_travel_distance: float | None = None


hxr_und_constraints = UndulatorConstraints(
    xy_delta=25,
    max_travel_distance=5,
)

@dataclass
class ConstraintData:
    yag: dict[Diagnostics, YagConstraints]
    mirr: MirrorConstraints
    und: UndulatorConstraints


constraint_data = ConstraintData(
    yag=yag_constraint_data,
    mirr=mfx_mirror_constraints,
    und=hxr_und_constraints,
)