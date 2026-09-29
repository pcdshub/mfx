# k_xas_scan — Requirements & Implementation Plan

**Date:** 2026-06-19  
**Status:** IN PROGRESS  
**Target file:** `/sdf/home/l/lbgee/mfx_main/mfx/mfx/exafs.py`

---

## Requirements (from grilling session)

### Purpose
New scan method on the `Exafs` class where the **undulator K is the primary scan axis** and the DCCM fills in a small energy window around each K position. Designed for commissioning undulator motion at MFX and evaluating whether data can be collected during K transit.

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Separate method vs mode flag | New method `k_xas_scan` | No regression risk to `long_escan` |
| DCCM motion mode | `dccm.energy.move()` (crystal-only) | No vernier requests — vernier PV will be rejected by accelerator |
| K step size | Defaults to `2 * dccm_window_eV` | Seamless tiling of DCCM windows |
| DCCM window | ±2 eV default, 1 eV step | Matches SASE bandwidth for upcoming experiment |
| K move behavior | `'pause'` (default) or `'concurrent'` | Concurrent mode tests whether data during K transit is usable |
| Concurrent mode behavior | Request K non-blocking → move DCCM to first offset → step through grid | Early points = during transit, later points = settled |
| K positions | Start at `start_eV`, step by `k_step_eV`, stop when > `end_eV` | Simple, predictable (option A) |
| Simulation | Full support | Must test before precious beam time |
| Elog | Skip for MVP | Print params at start is sufficient |
| Return value | Lightweight summary list + print | Quick in-hutch evaluation |

### Constraints
- **No vernier access** in upcoming experiment
- **No transfocator** (negligible focus change over 50 eV)
- **No undulator pointing** for MVP
- **No K³ time weighting** — uniform dwell

### What's Included (MVP)
- [x] K-primary scan loop
- [x] Two K move modes: `'pause'` and `'concurrent'`
- [x] Configurable DCCM window (±eV, step size)
- [x] Optional `dccm_offsets` list override
- [x] FEE spectrometer tracking (optional)
- [x] Beam status monitoring (optional)
- [x] Simulation mode
- [x] Parameter printout at start
- [x] Summary returned at end
- [x] KeyboardInterrupt cleanup

### What's Excluded (MVP)
- Vernier alignment (tchk)
- Transfocator tracking
- Elog posting
- Undulator pointing
- K³-weighted timing
- Adaptive DCCM window

---

## Method Signature

```python
def k_xas_scan(self,
    start_eV, end_eV, element='Fe',
    k_step_eV=None,            # defaults to 2*dccm_window_eV
    k_move_mode='pause',       # 'pause' or 'concurrent'
    dccm_window_eV=2.0,        # ±this around K center
    dccm_step_eV=1.0,          # step within window
    dccm_offsets=None,         # explicit list override (eV relative to K)
    dwell_time=1.0,            # seconds per DCCM point
    record=False,
    picker=None,
    track_feespec=False,
    flux_threshold=None,
    crystal_angle_offset=0.0,
    sample='?',
    simulate=False,
    runs=1,
):
```

---

## Execution Flow

```
k_xas_scan()
│
├── 1. Validate parameters, compute defaults
│       ├── k_step_eV = 2 * dccm_window_eV if None
│       ├── Compute dccm_offsets from window/step if not provided
│       └── Compute K positions: arange(start_eV, end_eV + k_step_eV, k_step_eV)
│
├── 2. Print scan configuration
│
├── 3. Store initial positions (DCCM energy, K energy)
│
├── 4. FOR each run (1..runs):
│       │
│       ├── 4a. Setup DAQ (pause/resume for whole scan)
│       │
│       ├── 4b. FOR each K position:
│       │       │
│       │       ├── IF k_move_mode == 'pause':
│       │       │   ├── Pause DAQ
│       │       │   ├── Move K (blocking)
│       │       │   ├── Move FEE spec (if track_feespec)
│       │       │   ├── Resume DAQ
│       │       │   └── FOR each dccm_offset:
│       │       │       ├── Move DCCM (crystal only)
│       │       │       ├── check_beam_status()
│       │       │       ├── Wait dwell_time
│       │       │       └── Record to summary
│       │       │
│       │       └── IF k_move_mode == 'concurrent':
│       │           ├── Request K move (non-blocking)
│       │           ├── Move FEE spec (if track_feespec)
│       │           └── FOR each dccm_offset:
│       │               ├── Move DCCM (crystal only)
│       │               ├── check_beam_status()
│       │               ├── Wait dwell_time
│       │               └── Record to summary
│       │
│       └── 4c. End of run
│
├── 5. EXCEPT KeyboardInterrupt:
│       ├── Return to initial positions
│       └── Print abort message
│
├── 6. _finalize: Return to initial positions
│
└── 7. Print and return summary
```

---

## Implementation Steps

- [ ] Step 1: Write `k_xas_scan` method skeleton with full docstring
- [ ] Step 2: Implement parameter validation and K/DCCM position computation
- [ ] Step 3: Implement `'pause'` mode scan loop
- [ ] Step 4: Implement `'concurrent'` mode scan loop
- [ ] Step 5: Implement summary generation and return
- [ ] Step 6: Test in simulation mode (dry run the logic)

---

## Progress Log

| Time | Action | Status |
|------|--------|--------|
| 2026-06-19 | Requirements finalized from grilling session | DONE |
| 2026-06-19 | Implementation plan written | DONE |
| 2026-06-19 | `k_xas_scan` method implemented in exafs.py | DONE |
| 2026-06-19 | `_k_xas_move_pause` helper implemented | DONE |
| 2026-06-19 | `_k_xas_move_concurrent` helper implemented | DONE |
| 2026-06-19 | AST parse verification (Python 3.8) | PASSED |
| 2026-06-19 | Logic test (numpy, tiling, coverage) | PASSED |

---

## Test Results

### AST Parse
- Python 3.8: PASS
- Methods found: `k_xas_scan`, `_k_xas_move_pause`, `_k_xas_move_concurrent`

### Logic Test (7100-7150 eV, ±2 eV window, 1 eV step)
- K positions: 13 (7100 to 7148 eV, step 4 eV)
- DCCM offsets: [-2, -1, 0, +1, +2] (5 points per K)
- Total points: 65
- Energy coverage: 7098–7150 eV
- Max gap: 1.0 eV (seamless tiling)
- Est. time (pause): 117s (1.9 min)
- Est. time (concurrent): 65s (1.1 min)

---
