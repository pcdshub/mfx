"""
gridplan.py -- grid-based collision avoidance for the DoD robot.

"""

import math
from collections import deque
from dataclasses import dataclass, field

from pathplan import Point, Zone, is_move_safe


# ---------------------------------------------------------------------------
# Vectors: position + velocity (Sebastian: "vectors make more sense")
# ---------------------------------------------------------------------------
@dataclass
class MotionVector:
    """
    A position PLUS a velocity. A Point says only WHERE the nozzle is;
    a MotionVector also says WHICH WAY it's moving and HOW FAST -- which is
    what you need to reason about stopping distance and safety margins.

    Units: position in um, velocity in um/s.
    """
    x: float
    y: float
    z: float
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0

    def point(self) -> Point:
        """Just the position part, as a pathplan Point."""
        return Point(self.x, self.y, self.z)

    def speed(self) -> float:
        """Magnitude of the velocity (um/s)."""
        return math.sqrt(self.vx ** 2 + self.vy ** 2 + self.vz ** 2)

    def direction(self):
        """Unit vector of travel, or (0,0,0) if not moving."""
        s = self.speed()
        if s == 0:
            return (0.0, 0.0, 0.0)
        return (self.vx / s, self.vy / s, self.vz / s)

    @staticmethod
    def toward(start: Point, end: Point, speed: float) -> "MotionVector":
        """
        Build the motion vector for a move from start to end at a given speed:
        position = start, velocity = speed * (unit vector start->end).
        """
        dx, dy, dz = end.x - start.x, end.y - start.y, end.z - start.z
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        if dist == 0:
            return MotionVector(start.x, start.y, start.z)
        k = speed / dist
        return MotionVector(start.x, start.y, start.z, dx * k, dy * k, dz * k)


def braking_distance(speed_um_s: float, decel_um_s2: float = 10000.0) -> float:
    """
    How far the nozzle travels while stopping: d = v^2 / (2a).
    This is the velocity-dependent part of the safety margin -- a fast move
    needs MORE clearance from the zone than a slow one, because if something
    goes wrong it can't stop instantly.

    decel_um_s2 is a PLACEHOLDER (10 mm/s^2) -- ask Sebastian / measure the
    real axis deceleration. Returns um.
    """
    if decel_um_s2 <= 0:
        return 0.0
    return (speed_um_s ** 2) / (2.0 * decel_um_s2)


# ---------------------------------------------------------------------------
# The grid
# ---------------------------------------------------------------------------
@dataclass
class GridPlanner:
    """
    A 3D grid over the workspace. Each cell is SAFE or UNSAFE.

    workspace: dict like {"X": (0, 254000), "Y": (0, 118000), "Z": (0, 40000)}
               -- same shape as the WORKSPACE dicts already in the project.
    zone:      the keep-out Zone from pathplan (or None).
    cell_size: cell edge length in um. 5000 (5 mm) is a good start: fine enough
               to hug the zone, coarse enough to plan in milliseconds.
    speed:     assumed travel speed (um/s), used for the braking margin.
    decel:     assumed deceleration (um/s^2). PLACEHOLDER -- confirm real value.
    """
    workspace: dict
    zone: Zone = None
    cell_size: float = 5000.0
    speed: float = 10000.0        # 10 mm/s -- placeholder travel speed
    decel: float = 10000.0        # 10 mm/s^2 -- placeholder deceleration
    # filled in by __post_init__:
    nx: int = field(init=False, default=0)
    ny: int = field(init=False, default=0)
    nz: int = field(init=False, default=0)
    unsafe: set = field(init=False, default_factory=set)

    def __post_init__(self):
        (x0, x1) = self.workspace["X"]
        (y0, y1) = self.workspace["Y"]
        (z0, z1) = self.workspace["Z"]
        self.x0, self.y0, self.z0 = x0, y0, z0
        self.nx = max(1, math.ceil((x1 - x0) / self.cell_size))
        self.ny = max(1, math.ceil((y1 - y0) / self.cell_size))
        self.nz = max(1, math.ceil((z1 - z0) / self.cell_size))
        self._classify_cells()

    # ---- 1) SAFE vs UNSAFE classification --------------------------------
    def _classify_cells(self):
        """
        Mark every cell whose center falls inside the (margin-inflated) zone
        as UNSAFE. The margin is the zone's own margin PLUS the braking
        distance at the assumed speed -- so faster operation automatically
        widens the forbidden band (Sebastian's velocity point).

        We only STORE the unsafe cells (a set of (i,j,k)) instead of a full
        3D array -- the zone is a small fraction of the workspace, so this is
        far lighter and lookups are O(1).
        """
        self.unsafe = set()
        if self.zone is None:
            return
        extra = braking_distance(self.speed, self.decel)
        # temporarily inflate: test cell centers against zone bounds + extra
        xmin, ymin, zmin, xmax, ymax, zmax = self.zone.inflated()
        xmin -= extra; ymin -= extra; zmin -= extra
        xmax += extra; ymax += extra; zmax += extra
        # only iterate cells that can possibly overlap the inflated box
        i_lo, j_lo, k_lo = self.cell_of(xmin, ymin, zmin)
        i_hi, j_hi, k_hi = self.cell_of(xmax, ymax, zmax)
        for i in range(i_lo, i_hi + 1):
            for j in range(j_lo, j_hi + 1):
                for k in range(k_lo, k_hi + 1):
                    cx, cy, cz = self.center_of(i, j, k)
                    if xmin <= cx <= xmax and ymin <= cy <= ymax and zmin <= cz <= zmax:
                        self.unsafe.add((i, j, k))

    def is_cell_safe(self, i, j, k) -> bool:
        return (i, j, k) not in self.unsafe

    # ---- coordinate <-> cell conversion -----------------------------------
    def cell_of(self, x, y, z):
        """Which cell (i,j,k) contains the point (x,y,z)? Clamped to the grid."""
        i = int((x - self.x0) / self.cell_size)
        j = int((y - self.y0) / self.cell_size)
        k = int((z - self.z0) / self.cell_size)
        return (max(0, min(i, self.nx - 1)),
                max(0, min(j, self.ny - 1)),
                max(0, min(k, self.nz - 1)))

    def center_of(self, i, j, k):
        """The um coordinates of the CENTER of cell (i,j,k) -- a grid waypoint."""
        return (self.x0 + (i + 0.5) * self.cell_size,
                self.y0 + (j + 0.5) * self.cell_size,
                self.z0 + (k + 0.5) * self.cell_size)

    # ---- 2) which grid cells does a move cross? ---------------------------
    def crossed_cells(self, start: Point, end: Point):
        """
        Return the ordered list of (i,j,k) cells the straight line start->end
        passes through. Amanatides-Woo voxel traversal: walk cell-by-cell,
        always stepping across whichever cell boundary the ray hits next.
        EXACT -- it cannot skip a cell the way point-sampling can.
        """
        cur = self.cell_of(start.x, start.y, start.z)
        last = self.cell_of(end.x, end.y, end.z)
        cells = [cur]
        if cur == last:
            return cells

        dx, dy, dz = end.x - start.x, end.y - start.y, end.z - start.z

        def setup(axis_pos, d, origin, idx):
            """step direction, t to first boundary, t per full cell -- one axis."""
            if d > 0:
                step = 1
                boundary = origin + (idx + 1) * self.cell_size
                t_max = (boundary - axis_pos) / d
                t_delta = self.cell_size / d
            elif d < 0:
                step = -1
                boundary = origin + idx * self.cell_size
                t_max = (boundary - axis_pos) / d
                t_delta = -self.cell_size / d
            else:
                step, t_max, t_delta = 0, math.inf, math.inf
            return step, t_max, t_delta

        i, j, k = cur
        si, tmi, tdi = setup(start.x, dx, self.x0, i)
        sj, tmj, tdj = setup(start.y, dy, self.y0, j)
        sk, tmk, tdk = setup(start.z, dz, self.z0, k)

        # walk until we reach the end cell (t in [0,1] covers the segment)
        while (i, j, k) != last and min(tmi, tmj, tmk) <= 1.0:
            if tmi <= tmj and tmi <= tmk:
                i += si; tmi += tdi
            elif tmj <= tmk:
                j += sj; tmj += tdj
            else:
                k += sk; tmk += tdk
            if not (0 <= i < self.nx and 0 <= j < self.ny and 0 <= k < self.nz):
                break
            cells.append((i, j, k))
        return cells

    def is_move_safe_grid(self, start: Point, end: Point) -> bool:
        """Grid version of pathplan.is_move_safe: every crossed cell must be SAFE."""
        return all(self.is_cell_safe(*c) for c in self.crossed_cells(start, end))

    # ---- 3) follow the grid: plan a waypoint path -------------------------
    def plan_grid_path(self, start: Point, end: Point):
        """
        Plan a route from start to end that only passes through SAFE cells.

        Returns a list of Points: [start, waypoint, waypoint, ..., end], where
        each waypoint is the CENTER of a safe grid cell -- i.e. the robot
        "follows the grid". Returns [start, end] if the straight line is
        already safe. Returns None if no route exists.

        BFS through the 6-connected grid (up/down/left/right/forward/back) --
        guaranteed to find the shortest route in number of cells if one exists.
        The raw cell path is then SMOOTHED: consecutive waypoints that a safe
        straight line can skip over are removed (checked with pathplan's exact
        is_move_safe, so smoothing can never re-introduce a collision).
        """
        # nothing to plan if the straight line is already clear
        if self.zone is None or (self.is_move_safe_grid(start, end)
                                 and is_move_safe(start, end, self.zone)):
            return [start, end]

        c_start = self.cell_of(start.x, start.y, start.z)
        c_end = self.cell_of(end.x, end.y, end.z)
        if not self.is_cell_safe(*c_start) or not self.is_cell_safe(*c_end):
            return None  # start or target sits inside the forbidden region

        # BFS over safe cells
        parent = {c_start: None}
        q = deque([c_start])
        found = False
        while q:
            cur = q.popleft()
            if cur == c_end:
                found = True
                break
            i, j, k = cur
            for di, dj, dk in ((1,0,0), (-1,0,0), (0,1,0), (0,-1,0), (0,0,1), (0,0,-1)):
                nb = (i + di, j + dj, k + dk)
                if (0 <= nb[0] < self.nx and 0 <= nb[1] < self.ny
                        and 0 <= nb[2] < self.nz
                        and nb not in parent and self.is_cell_safe(*nb)):
                    parent[nb] = cur
                    q.append(nb)
        if not found:
            return None

        # rebuild the cell chain, convert cell centers to um waypoints
        chain = []
        c = c_end
        while c is not None:
            chain.append(c)
            c = parent[c]
        chain.reverse()
        path = [start] + [Point(*self.center_of(*c)) for c in chain[1:-1]] + [end]

        # smooth: skip intermediate waypoints when the exact ray-box test says
        # the direct hop is safe. This turns staircase BFS paths into the
        # minimal set of waypoints while staying provably collision-free.
        smoothed = [path[0]]
        idx = 0
        while idx < len(path) - 1:
            far = idx + 1
            for probe in range(len(path) - 1, idx, -1):
                if is_move_safe(path[idx], path[probe], self.zone):
                    far = probe
                    break
            smoothed.append(path[far])
            idx = far
        return smoothed

    # ---- reporting ---------------------------------------------------------
    def report_move(self, start: Point, end: Point):
        """
        One-call summary for a move, in the order Sebastian described:
        1. is it safe?  2. which cells does it cross (and which are unsafe)?
        3. the grid path to follow if it isn't safe.
        """
        cells = self.crossed_cells(start, end)
        bad = [c for c in cells if not self.is_cell_safe(*c)]
        safe = not bad
        path = self.plan_grid_path(start, end)
        return {
            "safe_straight": safe,
            "cells_crossed": cells,
            "unsafe_cells": bad,
            "grid_path": [p.as_tuple() for p in path] if path else None,
            "n_waypoints": (len(path) - 2) if path else None,  # excluding start/end
        }

    def summary(self):
        total = self.nx * self.ny * self.nz
        return (f"grid {self.nx}x{self.ny}x{self.nz} = {total} cells "
                f"({self.cell_size:.0f} um cells), {len(self.unsafe)} unsafe, "
                f"braking margin at {self.speed:.0f} um/s = "
                f"{braking_distance(self.speed, self.decel):.0f} um")


if __name__ == "__main__":
    # demo on the REAL workspace + the placeholder keep-out zone
    zone = Zone(100000, 40000, 0, 140000, 70000, 20000, margin=2000)
    ws = {"X": (0, 254000), "Y": (0, 118000), "Z": (0, 40000)}
    g = GridPlanner(workspace=ws, zone=zone, cell_size=5000)
    print(g.summary())

    start = Point(50000, 55000, 10000)
    end = Point(200000, 55000, 10000)   # straight line goes through the zone

    r = g.report_move(start, end)
    print("\nstraight move safe?", r["safe_straight"])
    print("cells crossed:", len(r["cells_crossed"]),
          "| unsafe among them:", len(r["unsafe_cells"]))
    print("grid path waypoints:")
    for p in r["grid_path"]:
        print("   ", tuple(round(v) for v in p))

    # vectors + velocity
    mv = MotionVector.toward(start, end, speed=10000)   # 10 mm/s toward target
    print("\nmotion vector: speed", mv.speed(), "um/s, direction", 
          tuple(round(d, 2) for d in mv.direction()))
    print("braking distance at that speed:", 
          round(braking_distance(mv.speed())), "um")