"""
dod_safety_tools.py -- safety tooling for the DoD robot.

Three tools:
  - preflight_check(): sanity-checks the coordinate file and workspace bounds.
  - preview_move(robot, target): shows what a move WOULD do (path, distance,
    whether it's safe) WITHOUT moving the robot. Uses the real pathplan collision
    logic, and returns the planned path so the GUI can draw it.
  - live_safety_monitor(robot): watches position and logs warnings to CSV.

Design principles (the fixes):
  - Collision checking uses the SAME tested pathplan logic as the rest of the
    project -- not a separate, weaker re-implementation.
  - Tools operate on a robot that is PASSED IN, so they reason about the same
    robot the GUI is showing (not a fresh separate object).
  - Missing capabilities are reported CLEARLY ("not available in dummy mode"),
    never silently swallowed -- so a check that didn't run can't look like it passed.
"""

import json
import time
from datetime import datetime

from pathplan import Point, Zone, is_move_safe, plan_detour, segment_hits_zone

WORKSPACE = {"X": (0, 254000), "Y": (0, 118000), "Z": (0, 40000)}
POSITIONS_FILE = "named_position_coords.json"

# The keep-out zone (PLACEHOLDER until confirmed with Sebastian). Kept here so
# all the safety tools share ONE definition of the zone.
KEEP_OUT = Zone(100000, 40000, 0, 140000, 70000, 20000, margin=2000)


def load_positions():
    with open(POSITIONS_FILE, "r") as f:
        return json.load(f)


def inside_workspace(pos):
    return (WORKSPACE["X"][0] <= pos["X"] <= WORKSPACE["X"][1]
            and WORKSPACE["Y"][0] <= pos["Y"] <= WORKSPACE["Y"][1]
            and WORKSPACE["Z"][0] <= pos["Z"] <= WORKSPACE["Z"][1])


def _point_from(pos):
    return Point(pos["X"], pos["Y"], pos["Z"])


# ---------------------------------------------------------------- pre-flight
def preflight_check():
    """Return (passed, total, lines) and also print. Pure data checks, no robot."""
    lines = []
    checks = []
    positions = load_positions()

    checks.append(("Coordinate file loaded", len(positions) > 0))
    for name in ["Home", "InteractionPoint"]:
        checks.append((f"Required position exists: {name}", name in positions))

    bad = [n for n, p in positions.items() if not inside_workspace(p)]
    checks.append(("All saved positions inside workspace", len(bad) == 0))

    # every named position should itself be outside the keep-out zone
    in_zone = [n for n, p in positions.items() if KEEP_OUT.contains(_point_from(p))]
    checks.append(("No saved position sits inside the keep-out zone", len(in_zone) == 0))

    passed = 0
    lines.append("=== DoD Automated Pre-Flight Checklist ===")
    for label, ok in checks:
        lines.append(f"[{'PASS' if ok else 'FAIL'}] {label}")
        if ok:
            passed += 1
    lines.append(f"\nPre-flight result: {passed}/{len(checks)} checks passed")
    if bad:
        lines.append("\nPositions OUTSIDE workspace:")
        for n in bad:
            lines.append(f"  - {n}: {positions[n]}")
    if in_zone:
        lines.append("\nPositions INSIDE the keep-out zone:")
        for n in in_zone:
            lines.append(f"  - {n}: {positions[n]}")
    lines.append("==========================================")

    text = "\n".join(lines)
    print("\n" + text + "\n")
    return passed, len(checks), text


# ------------------------------------------------------------- move preview
def preview_move(robot, target_name):
    """
    Preview a move to a named position WITHOUT moving the robot.
    Works with either a SafeRobot (has .where()) or a DoDDummy (has .where()).
    Returns {ok, message, path}.
    """
    positions = load_positions()
    lines = ["=== Automated Move Preview ==="]

    if target_name not in positions:
        msg = f"[FAIL] Unknown target position: {target_name}"
        print(msg)
        return {"ok": False, "message": msg, "path": None}

    # current position from whichever robot object we were given
    p = robot.where()
    current = {"X": p.x, "Y": p.y, "Z": p.z}
    target = positions[target_name]
    start_pt = _point_from(current)
    end_pt = _point_from(target)

    lines.append(f"Current: X={current['X']:.0f} Y={current['Y']:.0f} Z={current['Z']:.0f}")
    lines.append(f"Target:  {target_name}  X={target['X']} Y={target['Y']} Z={target['Z']}")

    dist = ((target['X']-current['X'])**2 + (target['Y']-current['Y'])**2 + (target['Z']-current['Z'])**2) ** 0.5
    lines.append(f"Distance: {dist:.0f} um")

    # workspace check
    if not inside_workspace(target):
        lines.append("[RISK: HIGH] Target is OUTSIDE the workspace.")
    else:
        lines.append("[OK] Target is inside the workspace.")

    # target-inside-zone check (real pathplan geometry)
    if KEEP_OUT.contains(end_pt):
        lines.append("[RISK: HIGH] Target is INSIDE the keep-out zone -- move would be refused.")
        path = None
    elif is_move_safe(start_pt, end_pt, KEEP_OUT):
        lines.append("[OK] Straight-line path is clear of the keep-out zone.")
        path = [start_pt.as_tuple(), end_pt.as_tuple()]
    else:
        # blocked -> ask pathplan for a detour (the SAME logic the robot uses)
        detour = plan_detour(start_pt, end_pt, KEEP_OUT)
        if detour is None:
            lines.append("[RISK: HIGH] Path crosses the keep-out zone and NO safe detour was found.")
            path = None
        else:
            lines.append(f"[OK] Path crosses the zone; a safe detour was planned ({len(detour)} waypoints):")
            for wp in detour:
                lines.append(f"     -> ({wp.x:.0f}, {wp.y:.0f}, {wp.z:.0f})")
            path = [wp.as_tuple() for wp in detour]

    lines.append("\nThis is only a preview. It does NOT move the robot.")
    lines.append("==============================")
    text = "\n".join(lines)
    print("\n" + text + "\n")
    return {"ok": True, "message": text, "path": path}


# --------------------------------------------------------- live safety monitor
def live_safety_monitor(robot, poll_interval=1.0):
    """Watch the robot's position and log warnings to CSV. Ctrl+C to stop."""
    print("\n=== Live Safety Monitor ===\nWatching robot. Ctrl+C to stop.\n")
    log_file = "dod_safety_monitor_log.csv"
    with open(log_file, "a") as f:
        f.write("timestamp,x,y,z,warning\n")

    try:
        while True:
            p = robot.where()
            warning = ""
            if not inside_workspace({"X": p.x, "Y": p.y, "Z": p.z}):
                warning = "OUTSIDE WORKSPACE"
            elif KEEP_OUT.contains(Point(p.x, p.y, p.z)):
                warning = "INSIDE KEEP-OUT ZONE"

            ts = datetime.now().isoformat(timespec="seconds")
            status = f"WARNING: {warning}" if warning else "OK"
            print(f"[{ts}] {status} X={p.x:.0f} Y={p.y:.0f} Z={p.z:.0f}")
            with open(log_file, "a") as f:
                f.write(f"{ts},{p.x:.0f},{p.y:.0f},{p.z:.0f},{warning}\n")
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        print(f"\nStopped. Log saved to {log_file}")


if __name__ == "__main__":
    # standalone use builds its own robot for testing
    from safe_robot import SafeRobot, FakeClient
    bot = SafeRobot(client=FakeClient(), zone=KEEP_OUT)
    bot.start()
    print("Choose: 1=preflight  2=preview  3=live monitor")
    choice = input("Enter choice: ").strip()
    if choice == "1":
        preflight_check()
    elif choice == "2":
        preview_move(bot, input("Target position? ").strip())
    elif choice == "3":
        live_safety_monitor(bot)
    else:
        print("Invalid choice.")