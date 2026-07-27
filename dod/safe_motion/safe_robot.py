"""
safe_robot.py — SafeRobot class: obstacle-avoiding motion layer for the MFX DoD robot.

SafeRobot inherits from DoD and overrides all motion methods.  When
``safe_mode`` is ``False`` every call passes through transparently to the
parent with zero overhead.  When ``safe_mode`` is ``True`` each motion method
applies a policy appropriate to its type before executing:

    do_move          Full path plan via VisibilityGraph; executes waypoints
                     sequentially via super().do_move(); verifies position
                     after each waypoint.

    move_x_rel /     Small-move threshold check + endpoint check.
    move_y_rel       Large moves (> threshold) are blocked.

    move_rel         safe_mode_locked guard only; delegates to single-axis
                     overrides via DoD.move_rel → self.move_x/y_rel (MRO).

    move_x_abs /     Displacement vs. current position; applies same
    move_y_abs       threshold + endpoint policy as rel moves.

    move_z_abs /     Z-only; endpoint check against build plate bounds.
    move_z_rel       (Z is decoupled from XY exclusion zones.)

    do_task /        Task precondition whitelist: verify robot is at the
    take_probe       required start position before executing.

Divergence handling
-------------------
If post-move verification detects a position error beyond ``position_tolerance_um``:
  - ``stop_task()`` is called immediately.
  - ``safe_mode_locked`` is set to ``True``.
  - A description is printed to the console.
  - All subsequent safe-mode calls raise ``RuntimeError`` until the operator
    calls ``acknowledge_divergence()``.

``acknowledge_divergence()`` clears the lock but does NOT re-enable safe_mode.

Coordinate system
-----------------
All registry coordinates and exclusion zones are in robot frame (µm).
Robot X = Hutch X,  Robot Y = Hutch Z,  Robot Z = −Hutch Y.
The hutch→robot conversion for move_rel(coordinates='hutch') is handled
entirely by DoD.move_rel — SafeRobot does not re-implement it.
"""

from __future__ import annotations

import json
from typing import Optional

# DoD and its reconnect decorator.
# Requires MFX_Hutch_Python/mfx on sys.path during development:
#   import sys; sys.path.insert(0, '/path/to/MFX_Hutch_Python/mfx')
from dod.dod import DoD, _with_reconnect

from .registry import (
    load_registry,
    load_registry_from_json,
    lookup_name_by_coords,
    RegistryDict,
    WAYPOINT_COORD_TOLERANCE_UM,
)
from .obb import OBB
from .graph import VisibilityGraph


class SafeRobot(DoD):
    """DoD subclass with obstacle-avoiding safe-motion layer.

    Parameters
    ----------
    robot_config_path:
        Path to the robot's configuration file.  Accepts either:

        - A Windows INI file (``.ini``) — parsed directly from the robot's
          native config format.
        - A positions JSON file (``.json``) — produced by the setup script
          as a sidecar alongside the INI.  Use this path when the full INI
          is not available on the server (e.g. during development or when
          the INI must not be committed to version control).
    exclusion_zone_config:
        Path to the exclusion zone JSON config file.  Must contain at minimum
        ``build_plate``, ``clearance_um``, and ``obstacles`` keys.  May also
        contain ``small_move_threshold_um``, ``task_preconditions``, and
        ``waypoint_speeds``.
    position_tolerance_um:
        Maximum allowed deviation (per axis) between actual and expected
        position after each waypoint move.  Default 500 µm.
    waypoint_coord_tolerance_um:
        Tolerance for reverse-lookup of planner-returned (x, y) coordinates
        to position names in the registry.  Float-matching only — not a safety
        parameter.  Default ``WAYPOINT_COORD_TOLERANCE_UM`` (10 µm).
    modules, ip, port, supported_json, log_file:
        Forwarded to DoD.__init__ unchanged.
    """

    def __init__(
        self,
        robot_config_path: str,
        exclusion_zone_config: str,
        position_tolerance_um: float = 500.0,
        waypoint_coord_tolerance_um: float = WAYPOINT_COORD_TOLERANCE_UM,
        modules=None,
        ip: str = "172.21.39.172",
        port: int = 9999,
        supported_json: str = (
            "/cds/group/pcds/pyps/apps/hutch-python/mfx/dod/supported.json"
        ),
        log_file: str = ("/cds/group/pcds/pyps/apps/hutch-python/mfx/dod/dod.log"),
    ) -> None:
        super().__init__(
            modules=modules,
            ip=ip,
            port=port,
            supported_json=supported_json,
            log_file=log_file,
        )

        # ----------------------------------------------------------------
        # Safe-mode state
        # ----------------------------------------------------------------

        #: Set to True to enable safe-mode motion checks.
        self.safe_mode: bool = False

        #: Locked after a post-move divergence; cleared by acknowledge_divergence().
        self.safe_mode_locked: bool = False

        #: Stored divergence info for acknowledge_divergence() to summarise.
        self._last_divergence: Optional[dict] = None

        # ----------------------------------------------------------------
        # Tunable parameters
        # ----------------------------------------------------------------

        self._position_tolerance_um: float = position_tolerance_um
        self._waypoint_coord_tolerance_um: float = waypoint_coord_tolerance_um

        # ----------------------------------------------------------------
        # Load position registry — INI or JSON depending on file extension
        # ----------------------------------------------------------------

        self._registry: RegistryDict
        self._sentinel_str: Optional[str]
        if robot_config_path.lower().endswith(".json"):
            self._registry, self._sentinel_str = load_registry_from_json(
                robot_config_path
            )
        else:
            self._registry, self._sentinel_str = load_registry(robot_config_path)

        # ----------------------------------------------------------------
        # Load exclusion zone config and build graph
        # ----------------------------------------------------------------

        with open(exclusion_zone_config, "r") as fh:
            config: dict = json.load(fh)

        self._small_move_threshold_um: float = float(
            config.get("small_move_threshold_um", 100.0)
        )
        self._task_preconditions: dict = config.get("task_preconditions", {})

        plate = config["build_plate"]
        clearance = float(config["clearance_um"])
        self._plate_z_um: float = float(plate["z_um"])

        obstacles: list = [
            OBB(
                cx=float(obs["cx_um"]),
                cy=float(obs["cy_um"]),
                w=float(obs["w_um"]),
                h=float(obs["h_um"]),
                angle=float(obs["angle_deg"]),
            )
            for obs in config.get("obstacles", [])
        ]

        self._buffered_obstacles: list = [obs.expand(clearance) for obs in obstacles]

        self._graph: VisibilityGraph = VisibilityGraph(
            obstacles=obstacles,
            clearance=clearance,
            plate_x=float(plate["x_um"]),
            plate_y=float(plate["y_um"]),
        )

    # ------------------------------------------------------------------
    # Operator control
    # ------------------------------------------------------------------

    def acknowledge_divergence(self) -> None:
        """Clear the safe_mode_locked flag set by a post-move divergence.

        Prints a summary of the acknowledged divergence.  Does NOT
        automatically re-enable safe_mode — the operator must do that
        explicitly after verifying the robot state.
        """
        if not self.safe_mode_locked:
            print("[SafeRobot] No divergence lock is active.")
            return

        if self._last_divergence is not None:
            d = self._last_divergence
            print(
                f"[SafeRobot] Acknowledging divergence at '{d['position_name']}':\n"
                f"  Expected : X={d['expected']['X']} Y={d['expected']['Y']} "
                f"Z={d['expected']['Z']} µm\n"
                f"  Actual   : X={d['actual']['X']:.0f} Y={d['actual']['Y']:.0f} "
                f"Z={d['actual']['Z']:.0f} µm\n"
                f"  Error    : dX={d['error_um']['X']:.0f} dY={d['error_um']['Y']:.0f} "
                f"dZ={d['error_um']['Z']:.0f} µm"
            )

        self.safe_mode_locked = False
        self._last_divergence = None
        print(
            "[SafeRobot] Divergence lock cleared.  "
            "Re-enable safe_mode manually when the robot state is confirmed."
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_safe_mode_locked(self) -> None:
        """Raise RuntimeError if safe_mode_locked is True."""
        if self.safe_mode_locked:
            raise RuntimeError(
                "[SafeRobot] Safe mode is LOCKED due to a previous position divergence.  "
                "Call acknowledge_divergence() to clear the lock before issuing new moves."
            )

    def _get_current_xyz(self) -> dict:
        """Query the robot's current real position.

        Establishes a connection (idempotent) and returns
        ``{'X': float, 'Y': float, 'Z': float}`` in µm.

        Leaves the connection open for the subsequent super() call.
        """
        self.client.connect("Test")
        r = self.client.get_current_positions()
        return r.RESULTS["PositionReal"]

    def _endpoint_clear(self, x: float, y: float) -> bool:
        """Return True if (x, y) is outside all buffered exclusion zones."""
        return not any(obs.contains_point(x, y) for obs in self._buffered_obstacles)

    def _verify_position(self, expected_name: str) -> None:
        """Compare actual robot position to registry entry for *expected_name*.

        If any axis exceeds ``position_tolerance_um``:
          - Calls stop_task().
          - Sets safe_mode_locked = True.
          - Stores divergence details in _last_divergence.
          - Prints a description and raises RuntimeError.
        """
        actual = self._get_current_xyz()
        expected = self._registry[expected_name]

        dx = abs(actual["X"] - expected["X"])
        dy = abs(actual["Y"] - expected["Y"])
        dz = abs(actual["Z"] - expected["Z"])
        max_err = max(dx, dy, dz)

        if max_err > self._position_tolerance_um:
            self.stop_task()
            self.safe_mode_locked = True
            self._last_divergence = {
                "position_name": expected_name,
                "expected": {k: expected[k] for k in ("X", "Y", "Z")},
                "actual": dict(actual),
                "error_um": {"X": dx, "Y": dy, "Z": dz},
            }
            msg = (
                f"[SafeRobot] POST-MOVE DIVERGENCE at '{expected_name}': "
                f"expected ({expected['X']}, {expected['Y']}, {expected['Z']}) µm, "
                f"got ({actual['X']:.0f}, {actual['Y']:.0f}, {actual['Z']:.0f}) µm, "
                f"max error {max_err:.0f} µm "
                f"(tolerance {self._position_tolerance_um:.0f} µm).  "
                f"Safe mode LOCKED.  Call acknowledge_divergence() to clear."
            )
            print(msg)
            raise RuntimeError(msg)

    def _check_precondition_position(self, required_position_name: str) -> None:
        """Verify robot is within tolerance of *required_position_name*.

        Raises RuntimeError if the current position does not match the
        registry entry within ``position_tolerance_um``.
        """
        if required_position_name not in self._registry:
            raise KeyError(
                f"[SafeRobot] Required start position '{required_position_name}' "
                f"not found in registry.  Check the task_preconditions mapping."
            )

        actual = self._get_current_xyz()
        expected = self._registry[required_position_name]

        dx = abs(actual["X"] - expected["X"])
        dy = abs(actual["Y"] - expected["Y"])
        dz = abs(actual["Z"] - expected["Z"])
        max_err = max(dx, dy, dz)

        if max_err > self._position_tolerance_um:
            raise RuntimeError(
                f"[SafeRobot] Precondition FAILED: current position "
                f"({actual['X']:.0f}, {actual['Y']:.0f}, {actual['Z']:.0f}) µm "
                f"does not match required start '{required_position_name}' "
                f"({expected['X']}, {expected['Y']}, {expected['Z']}) µm.  "
                f"Max error: {max_err:.0f} µm "
                f"(tolerance {self._position_tolerance_um:.0f} µm)."
            )

    # ------------------------------------------------------------------
    # Motion overrides
    # ------------------------------------------------------------------

    @_with_reconnect
    def do_move(self, position, safety_test=False, verbose=False):
        """Move to a named position, routing through the path planner in safe mode.

        Safe-mode policy:
          1. Look up target coordinates in registry.
          2. Query the visibility graph for the obstacle-free waypoint sequence.
          3. Execute each waypoint via super().do_move().
          4. Verify actual position after each waypoint.

        Passthrough (safe_mode=False): delegates directly to DoD.do_move().
        """
        self._check_safe_mode_locked()
        if not self.safe_mode:
            return super().do_move(position, safety_test=safety_test, verbose=verbose)

        # Registry lookup for target
        if position not in self._registry:
            raise KeyError(
                f"[SafeRobot] Position '{position}' not found in registry.  "
                f"Ensure the robot INI config has been parsed and the position exists."
            )
        target = self._registry[position]
        target_x, target_y = float(target["X"]), float(target["Y"])

        # Current position
        current = self._get_current_xyz()
        start_x, start_y = current["X"], current["Y"]

        # Path plan
        waypoints = self._graph.query((start_x, start_y), (target_x, target_y))
        if waypoints is None:
            raise RuntimeError(
                f"[SafeRobot] No safe path found from "
                f"({start_x:.0f}, {start_y:.0f}) to '{position}' "
                f"({target_x:.0f}, {target_y:.0f}) µm.  "
                f"Check exclusion zone config and robot position."
            )

        # Execute each waypoint (skip index 0 = current position)
        result = None
        for wp_x, wp_y in waypoints[1:]:
            wp_name = lookup_name_by_coords(
                self._registry,
                wp_x,
                wp_y,
                tolerance_um=self._waypoint_coord_tolerance_um,
            )
            result = super().do_move(wp_name, safety_test=False, verbose=verbose)
            self._verify_position(wp_name)

        return result

    @_with_reconnect
    def move_x_rel(self, delta_x, safety_test=False, verbose=False, wait=True):
        """Relative X move with safe-mode threshold and endpoint checks.

        Safe-mode policy:
          - If |delta_x| > small_move_threshold: blocked.
          - Otherwise: endpoint check; execute via super().

        Passthrough (safe_mode=False): delegates directly to DoD.move_x_rel().
        """
        self._check_safe_mode_locked()
        if not self.safe_mode:
            return super().move_x_rel(
                delta_x, safety_test=safety_test, verbose=verbose, wait=wait
            )

        if abs(delta_x) > self._small_move_threshold_um:
            raise RuntimeError(
                f"[SafeRobot] move_x_rel({delta_x} µm) exceeds small_move_threshold "
                f"({self._small_move_threshold_um} µm).  "
                f"Use do_move() for large moves in safe mode."
            )

        current = self._get_current_xyz()
        endpoint_x = current["X"] + delta_x
        endpoint_y = current["Y"]

        if not self._endpoint_clear(endpoint_x, endpoint_y):
            raise RuntimeError(
                f"[SafeRobot] move_x_rel endpoint "
                f"({endpoint_x:.0f}, {endpoint_y:.0f}) µm "
                f"falls inside an exclusion zone."
            )

        return super().move_x_rel(
            delta_x, safety_test=False, verbose=verbose, wait=wait
        )

    @_with_reconnect
    def move_y_rel(self, delta_y, safety_test=False, verbose=False, wait=True):
        """Relative Y move with safe-mode threshold and endpoint checks.

        Safe-mode policy:
          - If |delta_y| > small_move_threshold: blocked.
          - Otherwise: endpoint check; execute via super().

        Passthrough (safe_mode=False): delegates directly to DoD.move_y_rel().
        """
        self._check_safe_mode_locked()
        if not self.safe_mode:
            return super().move_y_rel(
                delta_y, safety_test=safety_test, verbose=verbose, wait=wait
            )

        if abs(delta_y) > self._small_move_threshold_um:
            raise RuntimeError(
                f"[SafeRobot] move_y_rel({delta_y} µm) exceeds small_move_threshold "
                f"({self._small_move_threshold_um} µm).  "
                f"Use do_move() for large moves in safe mode."
            )

        current = self._get_current_xyz()
        endpoint_x = current["X"]
        endpoint_y = current["Y"] + delta_y

        if not self._endpoint_clear(endpoint_x, endpoint_y):
            raise RuntimeError(
                f"[SafeRobot] move_y_rel endpoint "
                f"({endpoint_x:.0f}, {endpoint_y:.0f}) µm "
                f"falls inside an exclusion zone."
            )

        return super().move_y_rel(
            delta_y, safety_test=False, verbose=verbose, wait=wait
        )

    def move_rel(
        self, dx=0, dy=0, dz=0, coordinates="robot", safety_test=False, verbose=False
    ):
        """Relative multi-axis move.

        Safe-mode policy:
          - safe_mode_locked check at entry.
          - Delegates to super().move_rel() which calls self.move_x_rel(),
            self.move_y_rel(), self.move_z_rel() via Python MRO — those
            SafeRobot overrides carry out the per-axis safety checks.
          - The hutch→robot coordinate conversion is handled entirely by
            DoD.move_rel; SafeRobot does not re-implement it.

        Passthrough (safe_mode=False): same delegation path; single-axis
        overrides also pass through when safe_mode is False.
        """
        self._check_safe_mode_locked()
        return super().move_rel(
            dx=dx,
            dy=dy,
            dz=dz,
            coordinates=coordinates,
            safety_test=safety_test,
            verbose=verbose,
        )

    @_with_reconnect
    def move_x_abs(self, position_x, safety_test=False, verbose=False):
        """Absolute X move with safe-mode threshold and endpoint checks.

        Safe-mode policy:
          - Computes displacement = |target_x − current_x|.
          - If displacement > small_move_threshold: blocked.
          - Otherwise: endpoint check; execute via super().

        Passthrough (safe_mode=False): delegates directly to DoD.move_x_abs().
        """
        self._check_safe_mode_locked()
        if not self.safe_mode:
            return super().move_x_abs(
                position_x, safety_test=safety_test, verbose=verbose
            )

        current = self._get_current_xyz()
        displacement = abs(float(position_x) - current["X"])

        if displacement > self._small_move_threshold_um:
            raise RuntimeError(
                f"[SafeRobot] move_x_abs displacement ({displacement:.0f} µm) "
                f"exceeds small_move_threshold ({self._small_move_threshold_um} µm).  "
                f"Use do_move() for large moves in safe mode."
            )

        if not self._endpoint_clear(float(position_x), current["Y"]):
            raise RuntimeError(
                f"[SafeRobot] move_x_abs endpoint "
                f"({float(position_x):.0f}, {current['Y']:.0f}) µm "
                f"falls inside an exclusion zone."
            )

        return super().move_x_abs(position_x, safety_test=False, verbose=verbose)

    @_with_reconnect
    def move_y_abs(self, position_y, safety_test=False, verbose=False):
        """Absolute Y move with safe-mode threshold and endpoint checks.

        Safe-mode policy:
          - Computes displacement = |target_y − current_y|.
          - If displacement > small_move_threshold: blocked.
          - Otherwise: endpoint check; execute via super().

        Passthrough (safe_mode=False): delegates directly to DoD.move_y_abs().
        """
        self._check_safe_mode_locked()
        if not self.safe_mode:
            return super().move_y_abs(
                position_y, safety_test=safety_test, verbose=verbose
            )

        current = self._get_current_xyz()
        displacement = abs(float(position_y) - current["Y"])

        if displacement > self._small_move_threshold_um:
            raise RuntimeError(
                f"[SafeRobot] move_y_abs displacement ({displacement:.0f} µm) "
                f"exceeds small_move_threshold ({self._small_move_threshold_um} µm).  "
                f"Use do_move() for large moves in safe mode."
            )

        if not self._endpoint_clear(current["X"], float(position_y)):
            raise RuntimeError(
                f"[SafeRobot] move_y_abs endpoint "
                f"({current['X']:.0f}, {float(position_y):.0f}) µm "
                f"falls inside an exclusion zone."
            )

        return super().move_y_abs(position_y, safety_test=False, verbose=verbose)

    @_with_reconnect
    def move_z_abs(self, position_z, safety_test=False, verbose=False):
        """Absolute Z move with safe-mode build-plate bounds check.

        Z is decoupled from XY exclusion zones (robot is at Z=0 during all
        XY travel).  The only check is that the target Z is within the build
        plate range [0, plate_z_um].

        Passthrough (safe_mode=False): delegates directly to DoD.move_z_abs().
        """
        self._check_safe_mode_locked()
        if not self.safe_mode:
            return super().move_z_abs(
                position_z, safety_test=safety_test, verbose=verbose
            )

        if not (0.0 <= float(position_z) <= self._plate_z_um):
            raise RuntimeError(
                f"[SafeRobot] move_z_abs target Z={position_z} µm is outside "
                f"build plate range [0, {self._plate_z_um:.0f}] µm."
            )

        return super().move_z_abs(position_z, safety_test=False, verbose=verbose)

    @_with_reconnect
    def move_z_rel(self, delta_z, safety_test=False, verbose=False, wait=True):
        """Relative Z move with safe-mode build-plate bounds check.

        Z is decoupled from XY exclusion zones.  The check verifies that
        current_z + delta_z remains within [0, plate_z_um].

        Passthrough (safe_mode=False): delegates directly to DoD.move_z_rel().
        """
        self._check_safe_mode_locked()
        if not self.safe_mode:
            return super().move_z_rel(
                delta_z, safety_test=safety_test, verbose=verbose, wait=wait
            )

        current = self._get_current_xyz()
        target_z = current["Z"] + float(delta_z)

        if not (0.0 <= target_z <= self._plate_z_um):
            raise RuntimeError(
                f"[SafeRobot] move_z_rel endpoint Z={target_z:.0f} µm is outside "
                f"build plate range [0, {self._plate_z_um:.0f}] µm."
            )

        return super().move_z_rel(
            delta_z, safety_test=False, verbose=verbose, wait=wait
        )

    @_with_reconnect
    def do_task(
        self,
        task_name,
        safety_check=False,
        handle_dialog="raise",
        verbose=False,
        poll_interval=2.0,
    ):
        """Execute a named task with safe-mode precondition check.

        Safe-mode policy:
          - Task must be listed in ``task_preconditions`` (from config).
            Tasks not on the whitelist are blocked.
          - Robot must be at the required start position within
            ``position_tolerance_um`` before the task is issued.

        Passthrough (safe_mode=False): delegates directly to DoD.do_task().

        Note: this enforces a verified entry condition; it does not provide
        path safety *inside* the task.  Document task safety assumptions
        clearly in the exclusion zone config.
        """
        self._check_safe_mode_locked()
        if not self.safe_mode:
            return super().do_task(
                task_name,
                safety_check=safety_check,
                handle_dialog=handle_dialog,
                verbose=verbose,
                poll_interval=poll_interval,
            )

        if task_name not in self._task_preconditions:
            raise RuntimeError(
                f"[SafeRobot] Task '{task_name}' is not on the safe-mode whitelist.  "
                f"Add it to 'task_preconditions' in the exclusion zone config, "
                f"or disable safe_mode to run unwhitelisted tasks."
            )

        required_position = self._task_preconditions[task_name]
        self._check_precondition_position(required_position)

        return super().do_task(
            task_name,
            safety_check=False,
            handle_dialog=handle_dialog,
            verbose=verbose,
            poll_interval=poll_interval,
        )

    @_with_reconnect
    def take_probe(
        self, channel, well, volume, check_task=True, timeout=None, verbose=False
    ):
        """Aspirate a probe sample with safe-mode precondition check.

        Safe-mode policy:
          - ``'take_probe'`` must be listed in ``task_preconditions``.
          - Robot must be at the required start position within
            ``position_tolerance_um`` before the command is issued.

        Passthrough (safe_mode=False): delegates directly to DoD.take_probe().
        """
        self._check_safe_mode_locked()
        if not self.safe_mode:
            return super().take_probe(
                channel,
                well,
                volume,
                check_task=check_task,
                timeout=timeout,
                verbose=verbose,
            )

        if "take_probe" not in self._task_preconditions:
            raise RuntimeError(
                "[SafeRobot] 'take_probe' is not on the safe-mode whitelist.  "
                "Add 'take_probe' → required_start_position to 'task_preconditions' "
                "in the exclusion zone config."
            )

        required_position = self._task_preconditions["take_probe"]
        self._check_precondition_position(required_position)

        return super().take_probe(
            channel,
            well,
            volume,
            check_task=check_task,
            timeout=timeout,
            verbose=verbose,
        )
