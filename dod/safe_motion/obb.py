"""
obb.py — Oriented Bounding Box geometry

All coordinates and dimensions in micrometres (µm).
Z=0 is the safe/highest robot position; Z=40000 is the lowest working depth.
Obstacle avoidance is a pure 2D XY problem (robot is at Z=0 during all XY travel).
"""

from __future__ import annotations
import math
from dataclasses import dataclass
from typing import List, Tuple

Point = Tuple[float, float]


@dataclass
class OBB:
    """Oriented Bounding Box.

    Args:
        cx:    Centre X in µm.
        cy:    Centre Y in µm.
        w:     Full width in µm (along local X axis before rotation).
        h:     Full height in µm (along local Y axis before rotation).
        angle: Rotation in degrees, counter-clockwise from world +X axis.
    """

    cx: float
    cy: float
    w: float
    h: float
    angle: float  # degrees CCW from +X

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    def expand(self, clearance: float) -> OBB:
        """Return a new OBB inflated by *clearance* on every side."""
        return OBB(
            self.cx, self.cy, self.w + 2 * clearance, self.h + 2 * clearance, self.angle
        )

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def corners(self) -> List[Point]:
        """Return the 4 world-space corners in CCW order:
        bottom-left, bottom-right, top-right, top-left (in local space)."""
        hw, hh = self.w / 2.0, self.h / 2.0
        rad = math.radians(self.angle)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        offsets = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
        return [
            (self.cx + dx * cos_a - dy * sin_a, self.cy + dx * sin_a + dy * cos_a)
            for dx, dy in offsets
        ]

    def _to_local(self, px: float, py: float) -> Tuple[float, float]:
        """Transform world point (px, py) into the OBB's local coordinate frame."""
        rad = math.radians(self.angle)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        dx, dy = px - self.cx, py - self.cy
        # Rotate by -angle: R^T · (dx, dy)
        lx = dx * cos_a + dy * sin_a
        ly = -dx * sin_a + dy * cos_a
        return lx, ly

    def contains_point(self, px: float, py: float) -> bool:
        """Return True if (px, py) is strictly inside the OBB (not on boundary)."""
        lx, ly = self._to_local(px, py)
        return abs(lx) < self.w / 2.0 and abs(ly) < self.h / 2.0

    def segment_intersects(
        self, ax: float, ay: float, bx: float, by: float, inset: float = 0.0
    ) -> bool:
        """Return True if the segment A→B intersects this OBB.

        Args:
            inset: Shrink each half-side by this amount before testing (µm).
                   A small value (e.g. 1.0 µm) lets segments running exactly
                   along the obstacle boundary be treated as clear.

        Method: transform both endpoints into local space, then run
        Liang-Barsky clipping against the AABB.
        """
        lax, lay = self._to_local(ax, ay)
        lbx, lby = self._to_local(bx, by)
        return _segment_intersects_aabb(
            lax, lay, lbx, lby, self.w / 2.0 - inset, self.h / 2.0 - inset
        )

    def __repr__(self) -> str:
        return (
            f"OBB(cx={self.cx:.0f}, cy={self.cy:.0f}, "
            f"w={self.w:.0f}, h={self.h:.0f}, angle={self.angle:.1f}°)"
        )


# ------------------------------------------------------------------
# Internal: Liang-Barsky AABB segment clipping
# ------------------------------------------------------------------


def _segment_intersects_aabb(
    ax: float, ay: float, bx: float, by: float, hw: float, hh: float
) -> bool:
    """Test whether segment (ax,ay)→(bx,by) intersects AABB [-hw,hw]×[-hh,hh].

    Uses Liang-Barsky parametric clipping.  Returns True if the segment
    clips the box (including touching the boundary).
    """
    dx, dy = bx - ax, by - ay

    # p[i], q[i] pairs for the four clip planes:
    #   p negative  → entering half-space
    #   p positive  → exiting  half-space
    #   p == 0      → parallel; check q for inside/outside
    p = (-dx, dx, -dy, dy)
    q = (ax + hw, hw - ax, ay + hh, hh - ay)

    t_min, t_max = 0.0, 1.0

    for pi, qi in zip(p, q):
        if pi == 0.0:
            if qi < 0.0:
                return False  # parallel and outside this slab
        elif pi < 0.0:  # entering
            r = qi / pi
            if r > t_min:
                t_min = r
        else:  # exiting
            r = qi / pi
            if r < t_max:
                t_max = r
        if t_min > t_max:
            return False  # clipped away

    # Strict: a segment that merely touches the boundary at a single
    # point (t_min == t_max, e.g. corner node leaving its own obstacle)
    # is NOT considered an intersection.
    return t_min < t_max
