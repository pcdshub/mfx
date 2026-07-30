# DoD Robot Interface — MFX

This repository contains the Python interface for controlling the Drop-on-Demand (DoD)
robot and the Colliding Droplet Injector (CoDI) at the MFX beamline. The interface
communicates with the robot server over HTTP and exposes two classes — `DoD` and `CoDI`
— for use in hutch-python sessions.

---

## Table of Contents

- [For Operators](#for-operators)
  - [Session Startup](#session-startup)
  - [DoD Commands](#dod-commands)
  - [Error Recovery](#error-recovery)
  - [CoDI Commands](#codi-commands)
  - [CoDI Alignment Wrapper](#codi-alignment-wrapper)
  - [Timing](#timing)
  - [Dry-run Mode](#dry-run-mode-off-hutch-development)
  - [Safety](#safety)
  - [Connection Issues](#connection-issues)
- [For Developers](#for-developers)
  - [Architecture](#architecture)
  - [File Inventory](#file-inventory)
  - [hutch-python Loading](#hutch-python-loading)
  - [\_with\_reconnect Decorator](#_with_reconnect-decorator)
  - [Logging Redirect](#logging-redirect)
  - [Preset Access](#preset-access)
  - [Relative Motion and PositionReal Format](#relative-motion-and-positionreal-format)
  - [Nozzle Parameter Methods](#nozzle-parameter-methods)
  - [LED Strobe Methods](#led-strobe-methods)
  - [dod.py vs dod\_dev\_documented.py](#dodpy-vs-dod_dev_documentedpy)
  - [Dry-run Architecture](#dry-run-architecture-developer-reference)
- [Known Issues](#known-issues)

---

## For Operators

### Session Startup

In a normal hutch-python session the robot objects are **pre-loaded automatically**.
No imports or instantiation are needed:

```python
dod       # DoD robot interface  (already available)
dod.codi  # CoDI interface       (available as part of dod)
```

---

### DoD Commands

#### Status & Connection

| Command | Description | Returns |
|---|---|---|
| `dod.get_status()` | Current robot state | `dict` with keys `Position`, `RunningTask`, `Humidity`, `Temperature`, `BathTemp` |
| `dod.get_status(verbose=True)` | Full server response | `ServerResponse` object |
| `dod.get_position_names()` | List all named positions stored on the robot | list of strings |
| `dod.reconnect()` | Manually reconnect after a connection loss | — |

#### Motion

| Command | Description | Units |
|---|---|---|
| `dod.do_move('position_name')` | Move to a named position | — |
| `dod.move_x_abs(x)` | Move to absolute x position | µm |
| `dod.move_y_abs(y)` | Move to absolute y position | µm |
| `dod.move_z_abs(z)` | Move to absolute z position | µm |
| `dod.move_x_rel(dx)` | Move by relative offset along x | µm |
| `dod.move_y_rel(dy)` | Move by relative offset along y | µm |
| `dod.move_z_rel(dz)` | Move by relative offset along z | µm |
| `dod.move_rel(dx, dy, dz)` | Move by relative offsets in all three axes (robot frame by default) | µm |
| `dod.move_rel(dx, dy, dz, coordinates='hutch')` | Same, with deltas supplied in the hutch coordinate frame | µm |
| `dod.get_drive_range()` | Return the maximum allowed coordinate per axis | µm |

> **Coordinate systems:** Robot and hutch frames are related by
> `hutch(x, y, z) = robot(x, −z, y)`. All absolute move methods and
> `move_*_rel` operate in the robot frame. Pass `coordinates='hutch'` to
> `move_rel` to work in hutch coordinates.

#### Nozzle Dispensing

| Command | Description |
|---|---|
| `dod.get_nozzle_status()` | Return raw nozzle status dict |
| `dod.get_nozzle_parameters()` | Return per-nozzle parameters as a dict keyed by channel number |
| `dod.set_nozzle_dispensing(mode='Trigger')` | Enable triggered dispensing |
| `dod.set_nozzle_dispensing(mode='Free')` | Enable continuous dispensing |
| `dod.set_nozzle_dispensing(mode='Off')` | Stop dispensing on all active nozzles |

#### Nozzle Parameters

| Command | Description | Units |
|---|---|---|
| `dod.get_pulse_names()` | List available sciPULSE pulse shape names | — |
| `dod.set_nozzle_voltage(nozzle, volt)` | Set drive voltage for a specific nozzle | V |
| `dod.set_nozzle_pulse(nozzle, pulse)` | Set pulse shape for a specific nozzle | name or string |
| `dod.set_nozzle_freq(nozzle, freq)` | Set dispensing frequency for a specific nozzle | Hz |
| `dod.set_nozzle_active([1, 2, 3])` | Set which nozzles are armed (activated) | — |
| `dod.set_nozzle_selected(nozzle)` | Select the nozzle that fires on trigger / task execution | — |
| `dod.take_probe(channel, well, volume)` | Aspirate from a well plate using the specified nozzle | µL |
| `dod.take_probe(channel, well, volume, timeout=45)` | Same, with a custom wait timeout | µL / s |

> **Pulse shape:** Channels 1 and 2 use named waveforms (e.g. `'sciPULSE_LV01'`).
> All other channels use a numeric string for rectangular waveform duration (e.g. `'48'`).
> Use `dod.get_pulse_names()` to list available names.
>
> **Waveform load time:** After `set_nozzle_pulse` is called on channel 1 or 2, the robot
> hardware takes up to 5 s to load the named waveform.  The method blocks for 5 s
> automatically so the waveform is ready before the next command is issued.
>
> **Read-merge-write:** Each single-parameter setter reads current nozzle status
> before writing, so only the specified parameter changes — all others are preserved.
>
> **`set_nozzle_selected` guard:** raises `ValueError` if the requested nozzle is not
> in the active set, preventing a confusing robot-level reject.
>
> **`take_probe` requirements:** Requires the task `'ProbeUptake'` to be present on the
> robot (loaded from the robot's task library). If absent the endpoint silently does
> nothing; the method raises `RuntimeError` by default (`check_task=True`) to make
> this failure explicit. Pass `check_task=False` to skip the pre-flight round-trip.
> The `channel` argument also acts as `SelectNozzle`. The default timeout is
> `max(30, int(volume))` seconds (30 s floor + 1 s/µL at 1 µL/s assumed flow rate);
> pass `timeout=` to override. Valid `well` strings depend on the nozzle configuration
> in the `ProbeUptake` task — the robot rejects invalid wells.

#### LED Strobe

| Command | Description | Units |
|---|---|---|
| `dod.set_led(duration, delay)` | Set strobe pulse width and internal delay (applies to currently selected nozzle) | µs |
| `dod.set_led_per_nozzle(nozzle, duration, delay)` | Select a nozzle then set its strobe parameters in one call | µs |

> **Parameter ranges:** `duration` must be in `[1, 65000]`; `delay` must be in `[0, 6500]`.
> Both raise `ValueError` before sending if a value is out of range.
>
> **Per-nozzle assignment:** Different nozzles can have different strobe settings.
> `set_led_per_nozzle` issues a `SelectNozzle` command first (with a 0.5 s pause)
> then calls `SetLED` — all within a single connect–disconnect transaction.
> The nozzle must be in the active (armed) set; `ValueError` is raised if it is not.
>
> **No read-back endpoint:** There is no `GetLED` API endpoint; the robot does not
> expose current strobe parameters. Track values in calling code if needed.

---

#### Environmental Controls

| Command | Description | Units / Values |
|---|---|---|
| `dod.set_humidity(value)` | Set target relative humidity | %rH, integer, `[0, 100]` |
| `dod.set_cooling_temp(temp)` | Set cooling device temperature | °C (float) or `'dewpoint'` |

> **`set_humidity` range:** raises `ValueError` if `value` is outside `[0, 100]`.
>
> **`set_cooling_temp` modes:** pass a float/int for a fixed setpoint in °C, or the
> string `'dewpoint'` to enable automatic dewpoint-based adjustment.  `ValueError`
> is raised if `temp` is neither.

---

#### Tasks

| Command | Description |
|---|---|
| `dod.get_task_names()` | List all available robot tasks |
| `dod.get_task_details('task_name')` | Get details of a named task |
| `dod.do_task('task_name')` | Execute a named task (blocks until complete) |
| `dod.do_task('task_name', handle_dialog='auto_ok')` | Execute a task; auto-close single-button dialogs |
| `dod.do_task('task_name', handle_dialog='auto_1')` | Execute a task; auto-close all dialogs with Button1 |
| `dod.stop_task()` | Stop a currently running task |
| `dod.clear_abort()` | Clear abort state and refresh status |

> **Mid-run abort:** Set `dod.safety_abort = True` while `do_task` is running to
> stop the task on the next polling cycle (~0.5 s).

> **Dialog handling:** If the robot enters `"Dialog"` state during a task,
> `do_task` always prints the dialog message and button labels.  With the default
> `handle_dialog='raise'` it returns a paused-state dict and waits for you to call
> `dod.close_dialog(ref, selection)` manually.  See [Error Recovery](#error-recovery)
> below for the full workflow.

---

#### Error Recovery

Use these commands when the robot is stuck in `"Dialog"` or `"Error"` state.

| Command | Description |
|---|---|
| `dod.get_status()['Status']` | Check current robot status (`'Idle'`, `'Busy'`, `'Dialog'`, `'Error'`) |
| `dod.close_current_dialog(1)` | Print dialog message then close with Button1 (typically `'OK'`) — one-liner |
| `dod.close_current_dialog(2)` | Print dialog message then close with Button2 (typically `'Abort'`) — one-liner |
| `dod.close_dialog(ref, 1)` | Close a specific dialog by reference integer with Button1 |
| `dod.close_dialog(ref, 2)` | Close a specific dialog by reference integer with Button2 |
| `dod.reset_error()` | Clear persistent `"Error"` status after all dialogs are closed |

**Typical error-recovery workflow:**

```python
# Close the current dialog (prints message and buttons before closing)
dod.close_current_dialog(1)   # press OK / Yes
dod.close_current_dialog(2)   # press Abort / No

# If more dialogs are stacked, repeat until Status != 'Dialog':
while dod.get_status().get('Status') == 'Dialog':
    dod.close_current_dialog(1)

# If Status is still 'Error' after all dialogs are dismissed:
dod.reset_error()
```

If you need to inspect the dialog before deciding which button to press:

```python
status = dod.get_status()
print(status['Dialog']['Message'])
print(status['Dialog']['Button1'], '/', status['Dialog'].get('Button2', ''))
dod.close_current_dialog(1)   # or 2
```

> **Multiple dialogs:** If more than one dialog is open, `get_status()` reports
> the **most recent** one first — close them LIFO (last in, first out). Re-check
> status after each call until `Status != 'Dialog'`.

---

### CoDI Commands

#### Position Presets

| Command | Description |
|---|---|
| `dod.codi.get_presets()` | List all stored named presets |
| `dod.codi.get_pos()` | Read current position; returns `(name, rot_base, rot_left, rot_right, trans_z)` |
| `dod.codi.get_pos(precision_digits=2)` | Same, with custom rounding precision for name-matching (default: 1) |
| `dod.codi.move_to_preset('preset_name')` | Move to a named preset (blocks until done, 30 s timeout) |
| `dod.codi.move_to_preset('preset_name', wait=False)` | Move without blocking |
| `dod.codi.move_to_preset('preset_name', timeout=60)` | Move with custom timeout in seconds |
| `dod.codi.add_preset('name', base, left, right, z)` | Add or overwrite a named preset |
| `dod.codi.save_current_pos('name')` | Save current motor positions as a new preset |
| `dod.codi.update_z_all_presets()` | Apply current z to all stored presets |
| `dod.codi.reload_presets()` | Reload hutch-python motor presets into the local dictionary |
| `dod.codi.remove_preset('name')` | Remove a preset from the local dictionary |

Default presets: `'aspiration'`, `'angled_vert'`, `'angled_hor'`.

> **`get_pos` name matching:** The returned name is `None` if no preset matches
> the current position within `precision_digits` decimal places.  Increase
> `precision_digits` to require a tighter match.

> **`dryrun` property:** `dod.codi.dryrun` can be read or set directly.
> Setting `dod.dryrun = True/False` propagates automatically to `dod.codi`.

> **Deprecated aliases:** The old `CoDI_*` method names (`get_CoDI_predefined`,
> `set_CoDI_pos`, etc.) still work but emit `DeprecationWarning`.  They will be
> removed after one beamtime cycle.  Update call sites to the new names above.

#### Manual Moves

| Command | Description | Units |
|---|---|---|
| `dod.codi.move_z_abs(z)` | Move z-translation to absolute position | mm |
| `dod.codi.move_z_rel(dz)` | Move z-translation by relative offset | mm |
| `dod.codi.move_rot_base_abs(angle)` | Move base rotation to absolute angle | deg |
| `dod.codi.move_rot_left_abs(angle)` | Move left nozzle to absolute angle | deg |
| `dod.codi.move_rot_right_abs(angle)` | Move right nozzle to absolute angle | deg |
| `dod.codi.move_rot_base_rel(da)` | Rotate base by relative offset | deg |
| `dod.codi.move_rot_left_rel(da)` | Rotate left nozzle by relative offset | deg |
| `dod.codi.move_rot_right_rel(da)` | Rotate right nozzle by relative offset | deg |

---

### Timing

The timing system controls four EVR triggers: X-ray, nozzle 1, nozzle 2, and LED.
All values are in **nanoseconds** unless otherwise noted.

#### Timing Parameters

| Parameter | Attribute | Default |
|---|---|---|
| X-ray trigger (absolute) | `dod.timing_Xray` | Read from PV at startup |
| Nozzle 1 delay (relative to X-ray) | `dod.timing_delay_nozzle_1` | Computed at startup |
| Nozzle 2 delay (relative to X-ray) | `dod.timing_delay_nozzle_2` | Computed at startup |
| LED delay (relative to X-ray) | `dod.timing_delay_LED` | 1 000 ns |
| Reaction delay | `dod.timing_delay_reaction` | 0 ns |
| Science pulse offset (fixed) | `dod.timing_delay_sciPulse` | 60 600 ns |

#### Timing Commands

| Command | Description |
|---|---|
| `dod.set_reaction_timing_rel(ns)` | Set the drop-to-X-ray reaction delay |
| `dod.set_led_timing_rel(ns)` | Set the LED delay relative to X-ray |
| `dod.set_nozzle_timing_zero(1, ns)` | Set the time-zero reference for nozzle 1 or 2 (LED alignment step) |
| `dod.set_nozzle_timing_rel(1, ns)` | Adjust nozzle 1 or 2 timing by a relative offset |
| `dod.set_nozzle_timing_abs(1, ns)` | Set nozzle 1 or 2 delay to an absolute value |
| `dod.set_xray_timing_ref(ns)` | Update the X-ray timing reference used in nozzle delay math |
| `dod.print_timing()` | Print all current timing values (in µs) to the console |
| `dod.logging_string()` | Return e-log string with current timing and CoDI state |
| `dod.logging_string(post_elog=True)` | Return and post to the MFX e-log |
| `dod.logging_string(post_elog=True, tag='CoDI', run_number=42)` | Post with custom tag and run number |

> **Note:** If a calculated nozzle delay is negative, one full 120 Hz period
> (`_PERIOD_120HZ_NS` ≈ 8.33 ms) is added automatically.
>
> **`_timing_update()`** is now private (leading underscore).  It is called
> automatically by all timing setters — do not call it directly.

---

### CoDI Alignment Wrapper

`codi_align` is an interactive terminal-based alignment tool with four modes
corresponding to the four alignment steps. Press `?` inside the tool for a
full procedure walkthrough.

```python
from dod.codi import codi_align
codi_align(codi)              # position and overlap modes only
codi_align(codi, dod=dod)     # full 4-mode alignment (requires DoD for T and R)
```

| Mode | Key | What it does | Step |
|---|---|---|---|
| **P** – Position | `p` | Step all four CoDI axes. Keys `1`–`4` select the active axis. | Step 0 |
| **T** – Timing | `t` | Step EVR timing-zero for nozzle 1 or 2. Keys `1`/`2` toggle nozzle. `[`/`]`/`m` mark timing range and jump to midpoint. `=` prompts for direct µs value. Requires `dod`. | Step 1 |
| **Z** – Overlap | `z` | `trans_z` only. `[` marks overlap start, `]` marks overlap end, `m` moves to midpoint. | Step 2 |
| **R** – Reaction | `r` | Step `reaction_timing_rel`. Right = more reaction time. `=` prompts for direct µs value. Requires `dod`. | Step 3 |

Default step sizes: rotation axes **0.05°**, `trans_z` **0.010 mm**, timing **10 µs**.

**Shared controls:**

| Key | Action |
|---|---|
| Left / Right arrows | Move active axis (negative / positive) |
| Up / Down arrows | Halve / double step size of active axis |
| `+` / `-` | Aliases for Up / Down step-size adjustment |
| `s` | Save current CoDI position as a named preset (prompts for name) |
| `h` | Print key map |
| `?` | Print alignment procedure walkthrough (Steps 0–3) |
| `q` | Quit; prompts whether to post session summary to e-log |

> **Dry-run behaviour:** When `codi.dryrun` is `True`, simulated motor positions
> are tracked in memory so the status line reflects each incremental step.
> On quit, if `y` is entered for the e-log prompt, the message that would be
> posted is printed to the console instead.

---

### Dry-run Mode (off-hutch development)

Both `DoD` and `CoDI` can be instantiated on S3DF without a hutch-python session
or any EPICS/robot connections:

```python
import sys
sys.path.insert(0, "/sdf/home/d/dehe/Ops_supp/MFX_Hutch_Python/mfx")

from dod.codi import CoDI
from dod.dod import DoD

codi = CoDI(dryrun=True)
dod  = DoD(dryrun=True, modules='codi', log_file='/tmp/dod.log')
codi = dod.codi   # or use the standalone CoDI above
```

When `dryrun=True`:
- `CoDI` uses `_MockMotor` objects — no SmarAct / EPICS connections.
  Simulated positions are tracked in memory (`_pos`), so incremental steps
  in `codi_align` are reflected in the status line rather than always showing zero.
- `DoD` uses `_MockClient` (no HTTP) and `_MockTrigger` (no EVR PVs)
- All motor moves, DAQ server calls, and timing PV writes print `[DRY RUN]` messages and no-op
- Python state (`timing_delay_*`, `CoDI_pos_predefined`, etc.) is updated normally
- `codi_align(codi, dod=dod)` works for all four modes; on quit, the elog message
  is printed to the console instead of posted

`dryrun` can also be toggled after construction on live hardware (Case B):

```python
dod.dryrun = True    # suppress all hardware writes; python state still updates
dod.dryrun = False   # re-enable hardware writes
```

The setter propagates automatically to `dod.codi`.

---

### Safety

> ⚠️ **The software forbidden-region enforcement is not yet operational.**
> All move methods accept a `safety_test=True` parameter, but the check is not
> fully implemented. Physical motion limits must be respected manually.

The intended safety model defines rectangular forbidden regions in the robot x–y plane.
Three regions are pre-configured at startup:

| Region | x range (µm) | y range (µm) | Applies to |
|---|---|---|---|
| Minimum y boundary | 0 – 300 000 | 0 – 10 000 | Both rotation states |
| Maximum y boundary | 0 – 300 000 | 50 000 – 500 000 | Both rotation states |
| Horizontal-forbidden zone | 0 – 300 000 | 50 000 – 50 000 | Horizontal rotation only |

---

### Connection Issues

The robot's HTTP server occasionally closes idle TCP connections.
The interface handles this **automatically**:

1. Any command that hits a stale connection raises `RemoteDisconnected`.
2. The `_with_reconnect` decorator catches this, waits 1 s, calls `dod.reconnect()`,
   and retries once.
3. If the retry also fails, the exception propagates to the caller.

If the robot remains unresponsive after an automatic retry, call manually:

```python
dod.reconnect()
```

---

## For Developers

### Architecture

```
Hardware (robot server at 172.21.39.172:9999)
        ↑ HTTP GET          [_MockClient in dry-run]
DropsDriver.py   (myClient)         ← context only
HTTPTransceiver.py                  ← context only
        ↑ wrapped by
DoD  (dod.py / dod_dev_documented.py)   ← owned
  ├─ _with_reconnect decorator
  ├─ dryrun property  (propagates to codi)
  ├─ motion:   do_move, move_x/y/z_abs
  ├─ nozzle:   set_nozzle_dispensing, get_nozzle_status
  ├─ led:      set_led, set_led_per_nozzle
  ├─ env:      set_humidity, set_cooling_temp
  ├─ tasks:    do_task, get_task_names, get_task_details
  ├─ safety:   set/get/test_forbidden_region  [not yet operational]
  ├─ timing:   set_nozzle_timing_*, set_reaction_timing_rel,
  │            set_led_timing_rel, set_xray_timing_ref,
  │            _format_timing, print_timing, logging_string
  │            [_MockTrigger in dry-run]
  └─ dod.codi ──→ CoDI  (codi.py)  ← owned
                    ├─ dryrun property
                    ├─ four SmarAct motors  [_MockMotor in dry-run]
                    │    rot_base, rot_left, rot_right, trans_z
                    ├─ named preset dictionary (CoDI_pos_predefined)
                    └─ codi_align(codi, dod=None)  ← top-level function
```

---

### File Inventory

#### Owned files (edit freely)

| File | Description |
|---|---|
| `dod_dev_documented.py` | Primary `DoD` class. Fully documented with numpy-style docstrings. `log_file` default points to the deployed path. |
| `dod.py` | Local test copy. Identical to `dod_dev_documented.py` except `log_file` defaults to `/tmp/dod.log`. |
| `codi.py` | `CoDI` class. Fully documented with numpy-style docstrings. |

#### Context files (do not edit)

Deployed at `/reg/g/pcds/pyps/apps/hutch-python/mfx/dod/`.

---

##### `DropsDriver.py`

Defines `myClient` — the TCP/HTTP client that wraps every robot command.

**Construction (`myClient.__init__`):**
- Creates a single `HTTPConnection` stored as `self.conn`.
- Creates an `HTTPTransceiver` stored as `self.transceiver`.
- Instantiates `SupportedEndsHandler`; calls `reload_all()` only when `reload=True`
  (first load). Skipped on reconnect to avoid slow HTTP requests.
- Calls `pprint.pprint(self.supported_ends())` unconditionally — prints to stdout
  on every instantiation (see [Known Issues](#known-issues)).

**`middle_invocation_wrapper` decorator:**
Applied to every robot command method. On each call it:
1. Logs the function name at INFO level.
2. Calls the wrapped function (which calls `self.send(endpoint)`).
3. Calls `self.get_response()` and returns the result.

**Full API method list:**

| Method | HTTP endpoint | Notes |
|---|---|---|
| `connect(user)` | `GET /DoD/Connect?ClientName={user}` | Required before any `do` request |
| `disconnect()` | `GET /DoD/Disconnect` | Ends `do`-request access |
| `get_status()` | `GET /DoD/get/Status` | Returns robot state dict |
| `get_position_names()` | `GET /DoD/get/PositionNames` | Returns list of named positions |
| `get_current_positions()` | `GET /DoD/get/CurrentPosition` | Returns current + real position |
| `get_task_names()` | `GET /DoD/get/TaskNames` | Returns list of task names |
| `get_task_details(task_name)` | `GET /DoD/get/TaskDetails?TaskName={value}` | Returns task content |
| `get_drive_range()` | `GET /DoD/get/DriveRange` | Returns max range per axis (µm) |
| `get_nozzle_status()` | `GET /DoD/get/NozzleStatus` | Returns nozzle parameters and state |
| `get_pulse_names()` | `GET /DoD/get/PulseNames` | Returns available sciPULSE shapes |
| `move(position)` | `GET /DoD/do/Move?PositionName={value}` | Move to named position |
| `move_x(value)` | `GET /DoD/do/MoveX?X={value}` | Absolute x move (µm); no safety check |
| `move_y(value)` | `GET /DoD/do/MoveY?Y={value}` | Absolute y move (µm); no safety check |
| `move_z(value)` | `GET /DoD/do/MoveZ?Z={value}` | Absolute z move (µm); no safety check |
| `move_to_interaction_point()` | `GET /DoD/do/InteractionPoint` | Move to IP; enables dispenser offset UI |
| `execute_task(value)` | `GET /DoD/do/ExecuteTask?TaskName={value}` | Run a named task |
| `auto_drop()` | `GET /DoD/do/AutoDrop` | Runs the `AutoDropDetection` task |
| `stop_task()` | `GET /DoD/do/StopTask` | Stops running task or move |
| `select_nozzle(channel)` | `GET /DoD/do/SelectNozzle?Channel={channel}` | Select active nozzle |
| `dispensing(state)` | `GET /DoD/do/Dispensing?State={state}` | `'Trigger'`, `'Free'`, or `'Off'` |
| `setLED(duration, delay)` | `GET /DoD/do/SetLED?Duration={d}&Delay={d}` | Strobe LED parameters |
| `set_nozzle_parameters(...)` | `GET /DoD/do/SetNozzleParameters?...` | Set active/selected nozzles, volt, pulse, freq |
| `take_probe(channel, well, vol)` | `GET /DoD/do/TakeProbe?Channel={c}&ProbeWell={w}&Volume={v}` | Requires `ProbeUptake` task present; surfaced as `dod.take_probe()` |
| `set_ip_offset()` | `GET /DoD/do/InteractionPoint` | Sets IP offset from current nozzle position |
| `set_humidity(value)` | `GET /DoD/do/SetHumidity?rH={value}` | Sets target humidity (%rH, integer) |
| `set_cooling_temp(temp)` | `GET /DoD/do/SetCoolingTemp?Temp={temp}` | Sets cooling device temperature (°C or `"dewpoint"`) |
| `close_dialog(ref, sel)` | `GET /DoD/do/CloseDialog?Reference={r}&Selection={s}` | Closes a dialog when `Status == "Dialog"` |
| `reset_error()` | `GET /DoD/do/ResetError` | Clears persistent `"Error"` status after dialogs closed |

> **Note:** Only a subset of these methods is currently surfaced through the `DoD`
> class. The remainder are available on `dod.client` directly.

---

##### `HTTPTransceiver.py`

Handles the raw HTTP communication layer.

**`send(endpoint)`:**
1. Logs the endpoint at INFO level.
2. Calls `print(endpoint)` — writes to stdout unconditionally (see [Known Issues](#known-issues)).
3. Calls `self.__conn__.request("GET", endpoint)`.
4. Calls `self.__conn__.getresponse()` and wraps the reply in a `ServerResponse`.
5. Puts the `ServerResponse` on a `Queue` and releases a `Semaphore`.

**`get_response()`:**
- Acquires the `Semaphore` with a **10 s timeout**. Returns `None` on timeout.
- Pops and returns the `ServerResponse` from the `Queue`.

---

##### `ServerResponse.py`

Parses the raw HTTP JSON body into a Python object.

**JSON → Python attribute mapping:**

| JSON key | Python attribute | Typical value |
|---|---|---|
| `"Time"` | `.TIME` | `"3/18/2024 8:01:26 AM"` |
| `"Status"` | `.STATUS` | `{"Status": "Idle", "StatusCode": 200}` |
| `"LastID"` | `.LAST_ID` | integer timestamp |
| `"ErrorCode"` | `.ERROR_CODE` | `0` = no error |
| `"ErrorMessage"` | `.ERROR_MESSAGE` | `"NA"` when no error |
| `"Result"` | `.RESULTS` | varies by endpoint (see below) |

**`STATUS` values:**

| `STATUS["Status"]` | Meaning |
|---|---|
| `"Idle"` | Robot is ready |
| `"Busy"` | Task or move in progress |
| `"Dialog"` | Robot is waiting for a dialog response |
| `"Error"` | Error state; check `ERROR_MESSAGE` |

**`RESULTS` by endpoint:**

| Endpoint | `RESULTS` structure |
|---|---|
| `get/Status` | `{"Position": {"X": 0, "Y": 0, "Z": 500}, "LastProbe": "", "Humidity": 10, "Temperature": 228, "BathTemp": -99}` |
| `get/CurrentPosition` | `{"CurrentPosition": 0, "Position": ["0", "name", "x", "y", ...], "PositionReal": {"X": 0, "Y": 0, "Z": 500}}` |
| `get/TaskNames` | List of task name strings (see `supported.json`) |
| `get/PositionNames` | List of position name strings (see `supported.json`) |
| `get/NozzleStatus` | `{"Activated Nozzles": ..., "Selected Nozzles": ..., "ID,Volt,Pulse,Freq,Volume": [...], "Dispensing": ...}` |
| `do/*` | `"Accepted"` or `"Rejected"` string |

`ServerResponse.__str__` prints all six fields in a readable multi-line format.

---

##### `JsonFileHandler.py`

Reads and writes `supported.json` — the local cache of supported API endpoints.

**`supported.json` file structure:**

```json
{
    "header": {
        "Time": "3/18/2024 8:01:26 AM",
        "Status": {"Status": "Idle", "StatusCode": 200},
        "LastID": 1579463888163,
        "ErrorCode": 0,
        "ErrorMessage": "NA",
        "Result": {}
    },
    "endpoints": [
        {
            "API": "/DoD/get/Status",
            "payload": { "Position": {...}, "Humidity": 10, ... },
            "args": null,
            "__comments__": null
        },
        {
            "API": "/DoD/do/Move?PositionName={value}",
            "payload": "Accepted",
            "args": {"PositionName": " "},
            "_comment": "/DoD/do/Move?PositionName={value}"
        }
    ]
}
```

**Key methods:**

| Method | Description |
|---|---|
| `reload_endpoints()` | Reads the file; builds an `endpoints_map` dict of `{API_string: list_index}` for fast lookup. Called in `DoD.__init__` and `DoD.reconnect()`. |
| `get_endpoint_data(endpoint)` | Returns the `payload` field for a given API string, or `None` if not found. |
| `add_endpoint(endpoint, payload, args, comment)` | Appends a new entry to the file; skips if the API string already exists. |
| `create_new_supported_file()` | Creates an empty `supported.json`; no-op if the file already exists. |

---

##### `SupportedEndsHandler.py`

Queries the robot server to populate the in-memory supported-endpoints dict and
optionally fetches valid argument values for `do` endpoints.

**In-memory structure (`self.supported_ends`):**

```python
{
    'get':  ["/DoD/get/Status", "/DoD/get/TaskNames", ...],   # list of GET endpoints
    'do':   {"/DoD/do/Move?PositionName={value}": [...],      # dict: endpoint → valid values
             "/DoD/do/MoveX?X={value}": None, ...},           # None for numeric args
    'conn': ["/DoD/Connect?ClientName={value}", "/DoD/Disconnect"]
}
```

**`reload_all()`:**
1. Reads `supported.json` and splits endpoints into `get`, `do`, and `conn` buckets.
2. For each `do` endpoint that takes a non-numeric argument (i.e. not MoveX/Y/Z),
   constructs a `GET /DoD/get/{ArgumentName}s` request to fetch valid values from
   the live robot. This is the slow part — skipped when `reload=False` (used in
   `DoD.reconnect()` to keep reconnect fast).

**`reload_endpoint(endpoint)`:**
Updates a single `do` endpoint's valid-value list without reloading all endpoints.

---

##### `supported.json`

Local cache of robot endpoints, used to initialise `myClient` without making live
HTTP requests. Contains example `payload` structures for each endpoint.

**Named positions** (as of last cache update — robot may have more):

```
Home, InteractionPoint, CameraStation, WasteStation1, WashStation1,
Eppi1Nozzle1, Eppi2Nozzle1, Eppi3Nozzle1, Eppi4Nozzle1,
DabStation, WetDabStation, IP_up, Sample_up, yag, AgB,
2N_1E_up … 2N_4E_up, 3N_1E_up … 3N_4E_up, 4N_1E_up … 4N_4E_up,
"Nozzle 4 IP", "Probe (96WP-1nozzle_mailin)", "Target (Test)", dummy
```

**Task names** (subset of ~80 stored tasks — see full list in file):

```
MorningWashProcedure, MoveHome, MoveToInteractionPoint,
AutoDropDetection, AutoDropDetectionDropVolume,
ProbeUptake, TakeProbe_*, GiveBackProbe_*, DipWashStation1,
WashFlush_Light/Medium/Strong, Ultimate_Wash_Sequence,
Test_colliding_droplet*, sciCleanEppi1, sciCleanWashTray1, ...
```

---

### hutch-python Loading

Current configuration:

```python
with safe_load('Droplet_on_Demand'):
    from dod.dod import *
    dod = DoD(ip="172.21.39.172", modules='codi')
```

The `modules='codi'` argument causes `DoD.__init__` to instantiate `CoDI()` and store
it as `dod.codi`. The previous separate `safe_load('Droplet_on_Demand_Colliding_Droplets')`
block (standalone `codi = CoDI()`) has been removed.

For standalone testing outside hutch-python:

```python
from dod.dod import DoD
dod = DoD(ip="172.21.39.172", modules='codi', log_file='/tmp/dod.log')
```

---

### `_with_reconnect` Decorator

Applied to all 22 methods that call `self.client.*`. On `RemoteDisconnected`,
`ConnectionResetError`, or `BrokenPipeError`:

1. Sleeps 1 s — the robot server needs a moment after dropping a connection.
2. Calls `self.reconnect()`, which re-instantiates `myClient` with `reload=False`
   to skip the slow endpoint reload.
3. Retries the original call once. If the retry fails, the exception propagates.

`reconnect()` itself is intentionally **not** decorated to avoid infinite recursion.

---

### Logging Redirect

`DoD.__init__` redirects the `dod.DropsDriver` and `dod.HTTPTransceiver` loggers to a
file and sets `propagate=False` to suppress INFO messages from the hutch-python console:

```python
for _log_name in ("dod.DropsDriver", "dod.HTTPTransceiver"):
    _lgr = logging.getLogger(_log_name)
    if not any(isinstance(h, logging.FileHandler) for h in _lgr.handlers):
        _fh = logging.FileHandler(log_file)
        _fh.setFormatter(_dod_log_fmt)
        _lgr.addHandler(_fh)
    _lgr.propagate = False
```

The `if not any(...)` guard prevents duplicate `FileHandler`s if `DoD()` is
instantiated more than once in the same session.

> **Caveat:** `HTTPTransceiver.send()` contains a bare `print(endpoint)` that writes
> directly to stdout. This cannot be suppressed via logging configuration and requires
> modifying `HTTPTransceiver.py`, which is not owned.

---

### Preset Access

`CoDI` uses `getattr()` to read motor preset attributes by name:

```python
preset_rot_base = getattr(self.CoDI_rot_base.presets.positions, preset).pos
```

The previous `exec`-based approach (`exec("preset_rot_base = self.CoDI_rot_base.presets.positions." + preset + ".pos")`) has been removed.  The `getattr` form is safe, debuggable, and raises `AttributeError` cleanly if a preset name is absent rather than failing silently.

---

### Relative Motion and `PositionReal` Format

`move_x_rel`, `move_y_rel`, `move_z_rel`, and `move_rel` read the current
position via `get_current_positions()` and add the supplied delta before calling
the underlying absolute move endpoint.

`PositionReal` in the server response is a dict `{"X": ..., "Y": ..., "Z": ...}`
(confirmed from `supported.json`). The three absolute move methods previously
unpacked it with a bare tuple unpack (`x, y, z = r.RESULTS["PositionReal"]`),
which yields the dict **keys** rather than the values — a latent bug that had no
effect because those variables were only used inside the (unimplemented)
`safety_test` branch. This has been corrected in `move_x_abs`, `move_y_abs`,
and `move_z_abs`, and the relative move methods use explicit key access from the
start.

**`move_rel` coordinate conversion** (`coordinates='hutch'`):

The mapping `hutch(x, y, z) = robot(x, −z, y)` gives:

| Hutch delta | Robot delta |
|---|---|
| `dx` | `dx_robot = dx` |
| `dy` | `dy_robot = dz` (hutch z = robot y) |
| `dz` | `dz_robot = −dy` (hutch y = −robot z) |

Axes with a zero delta are skipped and no move command is issued for that axis.

---

### Recaching the Robot JSON

`supported.json` is a local cache of the robot's API endpoints and their valid
argument values (position names, task names, etc.). There are two distinct
operations depending on what you need:

---

#### Case 1 — Refresh valid values for the current session

Use this when new positions or tasks have been added to the robot since the
hutch-python session started (e.g. after a robot firmware update or configuration
change).

```python
dod.reconnect(reload=True)
```

This re-instantiates `myClient` with `reload=True`, which triggers
`SupportedEndsHandler.reload_all()`. That method:
1. Reads `supported.json` for the base endpoint list.
2. Makes live HTTP GET requests to the robot to fetch fresh valid values for
   `do` endpoints (e.g. current `PositionNames`, `TaskNames`).

**Effect:** updates the in-memory `supported_ends` dict for this session only.
`supported.json` on disk is **not** modified.

---

#### Case 2 — Persist a new endpoint to `supported.json`

Use this when a genuinely new API endpoint needs to be added permanently to the
local cache (e.g. after a robot firmware update that adds a new endpoint).

```python
from dod.JsonFileHandler import JsonFileHandler

jfh = JsonFileHandler('/cds/group/pcds/pyps/apps/hutch-python/mfx/dod/supported.json')
jfh.reload_endpoints()
jfh.add_endpoint(
    endpoint='/DoD/do/NewEndpoint?Param={value}',
    payload='Accepted',
    args={'Param': 'example'},
    comment='Added YYYY-MM-DD — description of new endpoint'
)
```

`add_endpoint` is a no-op if the API string already exists, so it is safe to
call repeatedly.

> **Known limitation:** `SupportedEndsHandler.reload_all()` does not write back
> to `supported.json` automatically — there is an open `TODO` in the source for
> this. Until it is implemented, new endpoints must be added manually via
> `JsonFileHandler.add_endpoint()` or by editing `supported.json` directly.

---

#### Summary

| Need | Method | Persists to disk? |
|---|---|---|
| New positions/tasks added to robot | `dod.reconnect(reload=True)` | No — session only |
| New API endpoint added to robot | `JsonFileHandler.add_endpoint(...)` | Yes |
| Manual edit of `supported.json` | Edit file directly | Yes |

---

### Nozzle Parameter Methods

The seven nozzle parameter methods are built on a **read-merge-write** pattern
using three private helpers and one private low-level wrapper:

```
get_nozzle_status()          ← existing; returns raw status dict
  └─ _parse_nozzle_status()  ← private; returns (active_str, selected_str, params)
       └─ _active_list_to_str() ← private; converts 32-bool list → '1,2,3' string

_set_nozzle_parameters()     ← private; single HTTP transaction (connect → set → disconnect)

get_nozzle_parameters()      ← public; returns parsed per-nozzle dict
get_pulse_names()            ← public; returns list of available sciPULSE waveform names
set_nozzle_voltage(n, v)     ← public; read → merge volt → _set_nozzle_parameters
set_nozzle_pulse(n, p)       ← public; read → merge pulse → _set_nozzle_parameters
set_nozzle_freq(n, f)        ← public; read → merge freq → _set_nozzle_parameters
set_nozzle_active([1,2,3])   ← public; read → replace active list → _set_nozzle_parameters
```

**`_parse_nozzle_status` return format (`params` dict):**

```python
{
    1: {'volt': 0.0,  'pulse': 'sciPULSE_LV01', 'freq': 120, 'volume': 321.0},
    2: {'volt': 57.0, 'pulse': 'VISC01',        'freq': 120, 'volume': 102.0},
    3: {'volt': 83.0, 'pulse': '48',             'freq': 120, 'volume': 310.0},
}
```

**`SetNozzleParameters` HTTP call format:**

```
GET /DoD/do/SetNozzleParameters?Active={active}&Selected={selected}&Volt={v}&Pulse={p}&Freq={f}
```

- `Active` and `Selected` are comma-separated channel number strings (e.g. `'1,2,3'`).
- `Volt` and `Freq` apply to the `Selected` nozzle(s) only.
- The `Activated Nozzles` field in the status response is a 32-element boolean list;
  `_active_list_to_str` converts it to the string format the API expects.

**`middle_invocation_wrapper` kwargs limitation:**

All `myClient` methods are wrapped by `middle_invocation_wrapper`, whose `inner`
function only accepts `*args` — not `**kwargs`. Any call to `self.client.*` must
use **positional arguments** in the order defined in `DropsDriver.py`.

**Pulse shape format by channel:**

| Channel | Pulse format | Example |
|---|---|---|
| 1–2 (sciPULSE) | Named waveform string | `'sciPULSE_LV01'` |
| 3+ (standard) | Numeric duration string | `'48'` |

Use `dod.get_pulse_names()` to retrieve available waveform names.

---

### LED Strobe Methods

Two public methods surface the `SetLED` HTTP endpoint:

```
set_led(duration, delay)              ← direct wrapper; applies to selected nozzle
set_led_per_nozzle(nozzle, d, delay)  ← select-then-set in one transaction
```

**Pattern for `set_led`:**

```
connect → setLED(duration, delay) → disconnect
```

**Pattern for `set_led_per_nozzle`:**

```
[pre-flight: get_nozzle_status → _parse_nozzle_status → guard nozzle in active set]
connect → select_nozzle(nozzle) → sleep(0.5) → setLED(duration, delay) → disconnect
```

The 0.5 s sleep between `select_nozzle` and `setLED` matches the inter-command wait
used in `set_nozzle_dispensing`'s `Off` branch — a defensive pause to let the robot
process the select command before the next `do` request arrives.

**No read-back endpoint:** There is no `GET /DoD/get/LEDStatus` or equivalent.
The strobe parameters are write-only from the API's perspective. If the calling
code needs to track current values, it must maintain them locally.

**`myClient` method name:** `setLED(duration, delay)` (camelCase, matching the
`DropsDriver.py` naming convention). The DoD wrappers use snake_case (`set_led`,
`set_led_per_nozzle`) consistent with the rest of the `DoD` public API.

**Client-side validation (both methods):**

| Parameter | Valid range | Error |
|---|---|---|
| `duration` | `[1, 65000]` µs | `ValueError` |
| `delay` | `[0, 6500]` µs | `ValueError` |

Validation is performed before `connect` so no HTTP transaction is started for
an invalid call.

---

### `dod.py` vs `dod_dev_documented.py`

These two files must remain in sync. The **only** intentional difference is the
`log_file` default:

| File | `log_file` default |
|---|---|
| `dod_dev_documented.py` | `/cds/group/pcds/pyps/apps/hutch-python/mfx/dod/dod.log` |
| `dod.py` | `/tmp/dod.log` |

**Workflow:** edit `dod_dev_documented.py` first, then apply the identical change
to `dod.py`.

---

### Dry-run Architecture (developer reference)

Three mock classes in `dod.py` enable construction-time dry-run:

| Mock class | Replaces | Notes |
|---|---|---|
| `_MockClient` | `myClient` | `__getattr__` returns a callable that returns `_MockServerResponse()` for any method call |
| `_MockTrigger` | `pcdsdevices.evr.Trigger` | Has `ns_delay` → `_MockDelay` with `.get()=0.0` and `.put()` no-op |
| `_MockDelay` | EVR `ns_delay` channel | Used by `_MockTrigger` |
| `_MockServerResponse` | `ServerResponse` | Has `.STATUS="DRY_RUN"` and `.RESULTS` dict with safe defaults |

In `codi.py`, `_MockMotor` substitutes `SmarAct` motors:

| Mock class | Replaces | Notes |
|---|---|---|
| `_MockMotor` | `SmarAct` | Tracks simulated position in `_pos`; `wm()` returns `_pos`; `umvr` increments it; `mv/umv` set it absolutely; `presets.set/add_hutch` no-ops |

Gate guard pattern used throughout — Python state is always updated; hardware calls are suppressed when `self._dryrun is True`:

```python
if self._dryrun:
    print(f"[DRY RUN] method_name: action suppressed")
    return  # or continue with state update only
# ... live hardware call ...
```

---

## Known Issues

| Issue | Severity | Status |
|---|---|---|
| **Forbidden region enforcement not operational.** `safety_test=True` in all motion methods prints a warning but does not block unsafe moves. | High | Open |
| **`do_task` safety_check stub removed.** The `safety_check` parameter has been removed from both `DoD.do_task` and `SafeRobot.do_task`; the unimplemented stub is gone. | High | Fixed (2026-07-29) |
| **`exec`-based preset access.** `CoDI.__init__` and `update_CoDI_predefined` used `exec()` strings to read motor preset attributes — fragile and opaque. | High | Fixed (2026-07-29) — replaced with `getattr()` |
| **Inverted safety region mapping.** `test_forbidden_region` applied the horizontal list at 0° and the vertical list at 90° — the opposite of physical reality. | High | Fixed (2026-07-29) |
| **Broken CoDI import in `test_forbidden_region`.** `from dod.codi import CoDI_base` caused `ImportError` at runtime. | High | Fixed (2026-07-29) — replaced with `self.codi.CoDI_rot_base.wm()` |
| **`logging_string()` requires `modules='codi'`.** If `DoD` is instantiated without `modules='codi'`, `self.codi` does not exist. `logging_string()` now guards with `hasattr(self, 'codi')`. | Medium | Fixed (guarded) |
| **`move_rel` returns `None` when all deltas are zero.** No move command is issued and the return value is `None` rather than a `ServerResponse`. | Low | Open |
| **`print(endpoint)` in `HTTPTransceiver.send()`.** Writes directly to stdout on every HTTP call; cannot be suppressed without editing the unowned file. | Low | Open |
| **`take_probe` silent-nothing if `ProbeUptake` absent.** The `check_task=True` default guards against this but the task could be present yet misconfigured. | Medium | Mitigated by check_task guard |
| **`safety_test` parameter not yet removed from motion methods.** `do_move`, `move_x/y/z_abs`, etc. still accept `safety_test=False` but the check is unimplemented. Removal deferred (Bug #9) pending coordinated refactor across `dod.py` and `safe_robot.py`. | Medium | Deferred |
| **R-mode stepping not cumulative in `codi_align`.** `set_reaction_timing_rel` replaces `timing_delay_reaction` rather than incrementing it, so each R-mode keypress set the value to ±step instead of accumulating. | Medium | Fixed — `codi_align` now passes `dod.timing_delay_reaction + step` |
| **`[DRY RUN] _timing_update` prints flood terminal in `codi_align`.** Each T/R-mode keypress triggered a `print()` in raw-terminal mode, scrolling the status display. | Low | Fixed — `codi_align` sets `dod._dryrun_quiet = True` for the duration of the session |
