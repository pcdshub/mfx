# pathplan.py
# Collision checking and detour routing for the DoD robot.
# Pure geometry: no robot/network needed, so it's instant to test.

from dataclasses import dataclass


@dataclass
class Point:
    x: float
    y: float
    z: float

    def as_tuple(self):
        return (self.x, self.y, self.z)


@dataclass
class Zone:
    xmin: float
    ymin: float
    zmin: float
    xmax: float
    ymax: float
    zmax: float
    margin: float = 0.0

    def inflated(self):
        m = self.margin
        return (self.xmin - m, self.ymin - m, self.zmin - m,
                self.xmax + m, self.ymax + m, self.zmax + m)

    def contains(self, p: Point) -> bool:
        xmin, ymin, zmin, xmax, ymax, zmax = self.inflated()
        return (xmin <= p.x <= xmax and
                ymin <= p.y <= ymax and
                zmin <= p.z <= zmax)


def segment_hits_zone(start: Point, end: Point, zone: Zone) -> bool:
    xmin, ymin, zmin, xmax, ymax, zmax = zone.inflated()

    dx = end.x - start.x
    dy = end.y - start.y
    dz = end.z - start.z

    t_enter = 0.0
    t_exit = 1.0

    for s0, d, lo, hi in (
        (start.x, dx, xmin, xmax),
        (start.y, dy, ymin, ymax),
        (start.z, dz, zmin, zmax),
    ):
        if d == 0:
            if s0 < lo or s0 > hi:
                return False
        else:
            t1 = (lo - s0) / d
            t2 = (hi - s0) / d
            if t1 > t2:
                t1, t2 = t2, t1
            t_enter = max(t_enter, t1)
            t_exit = min(t_exit, t2)
            if t_enter > t_exit:
                return False

    return True


def is_move_safe(start: Point, end: Point, zone: Zone) -> bool:
    return not segment_hits_zone(start, end, zone)


def plan_detour(start: Point, end: Point, zone: Zone):
    if is_move_safe(start, end, zone):
        return [start, end]

    xmin, ymin, zmin, xmax, ymax, zmax = zone.inflated()
    buf = max(zone.margin, 1.0)

    safe_z_above = zmax + buf

    up = Point(start.x, start.y, safe_z_above)
    over = Point(end.x, end.y, safe_z_above)
    if (is_move_safe(start, up, zone) and
            is_move_safe(up, over, zone) and
            is_move_safe(over, end, zone)):
        return [start, up, over, end]

    safe_x_left = xmin - buf
    safe_x_right = xmax + buf
    safe_y_front = ymin - buf
    safe_y_back = ymax + buf

    side_candidates = [
        Point(safe_x_left, start.y, start.z),
        Point(safe_x_right, start.y, start.z),
        Point(start.x, safe_y_front, start.z),
        Point(start.x, safe_y_back, start.z),
        Point(safe_x_left, end.y, end.z),
        Point(safe_x_right, end.y, end.z),
    ]
    for wp in side_candidates:
        if is_move_safe(start, wp, zone) and is_move_safe(wp, end, zone):
            return [start, wp, end]

    return None