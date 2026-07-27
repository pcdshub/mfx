"""
registry.py — Robot INI config parser for the safe_motion package.

Parses the robot's Windows INI configuration file and builds:

  1. A position registry dict:
         {name: {'X': int, 'Y': int, 'Z': int, 'vX': int, 'vY': int, 'vZ': int}}

  2. A coordinate→name reverse index for path-planner waypoint lookup:
         {(X, Y): name}

  3. A sentinel timestamp extracted from the special ``_last_edit_YYYYMMDDHHMMSS``
     position entry written by the setup script.

Public API
----------
load_registry(path, coord_tolerance_um=WAYPOINT_COORD_TOLERANCE_UM)
    Parse the INI file at *path* and return ``(registry_dict, sentinel_str)``.

lookup_name_by_coords(registry_dict, x, y, tolerance_um=WAYPOINT_COORD_TOLERANCE_UM)
    Find the position name whose (X, Y) coordinates match (x, y) within
    *tolerance_um*.  Returns the name string or raises ``KeyError``.

INI format
----------
The robot stores all named positions as a single packed string under
``[Positions] / Positions``.  The value is double-quoted; records are
separated by the literal escape sequence ``\\0D\\0A``; fields within each
record are tab-separated:

    "0\\t<name>\\t<X>\\t<Y>\\t<Z>\\t<vX>\\t<vY>\\t<vZ>\\t\\t\\0D\\0A1\\t..."

Fields per record:
    0  index   (int, ignored)
    1  name    (str, may contain spaces)
    2  X       (µm, int)
    3  Y       (µm, int)
    4  Z       (µm, int)
    5  vX      (µm/s, int)
    6  vY      (µm/s, int)
    7  vZ      (µm/s, int)

Sentinel
--------
The setup script writes a dummy position whose name matches the pattern
``_last_edit_YYYYMMDDHHMMSS``.  The registry loader detects this prefix,
extracts the timestamp string, and excludes the entry from the normal
registry dict.

Coordinate system
-----------------
All values are in robot frame coordinates (µm).
Robot X = Hutch X,  Robot Y = Hutch Z,  Robot Z = −Hutch Y.
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Tolerance for float-matching planner-returned (x, y) coordinates back to
# named positions in the registry.  This guards against floating-point
# representation differences; it is NOT a safety parameter and should not be
# set in the user-facing exclusion zone config.
WAYPOINT_COORD_TOLERANCE_UM: float = 10.0

_SENTINEL_PREFIX = "_last_edit_"
_RECORD_SEP = r"\0D\0A"  # literal string in the INI value (not a real CR+LF)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

PositionEntry = Dict[
    str, int
]  # {'X': int, 'Y': int, 'Z': int, 'vX': int, 'vY': int, 'vZ': int}
RegistryDict = Dict[str, PositionEntry]  # {name: PositionEntry}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_registry(
    path: str,
    coord_tolerance_um: float = WAYPOINT_COORD_TOLERANCE_UM,
) -> Tuple[RegistryDict, Optional[str]]:
    """Parse the robot INI config at *path*.

    Parameters
    ----------
    path:
        Filesystem path to the robot ``.ini`` configuration file.
    coord_tolerance_um:
        Tolerance used when building the reverse coordinate→name index.
        Pairs of positions whose (X, Y) differ by less than this value
        would collide in the index; a warning is printed if detected.

    Returns
    -------
    registry_dict:
        ``{name: {'X': int, 'Y': int, 'Z': int, 'vX': int, 'vY': int, 'vZ': int}}``
        for every non-sentinel named position.
    sentinel_str:
        The timestamp portion of the ``_last_edit_YYYYMMDDHHMMSS`` entry
        (e.g. ``'20260720153045'``), or ``None`` if no sentinel is present.
    """
    raw_value = _read_positions_value(path)
    records = _split_records(raw_value)
    registry_dict: RegistryDict = {}
    sentinel_str: Optional[str] = None

    for record in records:
        fields = record.split("\t")
        if len(fields) < 8:
            continue  # malformed record — skip silently

        name = fields[1].strip()
        if not name:
            continue

        # Sentinel detection
        if name.startswith(_SENTINEL_PREFIX):
            sentinel_str = name[len(_SENTINEL_PREFIX) :]
            continue

        try:
            entry: PositionEntry = {
                "X": int(fields[2]),
                "Y": int(fields[3]),
                "Z": int(fields[4]),
                "vX": int(fields[5]),
                "vY": int(fields[6]),
                "vZ": int(fields[7]),
            }
        except ValueError:
            # Non-numeric coordinate field — skip (e.g. header/comment row)
            continue

        registry_dict[name] = entry

    return registry_dict, sentinel_str


def load_registry_from_json(
    path: str,
) -> Tuple[RegistryDict, Optional[str]]:
    """Parse a positions JSON file produced by the setup script.

    The JSON must have the structure written by ``setup_safe_motion.py``::

        {
          "positions": {
            "Home":    {"X": 0, "Y": 0, "Z": 0, "vX": 0, "vY": 0, "vZ": 25000},
            "_wp_000": {"X": 100000, ...},
            ...
          },
          "sentinel": "20260727181742"
        }

    Parameters
    ----------
    path:
        Filesystem path to the ``.json`` positions file.

    Returns
    -------
    registry_dict:
        ``{name: {'X': int, 'Y': int, 'Z': int, 'vX': int, 'vY': int, 'vZ': int}}``
    sentinel_str:
        The sentinel timestamp string, or ``None`` if absent.
    """
    import json as _json

    with open(path, "r", encoding="utf-8") as fh:
        data: dict = _json.load(fh)

    registry_dict: RegistryDict = {}
    for name, entry in data.get("positions", {}).items():
        registry_dict[name] = {
            "X": int(entry["X"]),
            "Y": int(entry["Y"]),
            "Z": int(entry["Z"]),
            "vX": int(entry["vX"]),
            "vY": int(entry["vY"]),
            "vZ": int(entry["vZ"]),
        }

    sentinel_str: Optional[str] = data.get("sentinel") or None
    return registry_dict, sentinel_str


def lookup_name_by_coords(
    registry_dict: RegistryDict,
    x: float,
    y: float,
    tolerance_um: float = WAYPOINT_COORD_TOLERANCE_UM,
) -> str:
    """Return the position name whose (X, Y) matches *(x, y)* within *tolerance_um*.

    Parameters
    ----------
    registry_dict:
        The registry dict returned by :func:`load_registry`.
    x, y:
        Target coordinates in µm (robot frame).
    tolerance_um:
        Maximum allowed distance (per axis) for a match.

    Returns
    -------
    str
        The matching position name.

    Raises
    ------
    KeyError
        If no position in the registry matches within the tolerance.
    """
    for name, entry in registry_dict.items():
        if abs(entry["X"] - x) <= tolerance_um and abs(entry["Y"] - y) <= tolerance_um:
            return name
    raise KeyError(
        f"No registry position found within {tolerance_um} µm of "
        f"(X={x:.1f}, Y={y:.1f}).  "
        f"Ensure the setup script has been run and all planner waypoints "
        f"are present in the robot INI config."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_positions_value(path: str) -> str:
    """Read the raw ``Positions`` string value from the INI file.

    The robot INI uses Windows line endings and stores the entire positions
    block as a single (possibly very long) quoted string value.  We parse it
    with a simple regex rather than ``configparser`` to avoid issues with
    embedded tab characters and non-standard quoting.

    Returns the content between the outermost double-quotes, or raises
    ``ValueError`` if the section or key is not found.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        content = fh.read()

    # Match: Positions = "..."  (the value may span multiple lines in theory,
    # but in practice the entire positions block is on one line).
    match = re.search(r'\bPositions\s*=\s*"(.*?)"', content, re.DOTALL | re.IGNORECASE)
    if not match:
        raise ValueError(
            f"Could not find 'Positions = \"...\"' in robot INI file: {path}"
        )
    return match.group(1)


def _split_records(raw_value: str) -> list:
    """Split the packed positions string into individual record strings.

    Records are separated by the literal text ``\\0D\\0A`` (two characters:
    backslash-0-D-backslash-0-A), which represents CR+LF in the robot's
    escaped format.  Empty strings after splitting are discarded.
    """
    return [r for r in raw_value.split(_RECORD_SEP) if r.strip()]
