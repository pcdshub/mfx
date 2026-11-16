"""
Per-step timing for undulator K scans (k_xas_scan).

Records wall-clock stamps for each K request so step time can be split
into photon-side overhead and undulator time, then writes a CSV and
posts a plain-text table to the elog at the end of each run.

Stamps are time.time() on the hutch-python host. EPICS timestamps from
epicsArch are the primary record; these are a cross-check.

Also here: the K request hand-shake (request_k blocks; request_k_async
returns a KWatch so a scan can take data while K moves), the precomputed
ACR energy list and the grids built on it, a per-DCCM-point log for fly
scans, and a read-only snapshot of the girder dead band.
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

# one row per DCCM point (write_points_csv). done_at_* = done PV (AO805)
# value at dwell start and end: 0 means K was still moving
POINT_COLUMNS = [
    'run', 'step', 'point', 'k_target_eV', 'dccm_eV', 'offset_eV',
    't_k_write', 't_dccm_start', 't_dccm_done', 't_dwell_start',
    't_dwell_end', 'done_at_dwell_start', 'done_at_dwell_end', 't_k_done',
]

SLOW_STEP_WARN_S = 60.0
# highest K request (SET2, eV) ACR allows; last known cap (10-26 shift)
# until set_acr_list(k_max=...) replaces it. Applied by the list helpers
# below and by request_k(k_max=...), not by request_k itself
K_MAX_EV = 7124.0
# SET2 within this of the target counts as already requested
K_SAME_EV = 0.05
# done PV must read 1 this long after the last request finished before the
# next SET2 write; a write that lands earlier can be dropped by the listener
K_READY_S = 2.0
# a write the listener acts on drops the done PV to 0 within this time
K_START_S = 20.0
# k_move under this is a null request (no girder moved): 7.0 s median for
# null requests against 11.2 s for real steps on 10-26
NULL_S = 9.0
# real step over this has a stage-2 tail; 0.125 um steps take 16-18 s
SLOW_S = 15.0
# end of the last K request seen by request_k or KWatch.wait, for the
# K_READY_S hold-off. 'seen' is True only when one of them watched that
# request finish; otherwise
# (first call, interrupted move, request from elsewhere) the hold-off is
# counted from when the done PV is next seen at 1.
_last_done = {'t': 0.0, 'seen': False}


def _wait_done(done, ok, what, warn_s):
    t_warn = time() + warn_s
    while done.get() != ok:
        sleep(0.05)
        if time() > t_warn:
            logger.warning(f"{what} still not done after {warn_s:.0f} s. Ctrl+C, "
                           f"caget SIOC:SYS0:ML07:AO805, call ACR.")
            t_warn += warn_s


def _wait_ready(done, ok, warn_s):
    """Block until the done PV has read 1 continuously for K_READY_S."""
    since = _last_done['t'] if _last_done['seen'] else None
    t_warn = time() + warn_s
    while True:
        if done.get() == ok:
            if since is None:
                since = time()
            if time() - since >= K_READY_S:
                return
        else:
            # busy again, restart the hold-off once it reads 1
            since = None
            if time() > t_warn:
                logger.warning(f"previous K request still not done after "
                               f"{warn_s:.0f} s. Ctrl+C, caget "
                               f"SIOC:SYS0:ML07:AO805, call ACR.")
                t_warn += warn_s
        sleep(0.05)


def request_k(positioner, target_eV, wait=True, start_s=None,
              warn_s=SLOW_STEP_WARN_S, k_max=None, on_no_ack='raise'):
    """
    Write a K request to a BeamEnergyRequestACRWait and wait for the done PV.

    ophyd's move() finishes only on a 0 -> 1 edge of the done PV, so it
    blocks forever when the listener never starts: a request equal to the
    current SET2 (no change for the listener to see), or a write that lands
    while the listener is still finishing the last move. Here:

    - a target above k_max (eV, None = no limit) raises ValueError, not sent;
    - a target already in SET2 (within K_SAME_EV) is not sent again; with
      wait=True it still waits for the done PV, in case the earlier request
      is still moving;
    - the write waits until the done PV has read 1 for K_READY_S;
    - if the done PV does not leave 1 within start_s (K_START_S) of the
      write, the request was not acknowledged (dropped write, listener
      stopped). on_no_ack='raise' (default) raises RuntimeError;
      'warn' logs and returns, for operators who confirm K by other means;
    - once the PV has gone to 0, no timeout. A warning prints every warn_s;
      Ctrl+C stops.

    Returns seconds from the write (or from the call, for a repeated target)
    to done. With wait=False, seconds to dispatch the write.
    """
    start_s = K_START_S if start_s is None else start_s
    if on_no_ack not in ('raise', 'warn'):
        raise ValueError(f"on_no_ack must be 'raise' or 'warn', not {on_no_ack!r}")
    if k_max is not None and target_eV > k_max + 1e-6:
        raise ValueError(f"K request {target_eV:.1f} eV above k_max "
                         f"{k_max:.1f} eV, not sent")
    done = getattr(positioner, 'done', None)
    ok = getattr(positioner, 'done_value', 1)
    current = positioner.setpoint.get()
    if abs(current - target_eV) < K_SAME_EV:
        logger.warning(f"K request already {current:.1f} eV, not sent")
        if done is None or not wait:
            return 0.0
        t0 = time()
        _wait_done(done, ok, f"K request to {current:.1f} eV", warn_s)
        return time() - t0
    if done is None or not wait:
        t0 = time()
        positioner.move(target_eV, wait=wait)
        return time() - t0
    _wait_ready(done, ok, warn_s)

    left_done = threading.Event()

    def _seen(value=None, **kwargs):
        if value != ok:
            left_done.set()

    # subscribe before the write so a fast 1 -> 0 -> 1 is not missed
    cid = done.subscribe(_seen, run=False)
    _last_done['seen'] = False
    try:
        positioner.setpoint.put(target_eV, wait=True)
        t0 = time()
        while not left_done.wait(0.05) and done.get() == ok:
            if time() - t0 > start_s:
                msg = (f"AO805 stayed 1 for {start_s:.0f} s after the K request "
                       f"to {target_eV:.1f} eV; the listener did not act on "
                       f"it. Check K with ACR before taking data.")
                if on_no_ack == 'raise':
                    raise RuntimeError(msg)
                logger.warning(msg)
                return time() - t0
        _wait_done(done, ok, f"K request to {target_eV:.1f} eV", warn_s)
        _last_done['seen'] = True
    finally:
        done.unsubscribe(cid)
        _last_done['t'] = time()
    return time() - t0


class KWatch:
    """
    One K request in flight, returned by request_k_async().

    Subscribes to the done PV before the SET2 write and stamps its edges
    as they arrive, so a request that finishes while the caller is busy
    (DCCM points in a fly scan) still gets its times:

    - t_write: time.time() just after the SET2 write (nan for a repeat);
    - t_ack: first done 1 -> 0 after the write (the listener took it);
    - t_done: first done 0 -> 1 after t_ack.

    repeat=True: SET2 already held the target, nothing was written and
    wait() only waits for the done PV to read 1. A positioner without a
    done signal (simulation) gives a watch whose wait() returns 0.0 at once.
    """

    def __init__(self, positioner, target_eV, repeat=False,
                 warn_s=SLOW_STEP_WARN_S):
        self.positioner = positioner
        self.target_eV = target_eV
        self.repeat = repeat
        self.warn_s = warn_s
        self.t_write = np.nan
        self.t_ack = np.nan
        self.t_done = np.nan
        self._done = getattr(positioner, 'done', None)
        self._ok = getattr(positioner, 'done_value', 1)
        self._lock = threading.Lock()
        self._finished = threading.Event()
        self._cid = None

    def _subscribe(self):
        self._cid = self._done.subscribe(self._seen, run=False)

    def _seen(self, value=None, **kwargs):
        self._edge(value, time())

    def _edge(self, value, t):
        # called from the CA thread (subscription) and from wait() (polling)
        if value is None:
            return
        with self._lock:
            if value != self._ok:
                if np.isnan(self.t_ack):
                    self.t_ack = t
            elif not np.isnan(self.t_ack) and np.isnan(self.t_done):
                self.t_done = t
                self._finished.set()

    def _poll(self):
        # backs up the subscription in case a monitor update is late; a
        # done=1 read taken before the ack was seen is not a completion
        acked = self.acked()
        v = self.state()
        if v is None or (v == self._ok and not acked):
            return
        self._edge(v, time())

    def state(self):
        """Done PV value now; None without a done signal or if the read fails."""
        if self._done is None:
            return None
        try:
            return self._done.get()
        except Exception:
            return None

    def acked(self):
        """True once the done PV has left 1 after the write."""
        return not np.isnan(self.t_ack)

    def finished(self):
        """True once the request is done (done PV 0 -> 1 after the ack)."""
        if self._done is None:
            return True
        if self.repeat:
            return self.state() == self._ok
        return not np.isnan(self.t_done)

    def wait(self, warn_s=None, start_s=None, on_no_ack='raise'):
        """
        Block until the request is done. Returns seconds from write to done.

        If the done PV has not left 1 within start_s (K_START_S at call time
        when None) of the write, the listener did not act on it:
        on_no_ack='raise' (default) raises RuntimeError, 'warn' logs and
        returns nan. A repeat waits for the done PV to read 1 and returns
        nan. Once acknowledged there is no timeout; a warning prints every
        warn_s (the watch's warn_s when None) and Ctrl+C stops. On success
        the K_READY_S hold-off for the next write counts from t_done, as
        after request_k(). Always drops the subscription.
        """
        warn_s = self.warn_s if warn_s is None else warn_s
        start_s = K_START_S if start_s is None else start_s
        try:
            if on_no_ack not in ('raise', 'warn'):
                raise ValueError(f"on_no_ack must be 'raise' or 'warn', not {on_no_ack!r}")
            if self._done is None:
                return np.nan if self.repeat else 0.0
            if self.repeat:
                _wait_done(self._done, self._ok,
                           f"K request to {self.target_eV:.1f} eV", warn_s)
                return np.nan
            while not self.acked():
                self._poll()
                if self.acked():
                    break
                if time() - self.t_write > start_s:
                    msg = (f"AO805 stayed 1 for {start_s:.0f} s after the K request "
                           f"to {self.target_eV:.1f} eV; the listener did not act "
                           f"on it. Check K with ACR before taking data.")
                    if on_no_ack == 'raise':
                        raise RuntimeError(msg)
                    logger.warning(msg)
                    return np.nan
                sleep(0.05)
            t_warn = time() + warn_s
            while not self._finished.wait(0.05):
                self._poll()
                if time() > t_warn:
                    logger.warning(f"K request to {self.target_eV:.1f} eV still not "
                                   f"done after {warn_s:.0f} s. Ctrl+C, caget "
                                   f"SIOC:SYS0:ML07:AO805, call ACR.")
                    t_warn += warn_s
            _last_done['t'] = self.t_done
            _last_done['seen'] = True
            return self.t_done - self.t_write
        finally:
            self.close()

    def close(self):
        """Drop the done PV subscription. Safe to call more than once."""
        with self._lock:
            cid, self._cid = self._cid, None
        if cid is not None and self._done is not None:
            try:
                self._done.unsubscribe(cid)
            except Exception as e:
                logger.warning(f"done PV unsubscribe failed: {e}")


def request_k_async(positioner, target_eV, k_max=None,
                    warn_s=SLOW_STEP_WARN_S):
    """
    Write a K request without waiting for the move. Returns a KWatch.

    Same hand-shake as request_k() up to the write: a target above k_max
    (eV, None = no limit) raises ValueError, not sent; a target already in
    SET2 (within K_SAME_EV) is not sent and the watch has repeat=True;
    otherwise the write waits until the done PV has read 1 for K_READY_S
    after the previous request, which is what keeps a scan from running
    ahead of the undulator. The done PV subscription starts before the
    write so a fast 1 -> 0 -> 1 is not missed.

    Call watch.wait() before the next K request: it checks the
    acknowledgement, returns the step time and starts the hold-off.
    """
    if k_max is not None and target_eV > k_max + 1e-6:
        raise ValueError(f"K request {target_eV:.1f} eV above k_max "
                         f"{k_max:.1f} eV, not sent")
    done = getattr(positioner, 'done', None)
    current = positioner.setpoint.get()
    if abs(current - target_eV) < K_SAME_EV:
        logger.warning(f"K request already {current:.1f} eV, not sent")
        return KWatch(positioner, target_eV, repeat=True, warn_s=warn_s)
    watch = KWatch(positioner, target_eV, warn_s=warn_s)
    if done is None:
        positioner.move(target_eV, wait=False)
        watch.t_write = time()
        return watch
    _wait_ready(done, watch._ok, warn_s)
    watch._subscribe()
    _last_done['seen'] = False
    try:
        positioner.setpoint.put(target_eV, wait=True)
    except BaseException:
        watch.close()
        raise
    watch.t_write = time()
    return watch


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


# precomputed list ACR loads, (lo, hi, step) in requested eV. Last known
# list (10-26 shift: moved from 6970-7160 to 7064-7144 after the Fe foil
# edge turned up at 7080) until set_acr_list() puts in the one ACR
# confirms. Read it as ut.ACR_LIST_EV at call time; a name import goes stale
ACR_LIST_EV = (7064.0, 7144.0, 0.5)


def acr_list(lo=None, hi=None, step=None):
    """
    Every energy on the precomputed ACR list, eV, rounded to 0.1.

    lo, hi, step left at None come from ACR_LIST_EV at call time, so the
    list set by set_acr_list() is the default.
    """
    lo = ACR_LIST_EV[0] if lo is None else lo
    hi = ACR_LIST_EV[1] if hi is None else hi
    step = ACR_LIST_EV[2] if step is None else step
    n = int(round((hi - lo) / step))
    return np.round(lo + step * np.arange(n + 1), 1)


def set_acr_list(lo, hi, step, k_max=None):
    """
    Replace the precomputed ACR list and, if k_max is given, the K cap.

    Use the range, step and highest K that ACR confirms are loaded. Every
    helper here reads ACR_LIST_EV and K_MAX_EV at call time, so grids built
    after this call are checked against the new list. Raises ValueError,
    changing nothing, unless lo < hi, step > 0, hi - lo is a whole number
    of steps and k_max >= lo. Returns (lo, hi, step, K_MAX_EV).
    """
    global ACR_LIST_EV, K_MAX_EV
    lo, hi, step = float(lo), float(hi), float(step)
    if not lo < hi:
        raise ValueError(f"ACR list low end {lo:.1f} eV must be below the "
                         f"high end {hi:.1f} eV")
    if not step > 0:
        raise ValueError(f"ACR list step must be > 0 eV, not {step}")
    n = (hi - lo) / step
    if abs(n - round(n)) > 1e-6:
        raise ValueError(f"{lo:.1f}-{hi:.1f} eV is not a whole number of "
                         f"{step:g} eV steps")
    if k_max is not None:
        k_max = float(k_max)
        if not k_max >= lo:
            raise ValueError(f"k_max {k_max:.1f} eV below the list low end "
                             f"{lo:.1f} eV")
    ACR_LIST_EV = (lo, hi, step)
    if k_max is not None:
        K_MAX_EV = k_max
    logger.warning(f"ACR list now {lo:.1f}-{hi:.1f} eV in {step:g} eV steps "
                   f"({int(round(n)) + 1} points), K cap {K_MAX_EV:.1f} eV")
    if K_MAX_EV < lo:
        logger.warning(f"K cap {K_MAX_EV:.1f} eV is below the list low end; "
                       f"every grid will fail check_on_list. Pass k_max.")
    return lo, hi, step, K_MAX_EV


def check_on_list(positions, allowed=None):
    """
    Raise ValueError if any position is off the precomputed ACR list or
    above K_MAX_EV.

    The listener only has phase-shifter and balancing solutions for listed
    energies, so an off-list request falls back to the slow path or fails.
    Returns the positions rounded to 0.1 eV.
    """
    allowed = acr_list() if allowed is None else np.round(allowed, 1)
    pos = np.round(np.asarray(positions, dtype=float), 1)
    bad = sorted(set(pos[~np.isin(pos, allowed)].tolist()))
    if bad:
        raise ValueError(f"{len(bad)} positions off the ACR list: {bad[:10]}")
    high = sorted(set(pos[pos > K_MAX_EV].tolist()))
    if high:
        raise ValueError(f"{len(high)} positions above K_MAX_EV {K_MAX_EV:.1f} eV: "
                         f"{high[:10]}")
    return pos


def grid(lo, hi, step):
    """
    Ascending positions lo..hi, checked against the ACR list.

    hi is included when (hi - lo) is a whole number of steps; otherwise the
    grid stops at the last step below hi, so it never passes hi.
    """
    n = int(np.floor((hi - lo) / step + 1e-6))
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


def window_ladder(start_eV=None, lo=None, hi=None):
    """
    Step-size ladder that fits inside lo..hi, in visiting order.

    Up to five steps each of 0.5, 1, 5 and 25 eV going up (a size stops
    early rather than pass hi), up to five 100 eV steps alternating down
    and up (none when the window is under 100 eV), one move to the low
    end, then four full-window steps (60 eV for 7064-7124). Use with
    k_order='given'. start_eV and lo default to the low end of
    ACR_LIST_EV, hi to K_MAX_EV, both read at call time.
    """
    start_eV = ACR_LIST_EV[0] if start_eV is None else start_eV
    lo = ACR_LIST_EV[0] if lo is None else lo
    hi = K_MAX_EV if hi is None else hi
    e = [float(start_eV)]
    for s in (0.5, 1, 5, 25):
        for _ in range(5):
            if e[-1] + s > hi:
                break
            e.append(e[-1] + s)
    for i in range(5):
        nxt = e[-1] - 100 if i % 2 == 0 else e[-1] + 100
        if not lo <= nxt <= hi:
            break
        e.append(nxt)
    e.append(lo)
    for i in range(4):
        e.append(hi if i % 2 == 0 else lo)
    return check_on_list(e)


class StepTimer:
    """Collects one row per K step for a single DAQ run."""

    def __init__(self, mode, prev_eV=None):
        # prev_eV: SET2 in place at the start, so a pre-requested first
        # target gets de_eV 0 (a repeat, not a null request)
        self.mode = mode
        self.rows = []
        self._row = None
        self._prev_eV = None if prev_eV is None else round(float(prev_eV), 1)

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

    def set_last(self, key, value):
        """
        Set a field of the last finished row, for stamps that arrive after
        end_step() (the K done in concurrent mode). Goes to the open row
        instead if end_step() has not been called yet; no-op without rows.
        """
        row = self._row if self._row is not None else (
            self.rows[-1] if self.rows else None)
        if row is not None:
            row[key] = value

    def timed_k_request(self, positioner, target_eV, **kwargs):
        """request_k() with SET2-write and done stamps for this step."""
        spent = request_k(positioner, target_eV, **kwargs)
        t1 = time()
        self.set('t_k_request', t1 - spent)
        # wait=False returns at dispatch, so there is no done stamp to record
        if kwargs.get('wait', True):
            self.set('t_k_done', t1)
            self.set('k_request_s', spent)
        return spent

    def timed_k_request_async(self, positioner, target_eV, **kwargs):
        """
        request_k_async() with the SET2-write stamp for this step. Returns
        the KWatch; after watch.wait() put t_k_done and k_request_s in
        with set_last().
        """
        watch = request_k_async(positioner, target_eV, **kwargs)
        self.set('t_k_request', watch.t_write)
        return watch

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


def _timed_s(row):
    """k_request_s of a row that counts as a timed K request, else None."""
    try:
        k = float(row.get('k_request_s', np.nan))
    except (TypeError, ValueError):
        return None
    if np.isnan(k):
        return None
    # same target as the previous step: nothing was sent, not a request
    if row.get('de_eV') == 0:
        return None
    return k


def _flag(row, null_s, slow_s):
    k = _timed_s(row)
    if k is None:
        return ''
    if k < null_s:
        return 'null'
    if k > slow_s:
        return 'slow'
    return ''


def summarize(rows, null_s=NULL_S, slow_s=SLOW_S):
    """
    Step-time summary of one run (StepTimer.rows), from k_request_s.

    A row is timed when k_request_s is a number and the step is not a
    repeat of the previous target (de_eV 0, nothing sent); nan rows (fly
    step not finished, no ack with on_no_ack='warn') are not timed. A timed
    row under null_s (s) is a null request (no girder moved), the rest are
    real steps, and a real step over slow_s is slow (stage-2 tail).

    Returns a dict: n_steps, n_timed, n_null, leading_null (nulls in a row
    from the first timed row), n_real, median_real, p90_real, max_real
    (s, nan without real steps) and n_slow.
    """
    timed = [k for k in (_timed_s(r) for r in rows) if k is not None]
    real = np.array([k for k in timed if k >= null_s], dtype=float)
    leading = 0
    for k in timed:
        if k >= null_s:
            break
        leading += 1
    has_real = real.size > 0
    return dict(
        n_steps=len(rows),
        n_timed=len(timed),
        n_null=len(timed) - int(real.size),
        leading_null=leading,
        n_real=int(real.size),
        median_real=float(np.median(real)) if has_real else np.nan,
        p90_real=float(np.percentile(real, 90)) if has_real else np.nan,
        max_real=float(real.max()) if has_real else np.nan,
        n_slow=int(np.sum(real > slow_s)),
    )


def _summary_text(s, null_s, slow_s):
    if not s['n_timed']:
        return f"k_move: no timed steps of {s['n_steps']}"
    line = (f"k_move: {s['n_timed']} of {s['n_steps']} steps timed, "
            f"{s['n_null']} null ({s['leading_null']} leading), "
            f"{s['n_real']} real")
    if s['n_real']:
        line += (f": median {s['median_real']:.1f} s, p90 "
                 f"{s['p90_real']:.1f} s, max {s['max_real']:.1f} s, "
                 f"{s['n_slow']} slow")
    return line + f". null < {null_s:g} s, slow > {slow_s:g} s."


def format_table(rows, run_number, mode):
    """
    Plain-text per-step table plus mean +- sd per step size.

    The flag column marks null requests (k_move < NULL_S) and slow real
    steps (> SLOW_S); the line under the table is summarize().
    """
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
        "resume   dccm   total  flag",
    ]
    for r in rows:
        lines.append(
            f"{r['step']:5d} {_fmt(r['e_from_eV'], 8)} {_fmt(r['e_to_eV'], 8)} "
            f"{_fmt(r['de_eV'], 7)} {_fmt(r['daq_pause_s'], 6)} "
            f"{_fmt(r['feespec_s'], 5)} {_fmt(r['k_request_s'], 7)} "
            f"{_fmt(r['feespec_check_s'], 8)} {_fmt(r['daq_resume_s'], 6)} "
            f"{_fmt(r['dccm_s'], 6)} {_fmt(r['total_s'], 7)}  "
            f"{_flag(r, NULL_S, SLOW_S)}".rstrip())
    lines += ["", _summary_text(summarize(rows, NULL_S, SLOW_S),
                                NULL_S, SLOW_S)]

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


def _csv_folders(exp):
    """Folders the CSVs go to, in the order tried."""
    candidates = []
    if exp:
        candidates.append(
            Path(f"/sdf/data/lcls/ds/mfx/{exp}/results/undulator_timing"))
    candidates.append(Path(os.path.expanduser("~/undulator_timing")))
    return candidates


def _write_rows(rows, name, columns, exp, extrasaction='raise'):
    for folder in _csv_folders(exp):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / name
            with open(path, 'w', newline='') as f:
                w = csv.DictWriter(f, fieldnames=columns,
                                   extrasaction=extrasaction)
                w.writeheader()
                w.writerows(rows)
            return path
        except OSError as e:
            logger.warning(f"Could not write {folder}: {e}")
    return None


def write_csv(rows, run_number, exp):
    """Write rows to the experiment results folder, falling back to home."""
    return _write_rows(rows, f"run{int(run_number):04d}_timing.csv",
                       COLUMNS, exp)


def write_points_csv(rows, run_number, exp):
    """
    Write per-DCCM-point rows (POINT_COLUMNS) as runNNNN_points.csv in the
    same folder as the timing CSV (same fallback to home). Returns the
    path, or None if no folder was writable.
    """
    return _write_rows(rows, f"run{int(run_number):04d}_points.csv",
                       POINT_COLUMNS, exp, extrasaction='ignore')


def _points_text(points):
    """One line: DCCM points taken with K moving (done PV 0) vs settled."""
    moving = settled = 0
    for p in points:
        try:
            v = float(p.get('done_at_dwell_start', np.nan))
        except (TypeError, ValueError):
            v = np.nan
        if v == 1:
            settled += 1
        elif not np.isnan(v):
            moving += 1
    line = (f"points: {len(points)} DCCM points, {moving} in move (done PV 0 "
            f"at dwell start), {settled} settled")
    unknown = len(points) - moving - settled
    if unknown:
        line += f", {unknown} without a done PV reading"
    return line


def report(timer, run_number, post=True, write=True, points=None):
    """
    Print table, write CSV (write=True), and post to elog (post=True).

    Pass write=False for simulated or unrecorded scans: their run numbers
    are not real and the CSV would overwrite a real run's file. points:
    one row per DCCM point (POINT_COLUMNS); adds a line counting points
    taken while K was moving (done PV 0 at dwell start) and settled, and
    with write=True also writes runNNNN_points.csv. Never raises.
    """
    try:
        exp = None
        try:
            from mfx.macros import get_exp
            exp = get_exp()
        except Exception as e:
            logger.warning(f"get_exp failed: {e}")
        table = format_table(timer.rows, run_number, timer.mode)
        path = write_csv(timer.rows, run_number, exp) if write else None
        msg = table + (f"\n\ncsv: {path}" if path else "\n\ncsv: not written")
        if points:
            ppath = write_points_csv(points, run_number, exp) if write else None
            msg += "\n" + _points_text(points)
            msg += (f"\npoints csv: {ppath}" if ppath
                    else "\npoints csv: not written")
        print("\n" + msg + "\n")
        if post:
            from mfx.db import elog
            elog.post(msg=msg, tags='undulator_timing',
                      run=run_number)
        return msg
    except Exception as e:
        logger.error(f"Timing report failed: {e}")
        return None


# girder dead band setting, one PV per undulator segment. Read-only here:
# ACR / undulator controls set it, hutch python only records it
DEADBAND_PV = 'USEG:UNDH:{seg}50:DeadbandHgEnc'
# every segment number is tried and the ones that answer are reported;
# the 10-26 report counts 34 of these PVs
DEADBAND_SEGMENTS = tuple(range(13, 48))


def _as_float(v):
    if v is None:
        return None
    try:
        a = np.asarray(v, dtype=float).ravel()
    except (TypeError, ValueError):
        return None
    if not a.size or np.isnan(a[0]):
        return None
    return float(a[0])


def _caget_all(epics, pvs, timeout):
    many = getattr(epics, 'caget_many', None)
    if many is not None:
        # older pyepics has no timeout keyword on caget_many
        for kw in ({'timeout': timeout}, {}):
            try:
                values = many(pvs, **kw)
            except TypeError:
                continue
            except Exception as e:
                logger.warning(f"caget_many failed, reading one PV at a time: {e}")
                break
            if values is not None and len(values) == len(pvs):
                return list(values)
            break
    values = []
    for pv in pvs:
        try:
            values.append(epics.caget(pv, timeout=timeout))
        except Exception:
            values.append(None)
    return values


def read_deadband(segments=DEADBAND_SEGMENTS, timeout=1.0):
    """
    Read DeadbandHgEnc on each segment. Returns {segment: value or None}.

    None = the PV did not answer within timeout (s). Values are as served
    by the PV (um per undulator controls). Uses epics.caget_many when
    pyepics has it, else caget per PV. Never writes and never raises:
    returns {} if pyepics is missing or the read fails as a whole.
    """
    try:
        import epics
    except Exception as e:
        logger.warning(f"dead band not read, pyepics not available: {e}")
        return {}
    try:
        segs = [int(s) for s in segments]
        pvs = [DEADBAND_PV.format(seg=s) for s in segs]
        values = _caget_all(epics, pvs, timeout)
        return {s: _as_float(v) for s, v in zip(segs, values)}
    except Exception as e:
        logger.warning(f"dead band read failed: {e}")
        return {}


def deadband_text(values):
    """
    One line from read_deadband(), e.g. 'dead band 0.125 um on 32 segments
    (min 0.125, max 0.125), 3 not readable'. The headline value is the
    median, marked as such when the segments differ.
    """
    if not values:
        return "dead band not read (pyepics missing or no segments)"
    ok = np.array([v for v in values.values() if v is not None], dtype=float)
    n_bad = len(values) - ok.size
    if not ok.size:
        return f"dead band not readable on any of {len(values)} segments"
    lo, hi = ok.min(), ok.max()
    med = float(np.median(ok))
    line = (f"dead band {med:g} um{'' if lo == hi else ' median'} on "
            f"{ok.size} segments (min {lo:g}, max {hi:g})")
    if n_bad:
        line += f", {n_bad} not readable"
    return line
