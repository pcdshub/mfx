"""
Per-step timing for undulator K scans (k_xas_scan).

Records wall-clock stamps for each K request so step time can be split
into photon-side overhead and undulator time, then writes a CSV and
posts a plain-text table to the elog at the end of each run.

Stamps are time.time() on the hutch-python host. EPICS timestamps from
epicsArch are the primary record; these are a cross-check.
"""

import csv
import logging
import os
import threading
from pathlib import Path
from time import time

import numpy as np

logger = logging.getLogger(__name__)

COLUMNS = [
    'step', 'e_from_eV', 'e_to_eV', 'de_eV', 'mode',
    't_step_start', 't_k_request', 't_k_done', 't_dwell_start',
    'daq_pause_s', 'feespec_s', 'k_request_s', 'feespec_check_s',
    'daq_resume_s', 'dccm_s', 'total_s',
]

SLOW_STEP_WARN_S = 60.0


def ladder(start_eV, steps=(0.2, 1, 5, 25, 100), n=5):
    """
    Ascending K positions: n steps of each size in `steps`, starting at start_eV.

    Default gives 26 positions spanning start_eV to start_eV + 656 eV.
    Values are rounded to 0.1 eV to survive k_xas_scan rounding.
    """
    e = [float(start_eV)]
    for s in steps:
        for _ in range(n):
            e.append(e[-1] + s)
    return np.round(e, 1)


class StepTimer:
    """Collects one row per K step for a single DAQ run."""

    def __init__(self, mode):
        self.mode = mode
        self.rows = []
        self._row = None
        self._prev_eV = None

    def start_step(self, e_to_eV):
        self._row = {c: np.nan for c in COLUMNS}
        self._row.update(
            step=len(self.rows) + 1,
            e_from_eV=self._prev_eV if self._prev_eV is not None else np.nan,
            e_to_eV=e_to_eV,
            mode=self.mode,
            t_step_start=time(),
        )
        if self._prev_eV is not None:
            self._row['de_eV'] = round(e_to_eV - self._prev_eV, 1)

    def set(self, key, value):
        if self._row is not None:
            self._row[key] = value

    def timed_k_request(self, positioner, target_eV, **kwargs):
        """Call positioner.move() and record request/done stamps."""
        warn = threading.Timer(
            SLOW_STEP_WARN_S,
            lambda: logger.warning(
                f"K request to {target_eV:.1f} eV still not done after "
                f"{SLOW_STEP_WARN_S:.0f} s. If it passes 120 s: Ctrl+C, "
                f"caget SIOC:SYS0:ML07:AO805, call ACR."))
        warn.daemon = True
        t0 = time()
        self.set('t_k_request', t0)
        warn.start()
        try:
            status = positioner.move(target_eV, **kwargs)
        finally:
            warn.cancel()
        t1 = time()
        self.set('t_k_done', t1)
        self.set('k_request_s', t1 - t0)
        return status

    def end_step(self):
        """Call at dwell start."""
        if self._row is None:
            return
        t = time()
        self._row['t_dwell_start'] = t
        self._row['total_s'] = t - self._row['t_step_start']
        self.rows.append(self._row)
        self._prev_eV = self._row['e_to_eV']
        self._row = None


def _fmt(v, width=7, prec=1):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return '-'.rjust(width)
    return f"{v:{width}.{prec}f}"


def _mean_sd(values):
    v = np.array(values, dtype=float)
    v = v[~np.isnan(v)]
    if v.size == 0:
        return '     -         '
    return f"{v.mean():6.1f} +- {v.std():4.1f}"


def format_table(rows, run_number, mode):
    """Plain-text per-step table plus mean +- sd per step size."""
    if not rows:
        return f"Run {run_number}  {mode}  no steps recorded"
    e_lo = min(r['e_to_eV'] for r in rows)
    e_hi = max(r['e_to_eV'] for r in rows)
    lines = [
        f"Run {run_number}  {mode}  {e_lo:.1f}-{e_hi:.1f} eV  "
        f"{len(rows)} steps",
        "times in s. k_move = K request write to done PV. "
        "total = step start to dwell start.",
        "",
        " step   E_from    E_to      dE  pause   fee  k_move  fee_chk "
        "resume   dccm   total",
    ]
    for r in rows:
        lines.append(
            f"{r['step']:5d} {_fmt(r['e_from_eV'], 8)} {_fmt(r['e_to_eV'], 8)} "
            f"{_fmt(r['de_eV'], 7)} {_fmt(r['daq_pause_s'], 6)} "
            f"{_fmt(r['feespec_s'], 5)} {_fmt(r['k_request_s'], 7)} "
            f"{_fmt(r['feespec_check_s'], 8)} {_fmt(r['daq_resume_s'], 6)} "
            f"{_fmt(r['dccm_s'], 6)} {_fmt(r['total_s'], 7)}")

    # skip step 1: it starts from wherever K was before the scan
    by_de = {}
    for r in rows[1:]:
        by_de.setdefault(abs(r['de_eV']), []).append(r)
    if by_de:
        lines += ["", "by |dE|:   k_move mean+-sd    total mean+-sd    n"]
        for de in sorted(by_de):
            k = _mean_sd([r['k_request_s'] for r in by_de[de]])
            t = _mean_sd([r['total_s'] for r in by_de[de]])
            lines.append(f"{de:7.1f} eV  {k}     {t}   {len(by_de[de]):3d}")
    return "\n".join(lines)


def write_csv(rows, run_number, exp):
    """Write rows to the experiment results folder, falling back to home."""
    name = f"run{int(run_number):04d}_timing.csv"
    candidates = []
    if exp:
        candidates.append(
            Path(f"/sdf/data/lcls/ds/mfx/{exp}/results/undulator_timing"))
    candidates.append(Path(os.path.expanduser("~/undulator_timing")))
    for folder in candidates:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / name
            with open(path, 'w', newline='') as f:
                w = csv.DictWriter(f, fieldnames=COLUMNS)
                w.writeheader()
                w.writerows(rows)
            return path
        except OSError as e:
            logger.warning(f"Could not write {folder}: {e}")
    return None


def report(timer, run_number, post=True):
    """Print table, write CSV, and post to elog. Never raises."""
    try:
        exp = None
        try:
            from mfx.macros import get_exp
            exp = get_exp()
        except Exception as e:
            logger.warning(f"get_exp failed: {e}")
        table = format_table(timer.rows, run_number, timer.mode)
        path = write_csv(timer.rows, run_number, exp)
        msg = table + (f"\n\ncsv: {path}" if path else "\n\ncsv: not written")
        print("\n" + msg + "\n")
        if post:
            from mfx.db import elog
            elog.post(msg=msg, tags='undulator_timing',
                      run=run_number)
        return msg
    except Exception as e:
        logger.error(f"Timing report failed: {e}")
        return None
