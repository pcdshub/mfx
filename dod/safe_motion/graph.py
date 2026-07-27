"""
graph.py — Visibility graph construction and Dijkstra path query.

Setup phase (once per obstacle layout):
  1. Expand each OBB by the clearance margin → buffered obstacles.
  2. Extract the 4 corners of each buffered OBB + build-plate corners.
  3. Filter out nodes outside the plate or inside any buffered obstacle.
  4. For every ordered pair (A, B) of nodes, if the Chebyshev path A→B
     is clear, add a directed edge with cost = Chebyshev distance.

Query phase (per start→goal request):
  1. Temporarily extend the graph with start and goal.
  2. Run Dijkstra on the extended adjacency dict.
  3. Return the ordered list of waypoints; the temporary nodes are
     not written back to self.adj (query builds a local copy).

The graph is DIRECTED because the Chebyshev path A→B and B→A are not
symmetric: they follow different trajectories (different mid-points),
and one may clip an obstacle while the other does not.
"""

from __future__ import annotations
import heapq
from typing import Dict, List, Optional, Tuple

from .obb import OBB
from .chebyshev import path_is_clear, chebyshev_cost

Point = Tuple[float, float]
Adj = Dict[Point, List[Tuple[float, Point]]]  # node → [(cost, neighbour)]


class VisibilityGraph:
    """Pre-built directed visibility graph for a fixed obstacle layout.

    Args:
        obstacles:  Raw (un-buffered) OBB list loaded from config.
        clearance:  Buffer distance in µm added to every obstacle side.
        plate_x:    Build plate width  in µm (X axis).
        plate_y:    Build plate height in µm (Y axis).
    """

    def __init__(
        self, obstacles: List[OBB], clearance: float, plate_x: float, plate_y: float
    ) -> None:
        self.raw_obstacles = obstacles
        self.clearance = clearance
        self.plate_x = plate_x
        self.plate_y = plate_y

        self.buffered: List[OBB] = [obs.expand(clearance) for obs in obstacles]
        self.nodes: List[Point] = []
        self.adj: Adj = {}

        self._build()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _inside_plate(self, x: float, y: float) -> bool:
        return 0.0 <= x <= self.plate_x and 0.0 <= y <= self.plate_y

    def _node_valid(self, pt: Point) -> bool:
        """A node is valid if it is on the plate and outside every buffered OBB."""
        x, y = pt
        if not self._inside_plate(x, y):
            return False
        return not any(obs.contains_point(x, y) for obs in self.buffered)

    def _build(self) -> None:
        # Candidate nodes: corners of buffered OBBs + build-plate corners.
        candidates: List[Point] = []
        for obs in self.buffered:
            candidates.extend(obs.corners())
        candidates += [
            (0.0, 0.0),
            (self.plate_x, 0.0),
            (0.0, self.plate_y),
            (self.plate_x, self.plate_y),
        ]

        # Deduplicate (floating-point corners can repeat) and filter.
        seen: set = set()
        self.nodes = []
        for pt in candidates:
            key = (round(pt[0], 2), round(pt[1], 2))
            if key not in seen and self._node_valid(pt):
                seen.add(key)
                self.nodes.append(pt)

        # Build directed adjacency list.
        self.adj = {pt: [] for pt in self.nodes}
        n = len(self.nodes)
        for i in range(n):
            for j in range(i + 1, n):
                a, b = self.nodes[i], self.nodes[j]
                cost = chebyshev_cost(a[0], a[1], b[0], b[1])
                if path_is_clear(a[0], a[1], b[0], b[1], self.buffered):
                    self.adj[a].append((cost, b))
                if path_is_clear(b[0], b[1], a[0], a[1], self.buffered):
                    self.adj[b].append((cost, a))

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(self, start: Point, goal: Point) -> Optional[List[Point]]:
        """Find the cheapest Chebyshev path from *start* to *goal*.

        Returns an ordered list of (x, y) waypoints, or None if no path exists.
        Does not modify self.adj (builds a local copy for the query).
        """
        if start == goal:
            return [start]

        # Shallow copy: new lists per node so self.adj is never mutated.
        temp: Adj = {pt: list(edges) for pt, edges in self.adj.items()}

        # Add start and goal (overwrite if they coincide with existing nodes,
        # which is rare but safe — Dijkstra handles extra edges gracefully).
        for pt in (start, goal):
            temp[pt] = []

        # Connect start and goal to all permanent graph nodes.
        for new_pt in (start, goal):
            for other in self.nodes:
                cost = chebyshev_cost(new_pt[0], new_pt[1], other[0], other[1])
                if path_is_clear(
                    new_pt[0], new_pt[1], other[0], other[1], self.buffered
                ):
                    temp[new_pt].append((cost, other))
                if path_is_clear(
                    other[0], other[1], new_pt[0], new_pt[1], self.buffered
                ):
                    temp[other].append((cost, new_pt))

        # Connect start ↔ goal directly (covers the obstacle-free case).
        cost_sg = chebyshev_cost(start[0], start[1], goal[0], goal[1])
        if path_is_clear(start[0], start[1], goal[0], goal[1], self.buffered):
            temp[start].append((cost_sg, goal))
        if path_is_clear(goal[0], goal[1], start[0], start[1], self.buffered):
            temp[goal].append((cost_sg, start))

        return _dijkstra(start, goal, temp)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> str:
        n_nodes = len(self.nodes)
        n_edges = sum(len(v) for v in self.adj.values())
        return (
            f"VisibilityGraph: {n_nodes} nodes, {n_edges} directed edges, "
            f"{len(self.buffered)} buffered obstacles "
            f"(clearance={self.clearance / 1000:.1f} mm)"
        )


# ------------------------------------------------------------------
# Dijkstra (module-level, operates on any Adj dict)
# ------------------------------------------------------------------


def _dijkstra(start: Point, goal: Point, adj: Adj) -> Optional[List[Point]]:
    """Standard Dijkstra on a directed adjacency dict.

    Returns the optimal path as an ordered list of Points, or None.
    """
    dist: Dict[Point, float] = {start: 0.0}
    prev: Dict[Point, Optional[Point]] = {start: None}
    heap: List[Tuple[float, Point]] = [(0.0, start)]
    visited: set = set()

    while heap:
        d, u = heapq.heappop(heap)
        if u in visited:
            continue
        visited.add(u)

        if u == goal:
            # Reconstruct path.
            path: List[Point] = []
            node: Optional[Point] = goal
            while node is not None:
                path.append(node)
                node = prev[node]
            path.reverse()
            return path

        for cost, v in adj.get(u, []):
            nd = d + cost
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(heap, (nd, v))

    return None  # goal unreachable
