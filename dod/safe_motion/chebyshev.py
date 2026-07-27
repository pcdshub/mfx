"""
chebyshev.py — Chebyshev motion model for the DoD robot XY stage.

The robot moves both X and Y axes simultaneously at equal velocities.
The actual trajectory between two points is therefore NOT a straight line
but a diagonal segment followed by an axis-aligned segment (L-shape):

    Phase 1 (diagonal):  both axes move until the shorter one finishes.
    Phase 2 (straight):  only the longer axis continues to the target.

This means collision checks must test these two segments against obstacles,
NOT a straight line between start and end.

All coordinates in µm.
"""

from __future__ import annotations
import math
from typing import List, Tuple

from .obb import OBB, Point

# A segment is represented as a pair of Points.
Segment = Tuple[Point, Point]


def chebyshev_segments(ax: float, ay: float, bx: float, by: float) -> List[Segment]:
    """Decompose the robot trajectory from A to B into its constituent segments.

    Returns a list of 1 or 2 segments:
      - 1 segment (pure diagonal): when |dx| == |dy|
      - 2 segments (diagonal + axis-aligned): the general case

    The 'mid' point is where the shorter axis finishes and the robot
    continues on the remaining axis alone.
    """
    dx, dy = bx - ax, by - ay
    adx, ady = abs(dx), abs(dy)

    if adx == 0 and ady == 0:
        # No movement: return a single degenerate segment.
        return [((ax, ay), (ax, ay))]

    sx = 1.0 if dx >= 0 else -1.0
    sy = 1.0 if dy >= 0 else -1.0

    if adx >= ady:
        # Y finishes first; diagonal covers ady, then horizontal remainder.
        mid: Point = (ax + ady * sx, by)
    else:
        # X finishes first; diagonal covers adx, then vertical remainder.
        mid = (bx, ay + adx * sy)

    if mid == (bx, by):
        # Pure diagonal (|dx| == |dy|): single segment.
        return [((ax, ay), (bx, by))]

    return [((ax, ay), mid), (mid, (bx, by))]


def chebyshev_cost(ax: float, ay: float, bx: float, by: float) -> float:
    """Transit 'cost' proportional to Chebyshev distance.

    With equal vx == vy, transit time = max(|dx|, |dy|) / v.
    We drop the common factor v and return the Chebyshev distance in µm,
    which is what Dijkstra minimises.
    """
    return max(abs(bx - ax), abs(by - ay))


def path_is_clear(
    ax: float, ay: float, bx: float, by: float, obstacles: List[OBB]
) -> bool:
    """Return True if the Chebyshev trajectory from A to B does not
    intersect any obstacle in *obstacles*.

    Both segments of the path are checked independently.
    Degenerate (zero-length) segments are skipped.

    A 1 µm inset is applied so that paths running exactly along the
    boundary of a clearance buffer are treated as valid.  The effective
    clearance remains essentially unchanged (e.g. 11.999 mm vs 12.000 mm).
    """
    _INSET = 1.0  # µm — boundary tolerance

    for seg in chebyshev_segments(ax, ay, bx, by):
        p1, p2 = seg
        if p1 == p2:
            continue  # degenerate segment — skip
        for obs in obstacles:
            if obs.segment_intersects(p1[0], p1[1], p2[0], p2[1], inset=_INSET):
                return False
    return True


def chebyshev_path_points(waypoints: List[Point]) -> List[Point]:
    """Expand an ordered list of waypoints into the full set of points
    that describe the actual robot trajectory (including mid-points).

    Useful for visualisation and length calculations.
    """
    if len(waypoints) < 2:
        return list(waypoints)

    all_pts: List[Point] = [waypoints[0]]
    for i in range(len(waypoints) - 1):
        a, b = waypoints[i], waypoints[i + 1]
        segs = chebyshev_segments(a[0], a[1], b[0], b[1])
        # Add all intermediate points except the start (already added).
        for seg in segs:
            all_pts.append(seg[1])

    return all_pts


def path_length_mm(waypoints: List[Point]) -> float:
    """Return the total Euclidean length of the actual robot trajectory in mm.

    Note: the Chebyshev cost (transit time) is proportional to
    max(|dx|, |dy|), not Euclidean length.  This function gives the
    physical distance the tool travels.
    """
    pts = chebyshev_path_points(waypoints)
    total = 0.0
    for i in range(len(pts) - 1):
        dx = pts[i + 1][0] - pts[i][0]
        dy = pts[i + 1][1] - pts[i][1]
        total += math.hypot(dx, dy)
    return total / 1000.0  # µm → mm
