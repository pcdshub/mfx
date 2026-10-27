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
from time import sleep, time

import numpy as np

logger = logging.getLogger(__name__)

COLUMNS = [
    'step', 'e_from_eV', 'e_to_eV', 'de_eV', 'mode',
    't_step_start', 't_k_request', 't_k_done', 't_dwell_start',
    'daq_pause_s', 'feespec_s', 'k_request_s', 'feespec_check_s',
    'daq_resume_s', 'dccm_s', 'total_s',
]

SLOW_STEP_WARN_S = 60.0
# SET2 within this of the target counts as already requested
K_SAME_EV = 0.05
# done PV must read 1 this long after the last request finished before the
# next SET2 write; a write that lands earlier can be dropped by the listener
K_READY_S = 2.0
# a write the listener acts on drops the done PV to 0 within this time
K_START_S = 20.0
# end of the last K request seen by request_k, for the K_READY_S hold-off
_last_done = {'t': 0.0}


def _wait_done(done, ok, what, warn_s):
    t_warn = time() + warn_s
    while done.get() != ok:
        sleep(0.05)
        if time() > t_warn:
            logger.warning(f"{what} still not done after {warn_s:.0f} s. Ctrl+C, "
                           f"caget SIOC:SYS0:ML07:AO805, call ACR.")
            t_warn += warn_s


def _wait_ready(done, ok, warn_s):
    """Block until the done PV reads 1 and has done so for K_READY_S."""
    while True:
        _wait_done(done, ok, "previous K request", warn_s)
        rest = K_READY_S - (time() - _last_done['t'])
        if rest <= 0:
            return
        sleep(rest)
        if done.get() == ok:
            return


def request_k(positioner, target_eV, wait=True, start_s=None,
              warn_s=SLOW_STEP_WARN_S):
    """
    Write a K request to a BeamEnergyRequestACRWait and wait for the done PV.

    ophyd's move() finishes only on a 0 -> 1 edge of the done PV, so it
    blocks forever when the listener never starts: a request equal to the
    current SET2 (no change for the listener to see), or a write that lands
    while the listener is still finishing the last move. Here:

    - a target already in SET2 (within K_SAME_EV) is not sent, returns 0;
    - the write waits until the done PV has read 1 for K_READY_S;
    - if the done PV does not leave 1 within start_s (K_START_S) of the
      write, the request counts as done, with a warning (listener idle, or
      nothing to move);
    - once the PV has gone to 0, no timeout. A warning prints every warn_s;
      Ctrl+C stops.

    Returns seconds from the write to done.
    """
    start_s = K_START_S if start_s is None else start_s
    current = positioner.setpoint.get()
    if abs(current - target_eV) < K_SAME_EV:
        logger.warning(f"K request already {current:.1f} eV, not sent")
        return 0.0
    done = getattr(positioner, 'done', None)
    if done is None or not wait:
        t0 = time()
        positioner.move(target_eV, wait=wait)
        return time() - t0
    ok = getattr(positioner, 'done_value', 1)
    _wait_ready(done, ok, warn_s)

    left_done = threading.Event()

    def _seen(value=None, **kwargs):
        if value != ok:
            left_done.set()

    # subscribe before the write so a fast 1 -> 0 -> 1 is not missed
    cid = done.subscribe(_seen, run=False)
    try:
        positioner.setpoint.put(target_eV, wait=True)
        t0 = time()
        while not left_done.wait(0.05) and done.get() == ok:
            if time() - t0 > start_s:
                logger.warning(
                    f"AO805 stayed 1 for {start_s:.0f} s after the K request to "
                    f"{target_eV:.1f} eV; taking it as done. If K did not move, "
                    f"ask ACR whether the listener is running.")
                return time() - t0
        _wait_done(done, ok, f"K request to {target_eV:.1f} eV", warn_s)
    finally:
        done.unsubscribe(cid)
        _last_done['t'] = time()
    return time() - t0


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


# precomputed list sent to ACR for the 2026-10-26 shift (requested eV)
ACR_LIST_EV = (6970.0, 7160.0, 0.5)


def acr_list(lo=ACR_LIST_EV[0], hi=ACR_LIST_EV[1], step=ACR_LIST_EV[2]):
    """Every energy on the precomputed ACR list, eV, rounded to 0.1."""
    n = int(round((hi - lo) / step))
    return np.round(lo + step * np.arange(n + 1), 1)


def check_on_list(positions, allowed=None):
    """
    Raise ValueError if any position is off the precomputed ACR list.

    The listener only has phase-shifter and balancing solutions for listed
    energies, so an off-list request falls back to the slow path or fails.
    Returns the positions rounded to 0.1 eV.
    """
    allowed = acr_list() if allowed is None else np.round(allowed, 1)
    pos = np.round(np.asarray(positions, dtype=float), 1)
    bad = sorted(set(pos[~np.isin(pos, allowed)].tolist()))
    if bad:
        raise ValueError(f"{len(bad)} positions off the ACR list: {bad[:10]}")
    return pos


def grid(lo, hi, step):
    """Ascending positions lo..hi inclusive, checked against the ACR list."""
    n = int(round((hi - lo) / step))
    return check_on_list(lo + step * np.arange(n + 1))


def sweep(lo, hi, step, cycles=1):
    """
    Up-and-down sweep lo -> hi -> lo, repeated `cycles` times, in visiting order.

    Each cycle ends where it started, so k_xas_scan makes no long return move
    when K sits at lo before the call. Interior points are visited twice per
    cycle from opposite directions, hi once. Use with k_order='given'.
    """
    up = list(grid(lo, hi, step))
    tri = up + up[-2::-1]
    e = tri + [x for _ in range(cycles - 1) for x in tri[1:]]
    return check_on_list(e)


def window_ladder(start_eV=6990.0, lo=ACR_LIST_EV[0], hi=ACR_LIST_EV[1]):
    """
    Step-size ladder that fits inside the ACR list window, in visiting order.

    Five steps each of 0.5, 1, 5 and 25 eV going up, five 100 eV steps
    alternating down and up, one move to the low end, then four full-window
    steps (190 eV for the 10-26 list). Use with k_order='given'.
    """
    e = [float(start_eV)]
    for s in (0.5, 1, 5, 25):
        for _ in range(5):
            e.append(e[-1] + s)
    for i in range(5):
        e.append(e[-1] - 100 if i % 2 == 0 else e[-1] + 100)
    e.append(lo)
    for i in range(4):
        e.append(hi if i % 2 == 0 else lo)
    return check_on_list(e)


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
        """request_k() with SET2-write and done stamps for this step."""
        spent = request_k(positioner, target_eV, **kwargs)
        t1 = time()
        self.set('t_k_request', t1 - spent)
        self.set('t_k_done', t1)
        self.set('k_request_s', spent)
        return spent

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
