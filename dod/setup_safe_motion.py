"""
setup_safe_motion.py — One-time setup script for the SafeRobot safe_motion package.

Reads the exclusion zone config, builds the visibility graph, and writes the
resulting waypoint positions (plus a sentinel timestamp) into the robot's INI
config file.  Re-run any time ``exclusion_zones.json`` changes.

Usage
-----
    python setup_safe_motion.py \\
        --config  path/to/exclusion_zones.json \\
        --robot-ini  path/to/robot_config.ini \\
        [--dry-run]

    --dry-run   Print what would be written without modifying the INI file.
                Always review dry-run output before a live write.

What this script does
---------------------
1. Load exclusion_zones.json → build OBBs → instantiate VisibilityGraph.
2. Read graph.nodes — the full set of obstacle-corner + plate-corner waypoints
   that SafeRobot's path planner may route through at runtime.
3. Read the existing robot INI, parse the Positions string into raw records.
4. Strip any previously generated _wp_* and _last_edit_* entries (idempotency).
5. Append new _wp_000, _wp_001, ... records:
     - (x, y) from graph.nodes
     - Z = 0 (safe height; robot is at Z=0 during all XY transit)
     - speeds from the config's ``waypoint_speeds`` key
6. Append a _last_edit_YYYYMMDDHHMMSS sentinel record.
7. Reconstruct the positions string and write back the INI (or print if --dry-run).

Coordinate system
-----------------
All coordinates are in robot frame (µm).
Robot X = Hutch X,  Robot Y = Hutch Z,  Robot Z = −Hutch Y.

Speed note
----------
vX=0 and vY=0 in the robot INI means "use hardware default/maximum", NOT
literal zero speed.  Generated waypoints always use the explicit non-zero
speeds from the config's ``waypoint_speeds`` section.  Do NOT copy speeds
from the ``Home`` position (its vX and vY are 0).

Index note
----------
The robot does not require sequential or ordered indices.  This script
appends new entries starting from max(existing_indices) + 1 to avoid
collisions without disturbing existing entries.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Path setup — allow running from DoD_dev/ without installing
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# safe_motion/__init__.py eagerly imports SafeRobot, which in turn imports
# mfx.dod.dod (the live robot library, not available on development machines).
# The setup script only needs OBB and VisibilityGraph — stub out the robot
# library so the package can load without a live robot environment.
import types as _types


def _stub_module(name: str) -> _types.ModuleType:
    mod = _types.ModuleType(name)
    sys.modules.setdefault(name, mod)
    return sys.modules[name]


for _name in [
    "dod",
    "dod.dod",
    "dod.DropsDriver",
    "dod.JsonFileHandler",
]:
    _stub_module(_name)

# Provide the two names safe_robot.py imports from dod.dod
sys.modules["dod.dod"].DoD = type("DoD", (), {})  # type: ignore[attr-defined]
sys.modules["dod.dod"]._with_reconnect = lambda f: f  # type: ignore[attr-defined]

from safe_motion.obb import OBB
from safe_motion.graph import VisibilityGraph

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MANAGED_PREFIXES = ("_wp_", "_last_edit_")
_RECORD_SEP = r"\0D\0A"  # literal 4-char string inside the INI value
_POSITIONS_RE = re.compile(
    r'(\bPositions\s*=\s*)"(.*?)"',
    re.DOTALL | re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Step 1 — Load config and build graph
# ---------------------------------------------------------------------------


def _load_config(config_path: str) -> Tuple[VisibilityGraph, dict]:
    """Parse exclusion_zones.json, build VisibilityGraph, return (graph, config).

    The caller reads ``graph.nodes`` to get the waypoint coordinates and
    ``config['waypoint_speeds']`` for the speed values to embed.
    """
    with open(config_path, "r") as fh:
        config: dict = json.load(fh)

    plate = config["build_plate"]
    clearance = float(config["clearance_um"])

    # Skip entries that have no geometry keys (e.g. pure comment dicts with only _note).
    obstacles: List[OBB] = [
        OBB(
            cx=float(obs["cx_um"]),
            cy=float(obs["cy_um"]),
            w=float(obs["w_um"]),
            h=float(obs["h_um"]),
            angle=float(obs["angle_deg"]),
        )
        for obs in config.get("obstacles", [])
        if "cx_um" in obs
    ]

    graph = VisibilityGraph(
        obstacles=obstacles,
        clearance=clearance,
        plate_x=float(plate["x_um"]),
        plate_y=float(plate["y_um"]),
    )

    return graph, config


# ---------------------------------------------------------------------------
# Step 2 — Read and parse existing INI
# ---------------------------------------------------------------------------


def _read_ini(robot_ini_path: str) -> Tuple[List[str], str]:
    """Read the robot INI file and return (records, full_text).

    ``records`` is a list of raw record strings (tab-separated fields, no
    separator).  ``full_text`` is the complete file content for reconstruction.
    """
    with open(
        robot_ini_path, "r", encoding="utf-8", errors="replace", newline=""
    ) as fh:
        full_text = fh.read()

    match = _POSITIONS_RE.search(full_text)
    if not match:
        raise ValueError(
            f"Could not find 'Positions = \"...\"' in robot INI file: {robot_ini_path}"
        )

    raw_value = match.group(2)
    records = [r for r in raw_value.split(_RECORD_SEP) if r.strip()]
    return records, full_text


# ---------------------------------------------------------------------------
# Step 3 — Strip managed entries (idempotency)
# ---------------------------------------------------------------------------


def _strip_managed_entries(records: List[str]) -> List[str]:
    """Remove all _wp_* and _last_edit_* records from *records*.

    Returns a new list; does not mutate the input.
    """
    kept = []
    for rec in records:
        fields = rec.split("\t")
        if len(fields) < 2:
            kept.append(rec)
            continue
        name = fields[1].strip()
        if any(name.startswith(pfx) for pfx in _MANAGED_PREFIXES):
            continue
        kept.append(rec)
    return kept


# ---------------------------------------------------------------------------
# Step 4 — Determine next free index
# ---------------------------------------------------------------------------


def _max_index(records: List[str]) -> int:
    """Return the highest integer index found in *records*, or -1 if none."""
    high = -1
    for rec in records:
        fields = rec.split("\t")
        if not fields:
            continue
        try:
            idx = int(fields[0].strip())
            if idx > high:
                high = idx
        except ValueError:
            continue
    return high


# ---------------------------------------------------------------------------
# Step 5 — Build _wp_* records
# ---------------------------------------------------------------------------


def _make_waypoint_records(
    nodes: List[Tuple[float, float]],
    speeds: dict,
    start_index: int,
) -> List[str]:
    """Build one INI record string per graph node.

    Parameters
    ----------
    nodes:
        List of (x, y) coordinate pairs from VisibilityGraph.nodes (µm).
    speeds:
        Dict with keys ``vx_um_per_s``, ``vy_um_per_s``, ``vz_um_per_s``.
    start_index:
        Integer index for the first new record.

    Returns
    -------
    List of raw record strings (tab-separated, two trailing tabs, no separator).
    """
    vx = int(speeds.get("vx_um_per_s", 25000))
    vy = int(speeds.get("vy_um_per_s", 25000))
    vz = int(speeds.get("vz_um_per_s", 5000))

    records = []
    for i, (x, y) in enumerate(nodes):
        name = f"_wp_{i:03d}"
        idx = start_index + i
        x_int = int(round(x))
        y_int = int(round(y))
        rec = f"{idx}\t{name}\t{x_int}\t{y_int}\t0\t{vx}\t{vy}\t{vz}\t\t"
        records.append(rec)
    return records


# ---------------------------------------------------------------------------
# Step 6 — Build sentinel record
# ---------------------------------------------------------------------------


def _make_sentinel_record(index: int) -> Tuple[str, str]:
    """Build the _last_edit_YYYYMMDDHHMMSS sentinel record.

    Returns (record_str, timestamp_str).
    """
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    name = f"_last_edit_{ts}"
    rec = f"{index}\t{name}\t0\t0\t0\t0\t0\t0\t\t"
    return rec, ts


# ---------------------------------------------------------------------------
# Step 7 — Pack records and reconstruct INI
# ---------------------------------------------------------------------------


def _pack_positions(records: List[str]) -> str:
    """Join records into a packed positions string with trailing separator."""
    return _RECORD_SEP.join(records) + _RECORD_SEP


def _reconstruct_ini(full_text: str, packed_positions: str) -> str:
    """Replace the Positions value in *full_text* with *packed_positions*."""

    def replacer(m: re.Match) -> str:
        return f'{m.group(1)}"{packed_positions}"'

    new_text, n = _POSITIONS_RE.subn(replacer, full_text)
    if n != 1:
        raise RuntimeError(
            f"Expected exactly 1 'Positions = \"...\"' match; found {n}."
        )
    return new_text


# ---------------------------------------------------------------------------
# Step 8 — Build positions JSON (sidecar)
# ---------------------------------------------------------------------------


def _build_positions_json(all_records: List[str], sentinel_ts: str) -> dict:
    """Parse *all_records* into a JSON-serialisable positions dict.

    Returns a dict with two top-level keys:

    ``positions``
        ``{name: {X, Y, Z, vX, vY, vZ}}`` for every non-sentinel record.
    ``sentinel``
        The sentinel timestamp string (e.g. ``'20260727181742'``).

    This is the format read by :func:`registry.load_registry_from_json`.
    """
    positions: dict = {}
    for rec in all_records:
        fields = rec.split("\t")
        if len(fields) < 8:
            continue
        name = fields[1].strip()
        if not name or name.startswith("_last_edit_"):
            continue
        try:
            positions[name] = {
                "X": int(fields[2]),
                "Y": int(fields[3]),
                "Z": int(fields[4]),
                "vX": int(fields[5]),
                "vY": int(fields[6]),
                "vZ": int(fields[7]),
            }
        except ValueError:
            continue
    return {"positions": positions, "sentinel": sentinel_ts}


def _json_path_for_ini(ini_path: str) -> str:
    """Return the sidecar JSON path for a given INI path.

    Replaces a ``.ini`` extension with ``.json``; appends ``.json`` otherwise.
    """
    p = Path(ini_path)
    if p.suffix.lower() == ".ini":
        return str(p.with_suffix(".json"))
    return str(p) + ".json"


# ---------------------------------------------------------------------------
# Step 9 — Summary
# ---------------------------------------------------------------------------


def _print_summary(
    kept_records: List[str],
    wp_records: List[str],
    sentinel_ts: str,
    dry_run: bool,
    json_path: Optional[str] = None,
) -> None:
    mode = "[DRY RUN] " if dry_run else ""
    print(f"\n{mode}setup_safe_motion summary")
    print("=" * 50)
    print(f"  Existing positions preserved : {len(kept_records)}")
    print(f"  Waypoint positions written   : {len(wp_records)}")
    for rec in wp_records:
        fields = rec.split("\t")
        name = fields[1] if len(fields) > 1 else "?"
        x = fields[2] if len(fields) > 2 else "?"
        y = fields[3] if len(fields) > 3 else "?"
        print(f"    {name:12s}  X={x}  Y={y}  Z=0")
    print(f"  Sentinel timestamp           : {sentinel_ts}")
    if dry_run:
        print("\n  *** DRY RUN — robot INI file was NOT modified. ***")
        print("  *** DRY RUN — positions JSON was NOT written.   ***")
        print("  Re-run without --dry-run to write changes.")
    else:
        print(f"  Positions JSON written       : {json_path}")
        print(
            "\n  *** IMPORTANT: Reload the robot configuration (restart robot software) ***"
        )
        print(
            "  *** before using SafeRobot.  New positions are not active until       ***"
        )
        print(
            "  *** the robot software re-reads its config file.                      ***"
        )
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write safe_motion waypoints into the robot INI config file."
    )
    parser.add_argument(
        "--config",
        required=True,
        metavar="PATH",
        help="Path to exclusion_zones.json",
    )
    parser.add_argument(
        "--robot-ini",
        required=True,
        metavar="PATH",
        help="Path to the robot Windows INI config file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without modifying the INI file",
    )
    args = parser.parse_args()

    # 1. Load config and build graph
    print(f"Loading config: {args.config}")
    graph, config = _load_config(args.config)
    print(graph.summary())

    waypoint_speeds = config.get(
        "waypoint_speeds",
        {"vx_um_per_s": 25000, "vy_um_per_s": 25000, "vz_um_per_s": 5000},
    )

    # 2. Read existing INI
    print(f"Reading robot INI: {args.robot_ini}")
    records, full_text = _read_ini(args.robot_ini)
    print(f"  Found {len(records)} existing position records.")

    # 3. Strip managed entries
    kept = _strip_managed_entries(records)
    stripped_count = len(records) - len(kept)
    if stripped_count:
        print(
            f"  Stripped {stripped_count} previously generated _wp_/_last_edit_ entries."
        )

    # 4. Determine next free index
    next_idx = _max_index(kept) + 1
    print(f"  Next available index: {next_idx}")

    # 5. Build waypoint records
    wp_records = _make_waypoint_records(graph.nodes, waypoint_speeds, next_idx)

    # 6. Build sentinel
    sentinel_record, sentinel_ts = _make_sentinel_record(next_idx + len(wp_records))

    # 7. Pack and reconstruct
    all_records = kept + wp_records + [sentinel_record]
    packed = _pack_positions(all_records)
    new_ini_text = _reconstruct_ini(full_text, packed)

    # 8. Build sidecar JSON
    json_path = _json_path_for_ini(args.robot_ini)
    positions_json = _build_positions_json(all_records, sentinel_ts)

    # 9. Summary
    _print_summary(
        kept, wp_records, sentinel_ts, dry_run=args.dry_run, json_path=json_path
    )

    # 10. Write (or print)
    if args.dry_run:
        print("--- Reconstructed Positions line (dry run) ---")
        # Find and print just the Positions line for review
        for line in new_ini_text.splitlines():
            if line.strip().lower().startswith("positions"):
                print(line)
                break
        print("--- End dry run output ---")
    else:
        out_path = args.robot_ini
        with open(out_path, "w", encoding="utf-8", newline="\r\n") as fh:
            fh.write(new_ini_text)
        print(f"Wrote updated INI to: {out_path}")

        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(positions_json, fh, indent=2)
        print(f"Wrote positions JSON to: {json_path}")


if __name__ == "__main__":
    main()
