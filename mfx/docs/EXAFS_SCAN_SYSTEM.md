# MFX EXAFS Scan System — Technical Documentation

## Overview

The EXAFS (Extended X-ray Absorption Fine Structure) scan system at MFX provides automated energy scanning from the pre-edge through the EXAFS region. It coordinates multiple hardware subsystems — monochromator, undulator, vernier, transfocator, and FEE spectrometer — to maintain beam quality while stepping through hundreds of energy points.

The primary entry point is `Exafs.long_escan()` in `exafs.py`.

---

## File Map

| File | Role |
|------|------|
| `exafs.py` | Main controller (`Exafs` class) and energy range builder (`EXAFSEnergyRangeBuilder`) |
| `dccm.py` | Double Crystal Channel-cut Monochromator device classes (Bragg angle ↔ energy) |
| `xrt_spec.py` | FEE spectrometer tracking (crystal/camera angle calculations and motion) |
| `xas.py` | Simpler XAS scan utilities (`continuous_dccmscan`, `run_dccmscan`) |
| `optimize/beamline_hw.py` | Device initialization (vernier PV, intensity diagnostics) |
| `optimize/beam.py` | Undulator beam alignment |
| `optimize/beam_status.py` | Beam flux monitoring (`BeamCheck`) |
| `devices.py` | LaserShutter and other device definitions |
| `beamline.py` | Top-level hardware instantiation |

---

## Hardware Subsystems

### 1. DCCM (Double Crystal Channel-cut Monochromator)

**File:** `dccm.py`  
**PV Prefix:** `SP1L0:DCCM`

The DCCM uses two matched Si(111) crystals in a channel-cut geometry. Energy selection uses Bragg's Law:

```
E (keV) = 12.398 / (2 × d × sin(θ))
d = 3.13560114 Å  (Silicon 111)
```

Three energy control modes are available:

| Mode | Class | Behavior |
|------|-------|----------|
| Basic | `DCCMEnergy` | Moves crystals (th1, th2) only |
| With Vernier | `DCCMEnergyWithVernier` | Moves crystals + requests MCC vernier change |
| With ACR Status | `DCCMEnergyWithACRStatus` | Moves crystals + vernier + waits for ACR completion |

The `long_escan` uses `energy_with_vernier` mode — each DCCM move automatically requests the Machine Control Center (MCC) to adjust the vernier energy so the undulator stays tuned.

**Motor Axes:**
- `th1` / `th2` — Bragg angle (BeckhoffAxis)
- `tx` — Chamber translation X
- `txd` / `tyd` — YAG diagnostic positioning

---

### 2. Undulator K Parameter

**Class:** `BeamEnergyRequestACRWait` from `pcdsdevices.beam_stats`  
**PV Prefix:** `MFX`, **ACR Status Suffix:** `AO805`

The undulator K parameter sets the fundamental harmonic of the free-electron laser. Unlike the DCCM (which moves continuously), the K motor is stepped in large jumps (default: 120 eV) because each K move disrupts the DAQ — the run must be paused, the undulator repositioned, and the run resumed.

Two ACR energy request objects are used:
- `acr_energy_v` (pv_index=1) — Vernier energy requests
- `acr_energy_k` (pv_index=2) — Undulator K energy requests

**K stepping logic** (in `_request_k_energy_update`):
1. Calculate distance between current scan energy and K setpoint
2. If distance exceeds `k_stepsize / 2`, a K move is needed
3. Next K position = current K ± k_stepsize (direction depends on `reverse`)
4. Minimum K energy enforced by `min_k_keV` with 1 eV safety margin

---

### 3. Vernier Energy

**Device:** Initialized from `mfx.optimize.beamline_hw.init_devices()["vernier_energy"]`

The vernier provides fine energy tuning independent of the DCCM crystals. The offset between vernier and DCCM drifts with energy, so a calibration system ("track-and-check", or **tchk**) measures and stores the offset at each K energy.

**Alignment Procedure** (`align_vernier_to_dccm`):
1. Read current DCCM energy
2. Scan vernier ±2.5 eV around DCCM energy (21 steps, 50 events per step)
3. Average intensity at each point (10 ms between readings)
4. Move to position with maximum intensity
5. Calculate offset = vernier_position − DCCM_energy

**Tracking Modes** (`tchk` parameter):
| Value | Behavior |
|-------|----------|
| `False` | No vernier tracking |
| `True` | Full alignment at every K energy boundary |
| `'single'` | Measure once per energy, cache for subsequent runs |

**Diagnostics available:**
- `'dg1'` — MFX DG1 intensity (upstream)
- `'dg2'` — MFX DG2 beam monitor (default)
- `'xcs1'` — XCS hutch intensity

---

### 4. Transfocator (Focus Tracking)

**Library:** `tfs` (external)  
**PV Prefix:** `MFX:LENS`

The transfocator uses compound refractive lenses (CRLs) to maintain focus as energy changes. Since focal length is energy-dependent, the lens configuration and Z-stage position must track the scan.

**Initialization** (`_init_tfs`):
- Creates `Transfocator("MFX:LENS")` (or simulated version)
- Optionally pre-computes a focus tracking map showing Z-position and lens configuration vs. energy

**Per-energy-point motion** (`_move_tfs_to_energy`):
1. Look up nearest energy entry in `track_focus_results.json`
2. Move Z-stage to stored position (+ optional `tfs_offset`)
3. Insert/remove lenses to match stored configuration
4. Set attenuation if provided (with 20s fault-state timeout)

**Configuration parameters:**
- `tfs_margin_mm` — safety margin (default: 5.0 mm)
- `ref_focal_length_um` — reference focal length
- `ref_z_stage_mm` — reference Z position
- `tfs_target` — target focal position (default: 400.37)
- `avoid_forbidden_combo` — skip unsafe lens combinations
- `enable_prefocus` — allow prefocusing lenses

---

### 5. FEE Spectrometer

**File:** `xrt_spec.py`  
**Class:** `XRTspec`  
**Hardware:** `HXRSpectrometer("STEP:XRT1")`

The Front-End Enclosure spectrometer monitors photon energy in real-time. Its geometry is calibrated empirically:

```
crystal_angle = 140.08 − 21.2×E + 1.02×E²  (degrees)
camera_angle  = −1.91 + 2 × crystal_angle    (degrees)
camera_y      = −4.92 − 0.111×E              (mm)
```

Where E is photon energy in keV. An optional `crystal_angle_offset` allows fine-tuning.

**Safety:** After every move, XRT transmission alarm (`XRT:HXS:TRNS.SEVR`) is checked. If not `NO_ALARM`, motors return to their previous positions.

**Tracking modes during EXAFS scans:**
- `track_feespec` — move crystal + camera + Y at K boundaries
- `track_feespec_cam` — move only camera angle at each energy point (less disruptive)

---

### 6. DAQ (Data Acquisition)

**System:** LCLS-II DAQ (`psdaq.control.DaqControl`)  
**Access:** `from mfx.db import daq`

The DAQ runs continuously during the energy scan. It records events at each energy point with timing determined by the `wait_time` array.

**State machine:**
```
configured → running → paused → running → ... → configured
```

**Lifecycle during a scan:**
1. `setState("configured")` — prepare DAQ
2. `setRecord(True/False)` — enable data persistence
3. `setState("running")` — start event collection
4. At K boundaries: `setState("paused")` → move K → `setState("running")`
5. End of scan: `setState("configured")` → `setRecord(False)`

**Pulse picker** (`from mfx.db import pp`):
- `'open'` — pulse picker fully open
- `'flip'` — flip-flop mode (alternating shots)
- Closed on scan completion

---

## Energy Range Generation

**Class:** `EXAFSEnergyRangeBuilder` (exafs.py:1669–2009)

Generates an optimized energy point array with four distinct regions:

### Region Layout

| Region | Spacing | Default Time | Purpose |
|--------|---------|--------------|---------|
| Pre-pre-edge | 5 eV | 2 s | Baseline normalization |
| Pre-edge | 0.5 eV | 2 s | Near-edge features |
| Edge | 1 eV | 1 s | XANES structure |
| EXAFS | 0.1 Å⁻¹ in K-space | K³-weighted | Fine structure oscillations |

### K-space Conversion

```
K (Å⁻¹) = √(0.2625 × (E − E₀))
E (eV)  = K² / 0.2625 + E₀
```

Where E₀ is the absorption threshold energy for the element.

### K³-weighted Acquisition Times

EXAFS signal decays as ~1/K³, so acquisition time scales with K³ to maintain constant signal-to-noise:

```python
K_time = K_values ** 3
normalized_time = min_time + (max_time - min_time) * (K_time_range - min) / (max - min)
```

Default range: 0.5 s (low K) to 10 s (high K).

### Supported Elements

| Element | Foil Energy (eV) | Threshold Energy (eV) |
|---------|-------------------|----------------------|
| Sc | 4492.8 | 4510.0 |
| Ti | 4966.4 | 4985.0 |
| V | 5465.1 | 5485.0 |
| Cr | 5989.2 | 6010.0 |
| Mn | 6539.0 | 6560.0 |
| Fe | 7111.2 | 7130.0 |
| Co | 7708.9 | 7730.0 |
| Ni | 8332.8 | 8350.0 |
| Cu | 8978.9 | 9000.0 |
| Zn | 9658.6 | 9680.0 |

---

## Main Scan Loop — `long_escan()`

### Parameters Summary

**Energy Control:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `start_eV` | 0.0 | Scan start (eV) |
| `end_eV` | None | Scan end (eV), overrides max_k |
| `min_k` | 2.0 | Minimum K (Å⁻¹) |
| `max_k` | 12.0 | Maximum K (Å⁻¹) |
| `element` | 'Fe' | Target element |
| `energies_list` | [] | Custom energy array (overrides auto-generation) |
| `wait_time_list` | [] | Custom time array (must match energies_list) |

**Undulator K Control:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `k_stepsize` | 120 | K step size (eV) |
| `k_offset` | 0 | K energy offset (eV) |
| `reverse` | False | Scan high→low |
| `min_k_keV` | 7.035 | Minimum K energy (keV) |

**Tracking & Calibration:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `tchk` | False | Vernier tracking mode (False/True/'single') |
| `diagnostic` | 'dg2' | Vernier alignment diagnostic |
| `track_focus` | False | Enable focus tracking |
| `track_feespec` | False | Track FEE spectrometer at K boundaries |
| `track_feespec_cam` | False | Track FEE camera at every point |
| `map_focus_track` | False | Pre-compute focus map and exit |
| `map_tchk_track` | False | Build new vernier offset map |
| `crystal_angle_offset` | 0.0 | FEE spectrometer crystal offset (degrees) |

**Data Acquisition:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `record` | False | Enable data recording |
| `picker` | None | Pulse picker mode ('open'/'flip'/None) |
| `runs` | 1 | Number of scan repetitions |
| `daq_delay` | 5 | Delay between runs (seconds) |
| `flux_threshold` | None | Minimum beam flux (mJ) |
| `attenuation` | None | Attenuation value |

**Undulator Pointing:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `undulator_point` | False | Enable undulator pointing |
| `undulator_on_diagnostic` | 'dg1' | Pointing diagnostic |
| `undulator_using_device` | 'yag' | Pointing device |
| `undulator_with_method` | 'calib' | Pointing method |
| `undulator_grid_bins` | 5 | Grid bins for calibration |

---

### Execution Flow

```
long_escan()
│
├── 1. Store initial positions (DCCM energy, K energy)
├── 2. Build energy & time arrays
│       └── EXAFSEnergyRangeBuilder.build_energy_range()
│           or use custom energies_list/wait_time_list
│
├── 3. Initialize tracking systems
│       ├── Load track_focus_results.json (if track_focus)
│       ├── _init_tfs() (transfocator setup)
│       └── _init_tchk() (vernier tracking setup)
│
├── 4. FOR each run (1..runs):
│       │
│       ├── 4a. _initialize_energies_and_move()
│       │       ├── Calculate initial K energy
│       │       ├── Reverse arrays if reverse=True
│       │       ├── Move DCCM to first energy
│       │       ├── Move K to initial position
│       │       └── Move FEE spectrometer (if track_feespec)
│       │
│       ├── 4b. check_beam_status() — pause if flux low
│       │
│       ├── 4c. _setup_daq_and_start_recording()
│       │       ├── Connect to LCLS-II DAQ
│       │       ├── Check DAQ state (abort if error)
│       │       ├── Open/flip pulse picker
│       │       ├── Configure DAQ
│       │       └── Start recording
│       │
│       ├── 4d. _align_undulator() (if undulator_point=True)
│       │
│       ├── 4e. FOR each energy point:
│       │       │
│       │       ├── _move_k_if_necessary()
│       │       │   ├── Check delta to K > k_stepsize/2
│       │       │   ├── Pause DAQ
│       │       │   ├── Move FEE spectrometer
│       │       │   ├── Move undulator K
│       │       │   └── Resume DAQ
│       │       │
│       │       ├── _move_tfs_to_energy() (if track_focus)
│       │       │   ├── Lookup lens config in tracking data
│       │       │   ├── Move Z stage
│       │       │   ├── Insert/remove lenses
│       │       │   └── Set attenuation
│       │       │
│       │       ├── check_beam_status()
│       │       │
│       │       ├── _move_dccm_energy_with_vernier()
│       │       │   └── Moves DCCM crystals + requests vernier
│       │       │
│       │       ├── Vernier alignment (if tchk):
│       │       │   ├── 'single': lookup or measure once
│       │       │   └── True: full _align_vernier_to_dccm()
│       │       │
│       │       ├── track_feespec_camera() (if track_feespec_cam)
│       │       │
│       │       ├── _measure_lens_beam_offset() (if mapping)
│       │       │
│       │       └── _wait(wait_time) — dwell for data collection
│       │
│       ├── 4f. Save tracking data (tchk, lens offset)
│       ├── 4g. Post to elog (if recording)
│       └── 4h. sleep(daq_delay) between runs
│
├── 5. EXCEPT KeyboardInterrupt:
│       ├── Post "Run ended prematurely" to elog
│       ├── Return motors to initial positions
│       └── Return FEE spectrometer to initial position
│
└── 6. _finalize_scan()
        ├── Return DCCM to start energy
        ├── Return K to start position
        └── Return FEE spectrometer to start position
```

---

## Beam Status Monitoring

**Method:** `check_beam_status(flux_threshold)`  
**Source:** `mfx.optimize.beam_status.BeamCheck`

When `flux_threshold` is set (mJ), beam intensity is monitored at every energy point:

1. Read gas detector average (`gdet_ave`)
2. If flux < threshold AND DAQ is running → pause DAQ
3. Poll every 1 second until flux recovers
4. Resume DAQ when flux restored

This handles beam dumps and injection interrupts without losing the scan position.

---

## Tracking Data Files

All tracking data is stored as JSON in the user's home directory (`Path.home()`):

| File | Contents |
|------|----------|
| `track_focus_results.json` | Lens configurations and Z positions vs. energy |
| `track_tchk_results.json` | Vernier offsets vs. energy |
| `track_lens_beam_offset_results.json` | Lens beam energy calibration |

**Example `track_focus_results.json` entry:**
```json
{
    "energy": 7200.0,
    "z_position": 451.23,
    "inserted_lenses": ["SIM::MFX:LENS:L1", "SIM::MFX:LENS:L3"]
}
```

**Example `track_tchk_results.json` entry:**
```json
{
    "energy": 7130.0,
    "vernier_offset": -1.2
}
```

---

## Simulation Mode

When `simulate=True`:
- Real motor moves are replaced with `sim.fast_motor1` / `sim.slow_motor1`
- DAQ interactions return immediately with success
- Transfocator uses `make_tfs_sim()` (simulated lens system)
- K energy stored locally instead of reading from EPICS
- No pulse picker, elog, or beam status operations

This allows testing the full scan logic without hardware access.

---

## XAS Module (Simpler Scans)

For quick XANES or single-region scans without full EXAFS automation, `xas.py` provides:

### `continuous_dccmscan(energies, pointTime, move_vernier, bidirectional)`

- Steps DCCM through a provided energy list
- Optional vernier coordination
- Optional bidirectional scanning (forward + reverse)
- Returns to initial energy on completion or Ctrl+C
- Does NOT manage DAQ (user starts/stops independently)

---

## Key EPICS PVs

| System | PV | Purpose |
|--------|-----|---------|
| DCCM θ1 | `SP1L0:DCCM:MMS:TH1` | Upstream Bragg angle |
| DCCM θ2 | `SP1L0:DCCM:MMS:TH2` | Downstream Bragg angle |
| DCCM state | `SP1L0:DCCM:MMS:STATE:SET` | IN/OUT control |
| Undulator K | `MFX:AO805` (pv_index=2) | K energy request |
| Vernier | `MFX:AO805` (pv_index=1) | Vernier energy request |
| DG1 intensity | `MFX:DG1:W8:01:SUM` | Beam monitor |
| DG2 intensity | `MFX:DG2:BMMON:SUM` | Beam monitor (default tchk) |
| XCS intensity | `HXX:DG1:BMMON:SUM` | Alternative diagnostic |
| FEE Spec crystal | `STEP:XRT1` (th) | Spectrometer crystal angle |
| FEE Spec camera | `STEP:XRT1` (tth) | Spectrometer camera angle |
| FEE Spec cam Y | `STEP:XRT1` (camy) | Camera Y position |
| FEE camera acq | `CAMR:FEE1:441:Acquire` | Camera acquisition state |
| XRT transmission | `XRT:HXS:TRNS.SEVR` | Transmission alarm |
| Attenuator status | `MFX:ATT:COM:STATUS` | Attenuator fault state |
| Lens beam energy | `MFX:LENS:BEAM:ENERGY` | Lens system energy readback |

---

## Error Handling

### Keyboard Interrupt (Ctrl+C)

Caught at the outer scan loop level. Cleanup:
1. Post "Run ended prematurely" to elog (if recording)
2. Return DCCM to initial energy
3. Return K to initial position
4. Return FEE spectrometer to initial position

### DAQ Connection Failure

If `daq.control.getInstrument()` returns None or DAQ is in error state, the scan breaks out of the run loop cleanly.

### Attenuator Fault

When setting attenuation, a 20-second timeout loop waits for the `MFX:ATT:COM:STATUS` PV to clear from `Faulted`. If timeout expires, it forces `OK` status and continues.

### XRT Transmission Alarm

After any FEE spectrometer move, the `XRT:HXS:TRNS.SEVR` alarm is checked. If not `NO_ALARM`, motors return to their previous positions immediately.

---

## Elog Integration

When `record=True`, the system posts to the MFX electronic logbook at:
- Scan start (with parameter summary)
- Scan completion
- Premature abort

Posts include all scan parameters and optionally an inspirational quote (`inspire=True`).

---

## Typical Invocation Examples

### Standard Fe K-edge EXAFS scan
```python
exafs = Exafs()
exafs.long_escan(
    element='Fe',
    sample='FeO_sample1',
    min_k=2.0,
    max_k=12.0,
    k_stepsize=120,
    record=True,
    picker='open',
    runs=3
)
```

### XANES-only scan (no EXAFS region)
```python
exafs.long_escan(
    element='Fe',
    start_eV=7080,
    end_eV=7180,
    record=True
)
```

### Full scan with all tracking enabled
```python
exafs.long_escan(
    element='Cu',
    min_k=2.0,
    max_k=14.0,
    tchk='single',
    track_focus=True,
    track_feespec=True,
    track_feespec_cam=True,
    undulator_point=True,
    record=True,
    picker='open',
    flux_threshold=0.5
)
```

### Build focus tracking map (does not run scan)
```python
exafs.long_escan(
    element='Fe',
    map_focus_track=True,
    ref_focal_length_um=3500,
    ref_z_stage_mm=450.0
)
```

### Reverse scan with custom K parameters
```python
exafs.long_escan(
    element='Mn',
    reverse=True,
    k_stepsize=100,
    k_offset=10,
    min_k_keV=6.5,
    min_time_EXAFS=1.0,
    max_time_EXAFS=15.0,
    record=True
)
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `ophyd` | EPICS device framework (EpicsSignal, PseudoPositioner) |
| `pcdsdevices` | LCLS device library (BeckhoffAxis, BeamEnergyRequest, IMS) |
| `tfs` | Transfocator lens control and simulation |
| `psdaq` | LCLS-II DAQ control interface |
| `hutch_python` | Hutch infrastructure (simulation hardware, utilities) |
| `numpy` | Array operations, energy calculations |
| `matplotlib` | Scan profile visualization |
| `epics` | Low-level EPICS channel access (caput) |

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     Exafs.long_escan()                       │
│                   (main scan controller)                      │
└───────┬──────────┬──────────┬──────────┬──────────┬─────────┘
        │          │          │          │          │
        ▼          ▼          ▼          ▼          ▼
┌───────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────────┐
│   DCCM    │ │  K     │ │Vernier │ │  TFS   │ │ FEE Spec   │
│(crystals) │ │(undulr)│ │(fine E)│ │(focus) │ │(diagnostic)│
├───────────┤ ├────────┤ ├────────┤ ├────────┤ ├────────────┤
│Si(111) θ  │ │ACR req │ │ACR req │ │Lenses  │ │Crystal θ   │
│Bragg's Law│ │pv_idx=2│ │pv_idx=1│ │Z stage │ │Camera 2θ   │
│4-25 keV   │ │120eV   │ │±2.5eV  │ │JSON cfg│ │Camera Y    │
│           │ │steps   │ │scan    │ │        │ │            │
└─────┬─────┘ └───┬────┘ └───┬────┘ └───┬────┘ └─────┬──────┘
      │            │          │          │            │
      ▼            ▼          ▼          ▼            ▼
┌─────────────────────────────────────────────────────────────┐
│                    EPICS Control System                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    LCLS-II DAQ System                         │
│            (continuous recording, paused at K moves)          │
└─────────────────────────────────────────────────────────────┘
```

---

## Timing Considerations

For a typical Fe K-edge EXAFS scan (K=2–12 Å⁻¹):

- ~12 pre-pre-edge points × 2 s = 24 s
- ~12 pre-edge points × 2 s = 24 s
- ~18 edge points × 1 s = 18 s
- ~100 EXAFS points × (0.5–10 s, K³-weighted) ≈ 300 s
- K moves (~5 pauses × ~3 s each) ≈ 15 s
- **Total per run: ~6–7 minutes**

With `runs=3`, total scan time ≈ 20 minutes plus inter-run delays.

Focus tracking, vernier alignment, and undulator pointing add overhead at each relevant point (typically 2–5 s per alignment).
