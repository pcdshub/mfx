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
| `dod.move_x_rel(dx)` | Relative x move | µm |
| `dod.move_y_rel(dy)` | Relative y move | µm |
| `dod.move_z_rel(dz)` | Relative z move | µm |
| `dod.move_rel(dx, dy, dz)` | Relative move in all axes (robot frame) | µm |
| `dod.move_rel(dx, dy, dz, coordinates='hutch')` | Relative move in hutch frame | µm |

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
| `dod.set_nozzle_voltage(nozzle, volt)` | Set drive voltage for one nozzle | V |
| `dod.set_nozzle_pulse(nozzle, pulse)` | Set pulse shape / duration for one nozzle | name or string |
| `dod.set_nozzle_freq(nozzle, freq)` | Set dispensing frequency for one nozzle | Hz |
| `dod.set_nozzle_active([1, 2, 3])` | Set which nozzles are armed | — |
| `dod.set_nozzle_selected(nozzle)` | Select which armed nozzle fires on trigger | — |
| `dod.take_probe(channel, well, volume)` | Aspirate from a well plate (e.g. `'A1'`, ≤ 250 µL); also selects `channel` | µL |

> **Pulse:** ch 1–2 use waveform names (e.g. `'sciPULSE_LV01'`); ch 3+ use numeric strings (e.g. `'48'`).
> Each setter reads current state first — only the named parameter changes.
> `set_nozzle_selected` raises `ValueError` if the nozzle is not armed.
> **Waveform load time:** `set_nozzle_pulse` on ch 1 or 2 blocks for 5 s after sending the command — the robot needs this time to load the named waveform.
> **`take_probe` requires `ProbeUptake` task on robot.** Raises `RuntimeError` if absent (`check_task=True` default). Blocks until done; default timeout = `max(30, volume)` s. Pass `timeout=` to override.

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

> **`handle_dialog` modes:** `'raise'` (default) — print dialog and return paused dict; `'auto_ok'` — auto-close single-button only; `'auto_1'` / `'auto_2'` — auto-close all with that button.

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
- `do_task(safety_check=True)` — safety check not yet implemented; use default `safety_check=False`.
