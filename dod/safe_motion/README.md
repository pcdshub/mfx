# safe_motion

Obstacle-avoiding motion layer for the MFX Drop-on-Demand (DoD) robot.

`SafeRobot` is a subclass of `DoD` that intercepts all motion methods and,
when `safe_mode` is enabled, checks moves against a set of user-defined
exclusion zones before executing them. When `safe_mode` is off, every call
passes through to the parent class with zero overhead.

---

## Contents

```
safe_motion/
├── README.md               # this file
├── __init__.py             # exports SafeRobot
├── safe_robot.py           # SafeRobot class
├── registry.py             # robot INI config parser → position registry
├── obb.py                  # oriented bounding box geometry
├── chebyshev.py            # Chebyshev motion model + path-clear check
├── graph.py                # visibility graph + Dijkstra path planner
└── exclusion_zones.json    # config template — copy and edit for your setup
```

`obb.py`, `chebyshev.py`, and `graph.py` are copied from `DoD_dev/robot_path_planner/`
and are self-contained within this package.

---

## Full workflow

### One-time setup (repeat whenever `exclusion_zones.json` changes)

**Step 1 — Define exclusion zones**

Edit `exclusion_zones.json`:
- `obstacles` — centre, width, height, and angle of each zone in robot frame (µm)
- `clearance_um` — safety buffer around each obstacle boundary
- `small_move_threshold_um` — max displacement allowed for raw jog moves (default 100 µm)
- `waypoint_speeds` — explicit vX/vY/vZ written into every generated waypoint (default 25000/25000/5000 µm/s)
- `task_preconditions` — map of `task_name → required_start_position_name`

**Step 2 — Run the setup script**

The setup script lives at `DoD_dev/setup_safe_motion.py`. It generates
OBB-corner waypoints, writes them as named positions into the robot INI config
file, and stamps a sentinel timestamp (`_last_edit_YYYYMMDDHHMMSS`).

```bash
# Review output before writing
python setup_safe_motion.py \
    --config path/to/exclusion_zones.json \
    --robot-ini path/to/robot_config.ini \
    --dry-run

# Write when satisfied
python setup_safe_motion.py \
    --config path/to/exclusion_zones.json \
    --robot-ini path/to/robot_config.ini
```

The script is idempotent — re-running strips old `_wp_*` entries and rewrites
them. Safe to run after any config change.

**Step 3 — Restart the robot software**

The robot must reload its config file for the new named positions to become
active. Restart the robot software before using `SafeRobot` in safe mode.

---

### Session startup

**Step 4 — Instantiate SafeRobot**

```python
import sys
sys.path.insert(0, '/sdf/home/d/dehe/Ops_supp/MFX_Hutch_Python')
sys.path.insert(0, '/sdf/home/d/dehe/Ops_supp/DoD_dev')

from safe_motion import SafeRobot

dod = SafeRobot(
    robot_config_path='/path/to/robot_config.ini',
    exclusion_zone_config='/path/to/exclusion_zones.json',
)
```

`safe_mode` starts `False` — all moves pass through to `DoD` until explicitly enabled.

**Step 5 — Verify the sentinel (recommended)**

```python
print(dod._sentinel_str)   # e.g. '20260727181742'
```

This should match the timestamp printed by the setup script. A mismatch means
the robot config was modified after the last setup run — re-run the setup
script (Steps 1–3) before enabling safe mode.

**Step 6 — Enable safe mode**

```python
dod.safe_mode = True
```

---

### Normal operation

```python
dod.do_move('Sample_1')       # path-planned, waypoint-by-waypoint, post-move verified
dod.move_x_rel(50)            # endpoint check (≤ threshold), then executes
dod.move_x_rel(5000)          # blocked — exceeds threshold; use do_move() instead
dod.do_task('wash_nozzle')    # precondition check (must be at Home), then executes
dod.safe_mode = False         # passthrough to DoD, zero overhead
```

---

### If a position divergence occurs

`SafeRobot` detects the error, calls `stop_task()`, prints a description, and
locks safe mode. All subsequent safe-mode calls raise `RuntimeError` until
the operator acknowledges:

```python
dod.acknowledge_divergence()   # prints divergence summary, clears lock
dod.safe_mode = True           # re-enable manually after confirming robot state
```

---

## Prerequisites

### 1. Setup script (run once per obstacle layout change)

Before `SafeRobot` can be used in safe mode, the setup script must be run.
It reads the exclusion zone config, generates OBB-corner waypoints with
explicit speeds, writes them as named positions into the robot INI config,
and stamps a sentinel timestamp (`_last_edit_YYYYMMDDHHMMSS`) into the config.

Until the setup script has been run and the robot has reloaded its config,
`do_move` in safe mode will fail because the waypoint names returned by the
path planner will not exist in the robot's position table.

The setup script is at `DoD_dev/setup_safe_motion.py`. See the Full Workflow
section above for usage.

### 2. Python path (development)

During development, `MFX_Hutch_Python` must be on `sys.path` for the `DoD`
import to resolve:

```python
import sys
sys.path.insert(0, '/sdf/home/d/dehe/Ops_supp/MFX_Hutch_Python')
from mfx.dod.safe_motion import SafeRobot
```

This is not needed once the package is deployed into `MFX_Hutch_Python`.

---

## Instantiation

```python
from mfx.dod.safe_motion import SafeRobot

robot = SafeRobot(
    robot_config_path='/path/to/robot_config.ini',
    exclusion_zone_config='/path/to/exclusion_zones.json',
    # optional:
    position_tolerance_um=500.0,   # post-move verify tolerance (default 500 µm)
    # DoD parameters (all optional, defaults match live robot):
    ip='172.21.39.172',
    port=9999,
)
```

At instantiation, `SafeRobot`:
- Parses the robot INI config to build the position registry.
- Loads the exclusion zone config and builds the visibility graph.
- Sets `safe_mode = False` — motion is in passthrough mode until explicitly enabled.

---

## Enabling safe mode

```python
robot.safe_mode = True    # enable
robot.safe_mode = False   # disable (passthrough to DoD)
```

When `safe_mode` is `False`, all calls delegate directly to `DoD` with no
added latency or checks. Toggle it off to regain full unrestricted motion.

---

## Motion method policies in safe mode

| Method | Policy |
|---|---|
| `do_move(name)` | Full path plan via visibility graph; executes waypoints sequentially; verifies position after each step |
| `move_x_rel(dx)` | Blocked if `\|dx\|` > `small_move_threshold`; endpoint check only if within threshold |
| `move_y_rel(dy)` | Same |
| `move_rel(dx, dy, dz)` | Delegates to single-axis overrides above; hutch/robot conversion preserved |
| `move_x_abs(x)` | Computes displacement vs current position; applies same threshold policy |
| `move_y_abs(y)` | Same |
| `move_z_abs(z)` | Z bounds check only (Z is decoupled from XY exclusion zones) |
| `move_z_rel(dz)` | Same |
| `do_task(name)` | Must be on the task precondition whitelist; verifies start position before executing |
| `take_probe(...)` | Same whitelist approach using key `'take_probe'` |

`small_move_threshold` is set in `exclusion_zones.json` (default 100 µm).

---

## Exclusion zone config

Copy `exclusion_zones.json` and edit it for your setup. The key sections are:

### Build plate
```json
"build_plate": { "x_um": 250000, "y_um": 120000, "z_um": 40000 }
```

### Clearance
```json
"clearance_um": 5000
```
Global safety buffer added to every obstacle boundary before path planning.
The robot path stays at least this far from every raw obstacle edge.

### Obstacles
Each obstacle is an oriented rectangle (OBB):

```json
"obstacles": [
  {
    "_name": "human-readable label (ignored by code)",
    "cx_um": 100000,
    "cy_um": 40000,
    "w_um":  40000,
    "h_um":  20000,
    "angle_deg": 0.0
  }
]
```

- `cx_um` / `cy_um` — **centre** of the rectangle in robot frame (µm).
  To specify by corner: `cx = x_min + w/2`, `cy = y_min + h/2`.
- `w_um` / `h_um` — full width and height (not half-widths).
- `angle_deg` — CCW rotation from robot +X axis. Use `0.0` for axis-aligned.

### Small move threshold
```json
"small_move_threshold_um": 100
```

### Task preconditions
```json
"task_preconditions": {
  "wash_nozzle": "Home",
  "take_probe":  "Home"
}
```
Maps task name → required start position name. Tasks not listed here are
blocked in safe mode. The robot must be within `position_tolerance_um` of the
required position before the task is issued.

---

## Coordinate system

All exclusion zone coordinates and the position registry use **robot frame**:

| Robot axis | Hutch axis |
|---|---|
| Robot X | Hutch X |
| Robot Y | Hutch Z |
| Robot Z | −Hutch Y |

The `move_rel(coordinates='hutch')` conversion is handled by `DoD` — `SafeRobot`
does not change this behaviour.

---

## Position divergence and locking

After every `do_move` waypoint, `SafeRobot` queries the robot's actual position
and compares it to the registry entry. If the error on any axis exceeds
`position_tolerance_um`:

1. `stop_task()` is called immediately.
2. `safe_mode_locked` is set to `True`.
3. A description is printed to the console.
4. All subsequent safe-mode calls raise `RuntimeError`.

To resume, the operator must acknowledge explicitly:

```python
robot.acknowledge_divergence()   # prints summary, clears lock
robot.safe_mode = True           # re-enable manually after verifying robot state
```

`acknowledge_divergence()` clears the lock but does **not** automatically
re-enable `safe_mode`.

---

## Sentinel timestamp

The setup script writes a dummy position named `_last_edit_YYYYMMDDHHMMSS`
into the robot INI config at the same time as the waypoints. `SafeRobot`
reads this on startup and stores it as `robot._sentinel_str`.

This is the primary staleness detection mechanism: if the robot config is
edited outside the setup script, the sentinel timestamp will differ from
the one stored in the registry. Mismatch checking and the pre-flight dialog
are planned for a future version (not in v1 scope).

---

## Deployment

When stable, copy the entire `safe_motion/` directory into:

```
MFX_Hutch_Python/mfx/dod/safe_motion/
```

No internal path changes are needed (all imports are relative within the package).
