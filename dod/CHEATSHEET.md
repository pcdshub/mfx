# DoD / CoDI — Operator Cheat Sheet  ·  MFX

> Objects `dod` and `dod.codi` are pre-loaded by hutch-python. No import needed.

---

## Architecture

```
Hardware (robot server at 172.21.39.172:9999)
        ↑ HTTP GET
DropsDriver / HTTPTransceiver       ← vendor layer (do not edit)
        ↑ wrapped by
DoD  (dod_dev_documented.py)        ← motion, nozzle, tasks, timing
  └─ dod.codi ──→ CoDI  (codi.py)  ← 4 SmarAct motors + named presets
```

---

## Status & Connection

| Command | What it does |
|---|---|
| `dod.get_status()` | Print robot state (position, task, humidity, temp) |
| `dod.reconnect()` | Manually reconnect if the robot is unresponsive |

> Connection drops are handled **automatically** (1 retry after 1 s). Call `reconnect()` only if the automatic retry also fails.

---

## DoD Motion

| Command | What it does | Units |
|---|---|---|
| `dod.do_move('position_name')` | Move to a named position | — |
| `dod.move_x_abs(x)` | Move to absolute x | µm |
| `dod.move_y_abs(y)` | Move to absolute y | µm |
| `dod.move_z_abs(z)` | Move to absolute z | µm |

---

## Nozzle Dispensing

| Command | What it does |
|---|---|
| `dod.get_nozzle_status()` | Show nozzle state and parameters |
| `dod.set_nozzle_dispensing(mode='Triggered')` | Dispense on external trigger |
| `dod.set_nozzle_dispensing(mode='Free')` | Continuous dispensing |
| `dod.set_nozzle_dispensing(mode='Off')` | Stop all nozzles |

---

## Tasks

| Command | What it does |
|---|---|
| `dod.get_task_names()` | List available tasks |
| `dod.do_task('task_name')` | Run a task (blocks until done) |
| `dod.stop_task()` | Stop a running task |
| `dod.clear_abort()` | Clear abort state after a stop |

> **Abort mid-run:** `dod.safety_abort = True`  (takes effect within ~0.5 s)

---

## CoDI — Presets

| Command | What it does |
|---|---|
| `dod.codi.get_CoDI_predefined()` | List all named presets |
| `dod.codi.get_CoDI_pos()` | Read current position + matched preset name |
| `dod.codi.set_CoDI_pos('name')` | Move to preset (blocks until done) |
| `dod.codi.set_CoDI_pos('name', wait=False)` | Move without blocking |
| `dod.codi.set_CoDI_current_pos('name')` | Save current position as new preset |
| `dod.codi.set_CoDI_current_z()` | Push current z to **all** presets |

Default presets: **`aspiration`** · **`angled_vert`** · **`angled_hor`**

---

## CoDI — Manual Moves

| Command | What it does | Units |
|---|---|---|
| `dod.codi.move_z_abs(z)` | Absolute z position | mm |
| `dod.codi.move_z_rel(dz)` | Relative z move | mm |
| `dod.codi.move_rot_base_abs(a)` | Absolute base rotation | deg |
| `dod.codi.move_rot_left_abs(a)` | Absolute left-nozzle rotation | deg |
| `dod.codi.move_rot_right_abs(a)` | Absolute right-nozzle rotation | deg |
| `dod.codi.move_rot_base_rel(da)` | Relative base rotation | deg |
| `dod.codi.move_rot_left_rel(da)` | Relative left-nozzle rotation | deg |
| `dod.codi.move_rot_right_rel(da)` | Relative right-nozzle rotation | deg |

---

## Timing  *(all values in nanoseconds)*

| Command | What it does |
|---|---|
| `dod.set_timing_rel_reaction(ns)` | Set drop-to-X-ray reaction delay |
| `dod.set_timing_rel_LED(ns)` | Set LED delay relative to X-ray |
| `dod.set_timing_zero_nozzle(1, ns)` | Set time-zero for nozzle 1 or 2 |
| `dod.set_timing_relative_nozzle(1, ns)` | Adjust nozzle 1 or 2 by offset |
| `dod.set_timing_abs_Xray(ns)` | Update X-ray timing reference |
| `dod.logging_string()` | Generate e-log entry (timing + CoDI state) |

Key attributes (read or set directly):

| Attribute | Meaning | Default |
|---|---|---|
| `dod.timing_delay_reaction` | Drop-to-X-ray delay | 0 ns |
| `dod.timing_delay_LED` | LED delay vs X-ray | 1 000 ns |
| `dod.timing_delay_nozzle_1` | Nozzle 1 delay vs X-ray | from PV |
| `dod.timing_delay_nozzle_2` | Nozzle 2 delay vs X-ray | from PV |

---

## Recaching the Robot JSON

| Need | Command | Persists? |
|---|---|---|
| New positions/tasks added to robot | `dod.reconnect(reload=True)` | No — session only |
| Add new endpoint permanently | `JsonFileHandler.add_endpoint(...)` | Yes — updates `supported.json` |

---

## ⚠️ Known Limitations

- **Forbidden-region checks are not yet active** — `safety_test=True` does not block unsafe moves.
- `do_task(safety_check=True)` will crash — use default `safety_check=False`.
