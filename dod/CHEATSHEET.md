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
  ├─ dod.codi ──→ CoDI  (codi.py)  ← 4 SmarAct motors + named presets
  └─ SafeRobot  (safe_motion/)     ← obstacle-avoiding subclass of DoD
```

---

## Status & Connection

| Command | What it does |
|---|---|
| `dod.get_status()` | Print robot state (position, task, humidity, temp) |
| `dod.get_position_names()` | List all named positions stored on the robot |
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
| `dod.move_x_rel(dx)` | Relative x move | µm |
| `dod.move_y_rel(dy)` | Relative y move | µm |
| `dod.move_z_rel(dz)` | Relative z move | µm |
| `dod.move_rel(dx, dy, dz)` | Relative move in all axes (robot frame) | µm |
| `dod.move_rel(dx, dy, dz, coordinates='hutch')` | Relative move in hutch frame | µm |
| `dod.get_drive_range()` | Return max allowed coordinate per axis | µm |

> **Coordinate systems:** `hutch(x,y,z) = robot(x,−z,y)`. Absolute and single-axis relative methods use the robot frame. Use `coordinates='hutch'` in `move_rel` to work in hutch coordinates.

---

## Nozzle Dispensing

| Command | What it does |
|---|---|
| `dod.get_nozzle_status()` | Show raw nozzle state dict |
| `dod.get_nozzle_parameters()` | Show per-nozzle volt / pulse / freq / volume as a dict |
| `dod.set_nozzle_dispensing(mode='Trigger')` | Dispense on external trigger |
| `dod.set_nozzle_dispensing(mode='Free')` | Continuous dispensing |
| `dod.set_nozzle_dispensing(mode='Off')` | Stop all active nozzles |

## Nozzle Parameters

| Command | What it does | Units |
|---|---|---|
| `dod.get_pulse_names()` | List available sciPULSE pulse shape names | — |
| `dod.set_nozzle_voltage(nozzle, volt)` | Set drive voltage for one nozzle | V |
| `dod.set_nozzle_pulse(nozzle, pulse)` | Set pulse shape / duration for one nozzle | name or string |
| `dod.set_nozzle_freq(nozzle, freq)` | Set dispensing frequency for one nozzle | Hz |
| `dod.set_nozzle_active([1, 2, 3])` | Set which nozzles are armed | — |
| `dod.set_nozzle_selected(nozzle)` | Select which armed nozzle fires on trigger | — |
| `dod.take_probe(channel, well, volume)` | Aspirate from a well plate (e.g. `'A1'`, ≤ 250 µL); also selects `channel` | µL |

> **Pulse:** ch 1–2 use waveform names (e.g. `'sciPULSE_LV01'`); ch 3+ use numeric strings (e.g. `'48'`). Use `dod.get_pulse_names()` to list valid names.
> Each setter reads current state first — only the named parameter changes.
> `set_nozzle_selected` raises `ValueError` if the nozzle is not armed.
> **Waveform load time:** `set_nozzle_pulse` on ch 1 or 2 blocks for 5 s after sending — the robot needs this time to load the waveform.
> **`take_probe` requires `ProbeUptake` task on robot.** Raises `RuntimeError` if absent. Default timeout = `max(30, volume)` s.

## Environmental Controls

| Command | What it does | Units / Values |
|---|---|---|
| `dod.set_humidity(value)` | Set target relative humidity | %rH, integer, 0–100 |
| `dod.set_cooling_temp(temp)` | Set cooling device temperature | °C (float) or `'dewpoint'` |

---

## LED Strobe

| Command | What it does | Units |
|---|---|---|
| `dod.set_led(duration, delay)` | Set strobe pulse width and delay (current nozzle) | µs |
| `dod.set_led_per_nozzle(nozzle, duration, delay)` | Select nozzle then set its strobe params | µs |

> **Ranges:** `duration` 1–65 000 µs; `delay` 0–6 500 µs. `ValueError` if out of range.
> No read-back — track values in calling code if needed.

---

## Tasks

| Command | What it does |
|---|---|
| `dod.get_task_names()` | List available tasks |
| `dod.do_task('task_name')` | Run a task (blocks until done; surfaces dialogs) |
| `dod.do_task('task_name', handle_dialog='auto_ok')` | Run a task; auto-close single-button dialogs |
| `dod.do_task('task_name', handle_dialog='auto_1')` | Run a task; auto-close all dialogs with Button1 |
| `dod.stop_task()` | Stop a running task |
| `dod.clear_abort()` | Clear abort state after a stop |

> **Abort mid-run:** `dod.safety_abort = True`  (takes effect within ~0.5 s)

---

## Error Recovery

| Command | What it does |
|---|---|
| `dod.get_status()['Status']` | Check current state: `'Idle'`, `'Busy'`, `'Dialog'`, `'Error'` |
| `dod.close_current_dialog(1)` | Print dialog then close with Button1 (`'OK'`) — **one-liner** |
| `dod.close_current_dialog(2)` | Print dialog then close with Button2 (`'Abort'`) — **one-liner** |
| `dod.reset_error()` | Clear `'Error'` state after all dialogs are dismissed |

**Workflow:**
```python
dod.close_current_dialog(1)   # prints message + closes with OK
# repeat if more dialogs remain
dod.reset_error()             # only if Status still 'Error' afterwards
```

> Multiple dialogs stack LIFO — `get_status()` shows the **most recent** one first.

---

## CoDI — Presets

| Command | What it does |
|---|---|
| `dod.codi.get_presets()` | List all named presets |
| `dod.codi.get_pos()` | Read current position + matched preset name |
| `dod.codi.move_to_preset('name')` | Move to preset (blocks until done, 30 s timeout) |
| `dod.codi.move_to_preset('name', wait=False)` | Move without blocking |
| `dod.codi.add_preset('name', base, left, right, z)` | Add or overwrite a named preset |
| `dod.codi.save_current_pos('name')` | Save current motor positions as a new preset |
| `dod.codi.update_z_all_presets()` | Push current z to all presets |
| `dod.codi.reload_presets()` | Reload presets from hutch-python motor objects |
| `dod.codi.remove_preset('name')` | Remove a preset from the local dictionary |

Default presets: **`aspiration`** · **`angled_vert`** · **`angled_hor`**

> **Deprecated aliases:** `get_CoDI_predefined`, `get_CoDI_pos`, `set_CoDI_pos`,
> `set_CoDI_current_pos`, `set_CoDI_current_z` still work but emit
> `DeprecationWarning`. Use the names above.

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

## CoDI Alignment (`codi_align`)

```python
from dod.codi import codi_align
codi_align(codi)              # P and Z modes only
codi_align(codi, dod=dod)     # all 4 modes
```

| Mode | Key | Step | What it controls |
|---|---|---|---|
| **P** Position | `p` | 0 | All 4 axes; `1`–`4` select axis |
| **T** Timing | `t` | 1 | EVR timing-zero per nozzle; `1`/`2` toggle |
| **Z** Overlap | `z` | 2 | `trans_z` only; `[`/`]`/`m` mark range + jump to midpoint |
| **R** Reaction | `r` | 3 | Reaction time; right = more reaction time |

| Key | Action |
|---|---|
| Left / Right | Move (negative / positive) |
| Up / Down or `+` / `-` | Step size ×0.5 / ×2 |
| `[` / `]` / `m` | Mark range start / end / jump to midpoint (T and Z modes) |
| `=` | Enter value directly in µs (T and R modes) |
| `s` | Save current CoDI position as preset |
| `h` | Key map |
| `?` | Alignment procedure walkthrough (Steps 0–3) |
| `q` | Quit; prompts for e-log post |

Default step sizes: rotation **0.05°** · trans_z **0.010 mm** · timing **10 µs**

---

## Timing  *(display in µs; internal storage in ns)*

| Command | What it does |
|---|---|
| `dod.set_reaction_timing_rel(ns)` | Set drop-to-X-ray reaction delay |
| `dod.set_led_timing_rel(ns)` | Set LED delay relative to X-ray |
| `dod.set_nozzle_timing_zero(1, ns)` | Set time-zero reference for nozzle 1 or 2 |
| `dod.set_nozzle_timing_rel(1, ns)` | Adjust nozzle 1 or 2 by relative offset |
| `dod.set_nozzle_timing_abs(1, ns)` | Set nozzle 1 or 2 to absolute value |
| `dod.set_xray_timing_ref(ns)` | Update X-ray timing reference |
| `dod.print_timing()` | Print all timing values to console (µs) |
| `dod.logging_string()` | Return e-log string (timing + CoDI state) |
| `dod.logging_string(post_elog=True)` | Return and post to MFX e-log |

Key attributes (read or set directly):

| Attribute | Meaning | Default |
|---|---|---|
| `dod.timing_delay_reaction` | Drop-to-X-ray delay | 0 ns |
| `dod.timing_delay_LED` | LED delay vs X-ray | 1 000 ns |
| `dod.timing_delay_nozzle_1` | Nozzle 1 delay vs X-ray | from PV |
| `dod.timing_delay_nozzle_2` | Nozzle 2 delay vs X-ray | from PV |

---

## SafeRobot (Safe Motion)

```python
from dod.safe_motion import SafeRobot
dod = SafeRobot(
    robot_config_path='/path/to/robot_config.ini',
    exclusion_zone_config='/path/to/exclusion_zones.json',
)
print(dod._sentinel_str)   # verify config is current
dod.safe_mode = True        # enable obstacle avoidance
```

| Command | What it does |
|---|---|
| `dod.safe_mode = True/False` | Enable / disable obstacle-avoiding motion |
| `dod.print_status()` | Show safe mode state, zones, positions, and preconditions |
| `dod.plot_path('name')` | Preview planned path without moving |
| `dod.do_move('name', plot=True)` | Preview then execute |
| `dod.acknowledge_divergence()` | Clear position-divergence lock after verifying robot state |

> When `safe_mode = False` all calls pass through to `DoD` with zero overhead.
> `do_move` in safe mode executes waypoint-by-waypoint and verifies position after each step.
> Raw jogs (`move_x/y_rel`) are blocked above `small_move_threshold` (default 100 µm) — use `do_move` for larger moves.

---

## Recaching the Robot JSON

| Need | Command | Persists? |
|---|---|---|
| New positions/tasks added to robot | `dod.reconnect(reload=True)` | No — session only |
| Add new endpoint permanently | `JsonFileHandler.add_endpoint(...)` | Yes — updates `supported.json` |

---

## ⚠️ Known Limitations

- **Forbidden-region checks in `DoD` base class are not yet active** — `safety_test=True` does not block unsafe moves. Use `SafeRobot` with `safe_mode=True` for real obstacle avoidance.
- `HTTPTransceiver.send()` prints the endpoint to stdout on every HTTP call — this cannot be suppressed without editing the unowned vendor file.
