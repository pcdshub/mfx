"""
Experiment mfx102095027, shift 2026-11-16 18:00 to 11-17 06:00.

Third undulator scanning night: girder dead band test with ACR, DCCM points
while the undulator moves (fly scan) on the Fe foil, then pink-beam
stochastic XANES on myoglobin microcrystals from the MESH (electrokinetic,
horizontal, XLJ). The 10-26 results this builds on are in the second shift
report; the shift plan PDF (shift_plan_20261116) gives the order of the
blocks and the decisions between them.

hutch-python loads this file when mfx102095027 is the active experiment and
exposes the User instance as `x` (and `user`). If another experiment is
active, load it by hand in mfx3 from the repo root:

    exec(open('experiments/102095027.py').read()); x = User()

Every method prints what it is about to do. Start with x.checklist_pre(),
x.status() and x.dry_run(). x.help() lists the methods in shift order.

The ACR list and K cap are read from mfx.undulator_timing at call time, so
x.acr_list_set(...) at 18:00 changes every grid built after it. Hutch python
never writes the dead band: ACR / undulator controls set it, x.deadband(um)
records the value they report, x.db_read() reads it back.
"""
import logging
import os
import time
from pathlib import Path

import numpy as np

import mfx.energy_calib as ec
import mfx.undulator_timing as ut
from mfx.undulator_timing import check_on_list, grid, request_k, sweep

logger = logging.getLogger(__name__)

EXP = 'mfx102095027'
SHIFT = '20261116'
TAG = 'shift_1116'
PREFIX = 'und1116'

# ---- energies ---------------------------------------------------------------
# real photon energy = K request + offset. 10-26: the real energy was 20 eV
# above the energy the machine reported (10-09 BLD gave -5.2 eV). Check it
# tonight (x.offset_check) before any DCCM-in scan; x.set_offset() updates it
REQ_OFFSET_EV = 20.0
# K request at the Fe foil edge on 10-26 (pink edge scans); x.set_edge()
EDGE_K_EV = 7080.0
# list asked of ACR before the shift: (lo, hi, step, highest K), requested eV.
# Until ACR confirms at 18:00 the module keeps the last known list (10-26:
# 7064-7144 eV in 0.5 eV, cap 7124 eV); x.acr_list_set() puts in the real one
ACR_LIST_REQUEST = (7040.0, 7160.0, 0.5, 7160.0)
# XRT image center and the range one image should hold, real eV
WINDOW_EV = (7080.0, 7155.0)
CENTER_EV = 7117.5
# FEE spectrometer crystal offset that centers the 7.1 keV spectrum
XRT_OFFSET_DEG = -1.3
XRT_NPX = 2048

# every K scan tonight runs concurrent_settled (fly scans: concurrent)
K_MODE = 'concurrent_settled'

# ---- SASE / XRT calibration (DCCM in) ------------------------------------------
# x.sase_cal(): K grid edge - 15 .. edge + 35 eV (the Mb sweep) in 10 eV; at
# each K the DCCM steps K-center +- 20 eV in 2 eV across the ~22 eV FWHM SASE
SASE_BELOW_EV = 15.0
SASE_ABOVE_EV = 35.0
SASE_K_STEP_EV = 10.0
SASE_HALF_EV = 20.0
SASE_DCCM_STEP_EV = 2.0
SASE_READ_S = 1.0               # IPM / GDET average per DCCM point
SASE_APPROACH_EV = 5.0          # approach move so every point is a real step
SASE_DIAG = 'dg2'               # ec.SIGNAL_PVS key or a PV name
# x.xrt_cal(): crystal rocked +- XRT_ROCK_DEG at each energy (xrt_tune uses
# 0.05 deg steps), line on the Zyla columns
XRT_CAL_N = 5
XRT_ROCK_DEG = 0.03
XRT_CAL_FRAMES = 5
DCCM_MOVE_S = 1.4               # 1 eV DCCM move, 10-09 timers

# ---- dead band test (19:00-21:00, with ACR) ----------------------------------
# 1 eV scans start this far below x.edge_k; 10 positions end at edge - 6, up
# and back = 19 visits, ~4 min at 12 s per step, ~6.5 min at 20 s
DB_START_BELOW_EV = 15.0
DB_N = 10
# concurrent_settled: a step takes max(dwell, K move); k_move is the measurement
DB_DWELL_S = 12.0
# pass rule, per scan leg: real-step median at most this, slow steps at most
# one per 40 timed steps, at most this many leading null requests, none after
DB_MEDIAN_MAX_S = 12.5
DB_LEADING_NULL_MAX = 1
# original band, restored at the 06:00 hand back when the energy GUI closes
DB_RESTORE_UM = 0.125

# ---- DCCM fly test (21:00-22:00) ----------------------------------------------
FLY_HALF_EV = 20.0              # K grid edge - 20 .. edge + 20 eV
FLY_STEP_EV = 5.0
FLY_N = 5
FLY_DWELL_S = 3.0
# F0 dwell counts from the K write: ~11 s K move + ~2 s XRT check leaves
# ~7 s at the new center with K settled
FLY_REF_DWELL_S = 20.0
# DCCM state readback (Beckhoff convention); confirm with cainfo at 17:00.
# insert()/remove() write :STATE:SET / :State:SET, see mfx/dccm.py
DCCM_STATE_RBV = 'SP1L0:DCCM:MMS:STATE:GET_RBV'

# ---- MESH myoglobin production -------------------------------------------------
MB_BELOW_EV = 15.0              # sweep edge - 15 .. edge + 35 eV
MB_ABOVE_EV = 35.0
MB_STEP_EV = 2.5
MB_DWELL_S = 30.0
MB_PARK_ABOVE_EV = 10.0
MB_PARK_DWELL_S = 900.0
# MESH high voltage: Acromag setpoint and readback in volts/1000
MESH_SP = 'MFX:USR:ao1:0'
MESH_RB = 'MFX:USR:ai1:1'
MESH_SCALE_V = 1000.0
MESH_MAX_KV = 5.0               # 3-5 kV operating range; the SED MESH lead sets it
DOOR_PV = 'PPS:FEH1:45:DOORA'   # the door watcher zeroes MESH_SP when it opens

# ---- transfocator (10-26 values; confirm the stack at 18:00) -------------------
TFS_LENSES = (4, 5, 6)          # legal without prefocus (December focus report)
TFS_R_UM = 58.8                 # effective radius of 04+05+06
TFS_E_EV = 7115.0               # center of the XANES window, real eV
TFS_Z_MM = 177.0                # expected waist at 7115 eV, -1.3 mm/eV
TFS_DOF_MM = 31.0
TFS_COARSE = np.arange(137.0, 218.1, 4.0)
# IP camera base PV; transfocator_aligner appends :IMAGE1:ArrayData.
# Unconfirmed: check before the shift which camera views the IP YAG.
IP_CAM = 'MFX:GIGE:LBL:01'

# ---- geometry calibrants --------------------------------------------------------
HC = 12398.42
# d spacings in Angstrom. LaB6 (a = 4.15692 A) was the calibrant on 10-26
# (the elog said silver behenate); AgBe kept for the long-spacing rings
LAB6_A = 4.15692
CALIBRANTS = {
    'LaB6': [LAB6_A / np.sqrt(h * h + k * k + l * l) for h, k, l in
             ((1, 0, 0), (1, 1, 0), (1, 1, 1), (2, 0, 0), (2, 1, 0),
              (2, 1, 1), (2, 2, 0), (3, 0, 0), (3, 1, 0), (3, 1, 1))],
    'AgBe': [58.38 / n for n in range(1, 13)],
}
JF16M_HALF_MM = 0.075 * 4400 / 2
JF16M_BEAMSTOP_MM = 10.0


# ---- helpers that need no hardware -------------------------------------------

def _ns(name):
    """Beamline object from the mfx3 namespace, falling back to mfx.beamline."""
    try:
        from IPython import get_ipython
        ip = get_ipython()
        if ip is not None and name in ip.user_ns:
            return ip.user_ns[name]
    except ImportError:
        pass
    import mfx.beamline as bl
    return getattr(bl, name)


def _results_dir():
    """Shift output folder in the experiment results area, else in home."""
    for folder in (Path(f'/sdf/data/lcls/ds/mfx/{EXP}/results/shift_{SHIFT}'),
                   Path(os.path.expanduser(f'~/shift_{SHIFT}'))):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            return folder
        except OSError as e:
            logger.warning(f'Cannot write {folder}: {e}')
    return Path('.')


def _post(msg, tag=TAG, run=None):
    print(msg)
    try:
        from mfx.db import elog
        elog.post(msg=msg, tags=tag, run=run)
    except Exception as e:
        logger.warning(f'elog post failed: {e}')


def _caget(pv, as_string=False, timeout=1.0):
    """caget that returns None instead of raising."""
    try:
        from epics import caget
        return caget(pv, as_string=as_string, timeout=timeout)
    except Exception as e:
        logger.warning(f'caget {pv} failed: {e}')
        return None


# XRT Zyla: left acquiring all night, nothing here starts or stops it
ZYLA_PV = 'XRT:ZYLA:CAM:01:Acquire'


def _door_closed():
    """True only when the hutch door PV reads 1 (closed)."""
    d = _caget(DOOR_PV)
    try:
        return d is not None and int(d) == 1
    except (TypeError, ValueError):
        return False


def _next_run(record):
    """Run number the next recorded scan gets, None when not recording."""
    if not record:
        return None
    try:
        from mfx.macros import get_run
        return get_run(station=0) + 1
    except Exception as e:
        logger.warning(f'get_run failed: {e}')
        return None


def list_bounds():
    """(lo, highest usable K, step) of the loaded ACR list, read at call time."""
    lo, hi, step = ut.ACR_LIST_EV
    return float(lo), float(min(hi, ut.K_MAX_EV)), float(step)


def fit_window(lo, hi, step, margin_steps=1):
    """
    Clip lo..hi (eV, K request) to the loaded list and K cap.

    Leaves margin_steps * step free below lo and above hi for the approach
    move, and snaps lo up to the list spacing. Returns (lo, hi). Raises
    ValueError when fewer than two positions are left.
    """
    l_lo, l_hi, l_step = list_bounds()
    margin = margin_steps * step
    lo2 = max(float(lo), l_lo + margin)
    lo2 = l_lo + np.ceil((lo2 - l_lo) / l_step - 1e-6) * l_step
    hi2 = min(float(hi), l_hi - margin)
    if hi2 - lo2 < step - 1e-6:
        raise ValueError(
            f"window {lo:.1f}-{hi:.1f} eV in {step:g} eV steps does not fit the "
            f"loaded list {l_lo:.1f}-{l_hi:.1f} eV (cap {ut.K_MAX_EV:.1f}) with "
            f"{margin:g} eV for the approach move; set x.edge_k or the list")
    return round(float(lo2), 1), round(float(hi2), 1)


def db_positions(edge_k, step=1.0, n=DB_N, direction='updown', start=None):
    """
    Dead band test grid. Returns (positions, approach K).

    n positions from start (default edge_k - 15 eV) in step eV, clipped to
    the list and cap (a warning when fewer than n are left). direction 'up',
    'down' or 'updown' (lo -> hi -> lo sweep). The approach K sits one step
    outside the first position, so step 1 is a real move (report rec 10).
    """
    if direction not in ('up', 'down', 'updown'):
        raise ValueError(f"direction must be 'up', 'down' or 'updown', not {direction!r}")
    start = edge_k - DB_START_BELOW_EV if start is None else float(start)
    lo, hi = fit_window(start, start + (n - 1) * step, step)
    up = list(grid(lo, hi, step))
    if len(up) < n:
        logger.warning(f"dead band grid clipped to {len(up)} of {n} positions "
                       f"({up[0]:.1f}-{up[-1]:.1f} eV) by the list or cap")
    if direction == 'up':
        pos, approach = up, up[0] - step
    elif direction == 'down':
        pos, approach = up[::-1], up[-1] + step
    else:
        pos, approach = list(sweep(lo, up[-1], step)), up[0] - step
    approach = float(check_on_list([approach])[0])
    return [float(p) for p in pos], approach


def fly_positions(edge_k, step=FLY_STEP_EV, lo=None, hi=None, reverse=False):
    """Fly test K grid edge - 20 .. edge + 20 eV, clipped. Returns (positions, approach)."""
    lo = edge_k - FLY_HALF_EV if lo is None else float(lo)
    hi = edge_k + FLY_HALF_EV if hi is None else float(hi)
    lo, hi = fit_window(lo, hi, step)
    up = [float(p) for p in grid(lo, hi, step)]
    if reverse:
        return up[::-1], float(check_on_list([up[-1] + step])[0])
    return up, float(check_on_list([up[0] - step])[0])


def fly_offsets(pattern='track', step=FLY_STEP_EV, n=FLY_N, going_up=True):
    """
    DCCM offsets in real eV from the new K center, in the order taken.

    'track': from the old center to the new one, spacing step/n: -4, -3,
    -2, -1, 0 for a +5 eV step and n=5; the signs flip going down.
    'center': 1 eV spacing centered on the new K center: -2..+2 for n=5.
    Add x.offset_eV to get offsets from the K request (what k_xas_scan
    takes).
    """
    if pattern == 'track':
        d = step / n
        off = [-(n - 1 - i) * d for i in range(n)]
        if not going_up:
            off = [-o for o in off]
    elif pattern == 'center':
        half = (n - 1) / 2.0
        off = [i - half for i in range(n)]
    else:
        raise ValueError(f"pattern must be 'track' or 'center', not {pattern!r}")
    return [round(float(o), 3) + 0.0 for o in off]


def mb_positions(edge_k, step=MB_STEP_EV):
    """Production sweep edge - 15 -> edge + 35 -> edge - 15 eV, clipped to list and cap."""
    lo, hi = fit_window(edge_k - MB_BELOW_EV, edge_k + MB_ABOVE_EV, step,
                        margin_steps=0)
    return [float(p) for p in sweep(lo, hi, step)]


def split_legs(rows):
    """
    Split timing rows where the scan direction turns (sign of de_eV).

    The first row of each leg is where null requests can pile up: after the
    approach move, and after the turnaround of a sweep.
    """
    legs, cur, sign = [], [], 0
    for r in rows:
        de = r.get('de_eV', np.nan)
        s = 0 if de is None or not np.isfinite(de) or de == 0 else int(np.sign(de))
        if s and sign and s != sign and cur:
            legs.append(cur)
            cur = []
        if s:
            sign = s
        cur.append(r)
    if cur:
        legs.append(cur)
    return legs


def db_verdict(rows):
    """
    Dead band pass rule on one scan's timing rows (StepTimer.rows).

    Per leg: real-step median <= 12.5 s, slow real steps (> ut.SLOW_S) at
    most one per 40 timed steps (one on a shorter leg), leading null requests <= 1 and no null
    request after them. Returns (passed, list of leg summaries, text).
    """
    legs = [ut.summarize(leg) for leg in split_legs(rows)] if rows else []
    if not legs or not sum(s['n_timed'] for s in legs):
        return False, legs, "no timed steps: cannot judge the dead band"
    problems = []
    for i, s in enumerate(legs, 1):
        if not s['n_real']:
            problems.append(f"leg {i}: no real steps")
            continue
        if s['median_real'] > DB_MEDIAN_MAX_S:
            problems.append(f"leg {i}: median {s['median_real']:.1f} s > "
                            f"{DB_MEDIAN_MAX_S:g} s")
        # one slow step allowed per 40 timed, and one on a shorter leg
        allowed = max(1, s['n_timed'] // 40)
        if s['n_slow'] > allowed:
            problems.append(f"leg {i}: {s['n_slow']} slow steps (> {ut.SLOW_S:g} s)")
        if s['leading_null'] > DB_LEADING_NULL_MAX:
            problems.append(f"leg {i}: {s['leading_null']} leading null requests")
        late = s['n_null'] - s['leading_null']
        if late > 0:
            problems.append(f"leg {i}: {late} null requests after the start")
    text = "; ".join(
        f"leg {i}: {s['n_real']} real, median {s['median_real']:.1f} s, "
        f"{s['n_slow']} slow, {s['n_null']} null ({s['leading_null']} leading)"
        for i, s in enumerate(legs, 1) if s['n_timed'])
    passed = not problems
    return passed, legs, ("PASS: " if passed else "FAIL: ") + (
        text if passed else "; ".join(problems) + ". " + text)


def spec_window(px_a, e_a, px_b, e_b, n_px=XRT_NPX, window=WINDOW_EV):
    """
    Energy range of one spectrometer image from two calibration points.

    px_a, px_b are the spectrum centroids in pixels measured with the DCCM at
    e_a, e_b (real eV). Prints eV/px, the energy at both image edges and
    whether `window` fits with 5% margin on each side. Returns (ev_per_px,
    e_at_px0, e_at_last_px).
    """
    slope = (e_b - e_a) / (px_b - px_a)
    e0 = e_a - slope * px_a
    e1 = e0 + slope * (n_px - 1)
    lo, hi = min(e0, e1), max(e0, e1)
    margin = 0.05 * (hi - lo)
    ok = lo + margin <= window[0] and window[1] <= hi - margin
    print(f"{slope:+.4f} eV/px, image covers {lo:.1f}-{hi:.1f} eV "
          f"({hi - lo:.1f} eV over {n_px} px)")
    print(f"window {window[0]:.0f}-{window[1]:.0f} eV: "
          + ("fits with margin" if ok else "DOES NOT FIT with 5% margin"))
    if not ok:
        mid = 0.5 * (lo + hi)
        print(f"image center sits at {mid:.1f} eV, window center at "
              f"{0.5 * sum(window):.1f} eV")
    return slope, e0, e1


def fit_waist(z, w):
    """
    Waist position from a z scan: parabola in w**2 over the 7 points nearest
    the minimum. Falls back to the minimum point if the fit is not concave
    up or lands outside the scanned range.
    """
    z, w = np.asarray(z, float), np.asarray(w, float)
    good = np.isfinite(w) & (w > 0)
    z, w = z[good], w[good]
    if len(z) < 3:
        return np.nan
    i = int(np.argmin(w))
    sel = slice(max(0, i - 3), min(len(z), i + 4))
    if len(z[sel]) >= 3:
        a, b, _ = np.polyfit(z[sel], w[sel] ** 2, 2)
        if a > 0 and z.min() <= -b / (2 * a) <= z.max():
            return float(-b / (2 * a))
    return float(z[i])


def k_for_real(real_eV, offset_eV=REQ_OFFSET_EV):
    """Nearest K request on the loaded ACR list for a real photon energy."""
    step = ut.ACR_LIST_EV[2]
    req = np.round((real_eV - offset_eV) / step) * step
    return float(check_on_list([req])[0])


def geom_rings(det_dist_mm, calibrant='LaB6', energy_eV=TFS_E_EV, n_max=10):
    """
    Print calibrant ring radii on the JF16M for one detector distance.

    Rings inside the 10 mm beamstop or beyond the detector edge are marked.
    Pick a distance with at least four rings on the sensor before the
    geometry run.
    """
    if calibrant not in CALIBRANTS:
        raise ValueError(f"calibrant must be one of {list(CALIBRANTS)}")
    lam = HC / energy_eV
    print(f"{calibrant}, {energy_eV:.1f} eV (lambda {lam:.4f} A), "
          f"JF16M at {det_dist_mm:.1f} mm")
    print("  ring   d (A)   2theta (deg)   r (mm)")
    for n, d in enumerate(CALIBRANTS[calibrant][:n_max], 1):
        s = lam / (2 * d)
        if s >= 1:
            break
        tth = 2 * np.arcsin(s)
        r = det_dist_mm * np.tan(tth)
        flag = ('  behind beamstop' if r < JF16M_BEAMSTOP_MM else
                '  off detector edge' if r > JF16M_HALF_MM else '')
        print(f"{n:5d}  {d:6.3f}   {np.degrees(tth):10.3f}   {r:7.1f}{flag}")


def _um_tag(um):
    """0.75 -> '0p75' for sample names."""
    return f"{um:g}".replace('.', 'p')


# ---- the experiment object ----------------------------------------------------

class User:
    """Shift 2026-11-16 procedures. Call x.help() for the method list."""

    def __init__(self):
        # real = K request + offset; update after x.offset_check()
        self.offset_eV = REQ_OFFSET_EV
        # K request at the Fe foil edge; every grid tonight centers here
        self.edge_k = EDGE_K_EV
        # report rec 12: XRT follows K in every scan where the spectrum is
        # the measurement. x.xrt_off() parks it for the rest of the night
        self.xrt_track = True
        # crystal-only offset (tth does not follow); retune at 18:00 if the
        # spectrum is off center, then every scan below picks it up
        self.xrt_offset = XRT_OFFSET_DEG
        # dead band as ACR / undulator controls report it (x.deadband)
        self.db_um = DB_RESTORE_UM
        self.db_results = []
        self.tfs_zmin = TFS_Z_MM
        self.last_zscan = None
        # run, energy, step, num of the last x.spec_calib(), for notch.output
        self.last_calib = None
        # SASE center against K (x.sase_cal) and XRT crystal correction
        # (x.xrt_cal). Scans use them only after x.sase_on() / x.xrt_cal_on()
        # (both cal methods switch them on); a new User() starts without
        # them: x.cal_load() reads the last saved ones
        self.sase = None
        self.use_sase = False
        self.xrtcal = None
        self.use_xrtcal = False

    # ---- overview ---------------------------------------------------------

    def help(self):
        """Print the methods in shift order."""
        print("""
before beam   x.checklist_pre()  x.status()  x.dry_run()  x.mesh_status()
18:00         x.acr_list_set(lo, hi, step, k_max)   (list ACR confirms)
              x.db_read()   (expect 0.125 um)   x.xrt_park()  x.xrt_tune(d)
              DCCM in: x.offset_check()  x.offset_fine(c)  x.set_offset(v)
              DCCM in: x.sase_cal()  (SASE center vs K, ~10 min)  x.xrt_cal()  (XRT line
                       on the center column vs energy, ~5 min)   x.procedure('calib')
              DCCM out: x.fe_foil_scan()  x.fe_foil_scan(reverse=True)  x.set_edge(k)
19:00 ACR     x.deadband(um) after every change ACR makes, then
              D0 x.db_baseline()    D1/D2 x.db_scan()    D3 x.db_scan(step=0.5)
              D4 x.db_scan(label='nolist')    D5 x.db_table()
21:00 fly     DCCM in: F0 x.fly_ref()  F1 x.fly('track')  F2 x.fly('center')
              F3 x.fly('track', reverse=True)  F4 x.fly_ref(points=True)
22:00 MESH    x.pink_switch()  x.mesh_set(kv)  x.mb_blank('start')  x.mb_park(r=1)
23:15         x.mb_pass(n, r) ... one DAQ run per pass, reservoir changes between
              x.mb_edge(n, r): real edge +- 30 eV in 5 eV, up only (edge = x.edge_k + x.offset_eV)
05:15         x.mb_blank('end')  x.mesh_off()  [DCCM-in foil: x.fe_foil_scan(dccm_offset=x.offset_eV)]
06:00         x.db_read()  (0.125 um after the GUI closes)  x.checklist_post()
any time      x.dccm_test()  (six-line DCCM check: code, calibration, state, +20 eV and back)
              x.sase_check()  (DCCM in: one K, measured vs predicted center; rezero=True)
              x.xrt_line()  (line column vs target now)   x.cal_show()  x.cal_load()
              x.sase_on/off()  x.xrt_cal_on/off()  x.real(k)  x.k_for(real)
              x.procedure('deadband'|'fly'|'mesh'|'xrt'|'calib'|'tfs'|'geom')
              x.xrt_on()  x.xrt_off()  x.xrt_check()  x.tfs_*  x.geom_rings(D)
""")

    def status(self):
        """Print K, done PV, list, dead band, DCCM, XRT, TFS, beam and MESH state."""
        from epics import caget

        def show(label, fn):
            try:
                print(f"  {label:22s} {fn()}")
            except Exception as e:
                print(f"  {label:22s} ? ({e.__class__.__name__})")

        def xrt_pos():
            xs = _ns('xrtspec').hxrsss
            return f"{xs.th.position:.3f} / {xs.tth.position:.3f} / {xs.camy.position:.3f}"

        def tfs_in():
            tfs = _ns('tfs')
            return [n for n in range(2, 11) if getattr(tfs, f'tfs_{n:02d}').inserted]

        lo, hi, step = ut.ACR_LIST_EV
        print(f"experiment file {EXP} ({SHIFT}), offset {self.offset_eV:+.1f} eV, "
              f"edge K {self.edge_k:.1f} eV, xrt_track {self.xrt_track}, "
              f"xrt_offset {self.xrt_offset:+.3f} deg, dead band recorded {self.db_um:g} um")
        print(f"  {self._cal_state()}")
        show('K request (eV)', lambda: f"{_ns('exafs').acr_energy_k.get().setpoint:.1f}")
        show('done PV AO805', lambda: caget('SIOC:SYS0:ML07:AO805'))
        show('ACR list in use', lambda: f"{lo:.1f}-{hi:.1f} eV in {step:g} eV, "
             f"K cap {ut.K_MAX_EV:.1f} eV")
        show('dead band readback', lambda: ut.deadband_text(ut.read_deadband(timeout=0.5)))
        show('DCCM energy (keV)', lambda: f"{_ns('dccm').energy.position}")
        show('DCCM state', lambda: _caget(DCCM_STATE_RBV, as_string=True))
        show('XRT th/tth/camy', xrt_pos)
        show('XRT camera', lambda: caget(ZYLA_PV, as_string=True))
        show('TFS z (mm)', lambda: f"{_ns('tfs').translation.position:.2f}")
        show('TFS lenses in', tfs_in)
        show('prefocus', lambda: _ns('crl1').state.get())
        show('attenuator T', lambda: f"{_ns('att').position:.2e}")
        show('pulse picker', lambda: _ns('mfx_pulsepicker').position)
        show('MESH SP / RB (V)', lambda: f"{caget(MESH_SP) * MESH_SCALE_V:.0f} / "
             f"{caget(MESH_RB) * MESH_SCALE_V:.0f}")
        show('hutch door', lambda: caget(DOOR_PV, as_string=True))

    def procedure(self, block=None):
        """Print the step list for 'deadband', 'fly', 'mesh', 'xrt', 'tfs' or 'geom'."""
        if block not in _PROC:
            print(f"blocks: {', '.join(_PROC)}")
            return
        print(_PROC[block])

    def checklist_pre(self):
        """Print the pre-experiment checklist (same list as the PDF)."""
        print(_CHECK_PRE)

    def checklist_post(self):
        """Print the post-experiment checklist (same list as the PDF)."""
        print(_CHECK_POST)

    def dry_run(self):
        """
        Print every grid tonight against the loaded list, then simulate one
        dead band scan, one fly scan and one Mb pass.

        Moves nothing and writes no CSV (simulated scans never write).
        Raises if a grid does not fit the list or cap.
        """
        lo, hi, step = ut.ACR_LIST_EV
        print(f"ACR list {lo:.1f}-{hi:.1f} eV in {step:g} eV "
              f"({len(ut.acr_list())} points), K cap {ut.K_MAX_EV:.1f} eV, "
              f"edge K {self.edge_k:.1f} eV")
        db1, a1 = db_positions(self.edge_k, 1.0)
        db05, a05 = db_positions(self.edge_k, 0.5)
        fly, af = fly_positions(self.edge_k)
        mb = mb_positions(self.edge_k)
        rows = [('db 1 eV sweep', db1, a1), ('db 0.5 eV sweep', db05, a05),
                ('fly 5 eV up', fly, af), ('Mb pass 2.5 eV', mb, None)]
        for name, pos, app in rows:
            print(f"  {name:16s} {len(pos):3d} visits, {min(pos):.1f}-{max(pos):.1f} eV"
                  + (f", approach {app:.1f} eV" if app is not None else ""))
        park = float(check_on_list([self.edge_k + MB_PARK_ABOVE_EV])[0])
        print(f"  Mb park K {park:.1f} eV")
        off = self._center_offsets(fly_offsets('track'))
        print(f"  {self._cal_state()}")
        print(f"  fly 'track' DCCM offsets from the "
              f"{'calibrated SASE center' if self.use_sase else 'K request'}: {off}")
        center = {k: v for k, v in self.xrt_opts().items() if k == 'energy_center'}
        exafs = _ns('exafs')
        exafs.k_xas_scan(k_positions=db1, k_order='given', pink=True,
                         k_move_mode=K_MODE, dwell_time=0.1, simulate=True)
        exafs.k_xas_scan(k_positions=fly, k_order='given', dccm_offsets=off,
                         k_move_mode='concurrent', dwell_time=0.1, simulate=True,
                         **center)
        exafs.k_xas_scan(k_positions=mb, k_order='given', pink=True,
                         k_move_mode=K_MODE, dwell_time=0.1, simulate=True)

    # ---- list, edge, offset ---------------------------------------------------

    def acr_list_set(self, lo, hi, step, k_max):
        """
        Put in the list and K cap ACR confirms are loaded (requested eV).

        Asked before the shift: 7040-7160 eV in 0.5 eV, highest K 7160 eV.
        Every grid built after this call is checked against it; x.dry_run()
        shows whether tonight's grids fit.
        """
        res = ut.set_acr_list(lo, hi, step, k_max=k_max)
        _post(f"ACR list confirmed: {res[0]:.1f}-{res[1]:.1f} eV in {res[2]:g} eV "
              f"({len(ut.acr_list())} points), K cap {res[3]:.1f} eV")
        return res

    def set_edge(self, k_eV):
        """Set the K request at the Fe foil edge; db, fly and Mb grids follow it."""
        self.edge_k = float(check_on_list([k_eV])[0])
        _post(f"edge K set to {self.edge_k:.1f} eV (10-26: 7080 eV)")

    def set_offset(self, eV):
        """Set the request-to-real offset (real = K request + offset, eV)."""
        self.offset_eV = float(eV)
        _post(f"request-to-real offset set to {self.offset_eV:+.1f} eV "
              f"(10-26: +20 eV, real above the machine-reported energy; 10-09: -5.2 eV)")

    def mono(self, real_eV=TFS_E_EV):
        """
        DCCM in and set to real_eV, K requested to the matching list point.

        K from the SASE calibration when it is on (x.sase_on), else from
        self.offset_eV (run x.offset_check() first if it is in doubt). The
        DCCM moves on its own energy axis, not with the vernier. DCCM
        energy from hutch python only (PLC motion code under debug on
        11-09; the PyDM screen is not trusted).
        """
        k = self.k_for(real_eV)
        dccm = _ns('dccm')
        print(f"DCCM in, DCCM {real_eV:.1f} eV, K request {k:.1f} eV "
              f"(SASE center {self.real(k):.1f})")
        dccm.insert()
        request_k(_ns('exafs').acr_energy_k, k, k_max=ut.K_MAX_EV)
        dccm.energy.move(real_eV / 1000.0, wait=True)

    def dccm_test(self, delta_eV=20.0, move=True, timeout=60.0, settle=3.0):
        """
        Short DCCM check, six lines to read out by hand.

        CODE: which dccm.py is loaded (CTC = PLC energy controller,
        DIRECT = TH1/TH2 motor records). CAL: crystal offsets in the motor
        records (.OFF) and in the PLC (AngleOffset). NOW: energy readback,
        CTC setpoint and state, thetas. With move=True, UP and BACK move
        dccm.energy by +delta_eV and back (the call x.mono and the scans
        use) and sample the PLC State/Done every 0.05 s until settle s
        after the move returns. VERDICT: one line. Energies in eV, angles
        in degrees.
        """
        P, C = 'SP1L0:DCCM:', 'SP1L0:DCCM:CTC:CRYS:01:'
        d_si, hc = 3.13560114, 12398.419

        def g(pv):
            v = _caget(pv, timeout=0.5)
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        def f(v, fmt='.4f'):
            return '?' if v is None else format(v, fmt)

        def bragg(e_eV):
            return float(np.degrees(np.arcsin(hc / (2 * d_si * e_eV))))

        def seq(vals):
            return '>'.join('?' if v is None else str(int(v)) for v in vals) or '?'

        en = _ns('dccm').energy
        code = ('CTC' if 'actuate' in getattr(type(en), 'component_names', ())
                else 'DIRECT')
        lines = [f"CODE {code} prefix={getattr(en, 'prefix', '?')}"]

        off1, off2 = g(P + 'MMS:TH1.OFF'), g(P + 'MMS:TH2.OFF')
        ao1, ao2 = g(C + 'AngleOffset'), g('SP1L0:DCCM:CTC:CRYS:02:AngleOffset')
        if None in (off1, ao1):
            where = '?'
        else:
            key = (abs(off1) > 1e-4, abs(ao1) > 1e-4)
            where = {(True, False): 'OFF', (False, True): 'PLC',
                     (True, True): 'BOTH', (False, False): 'NONE'}[key]
        lines.append(f"CAL  OFF1={f(off1, '.5f')} OFF2={f(off2, '.5f')} "
                     f"AO1={f(ao1, '.5f')} AO2={f(ao2, '.5f')} calib={where}")

        def now():
            e, cmd = g(C + 'EstEnergy_RBV'), g(C + 'CmdkeV')
            return dict(e=None if e is None else e * 1000,
                        cmd=None if cmd is None else cmd * 1000,
                        st=g(C + 'State_RBV'), dn=g(C + 'Done_RBV'),
                        err=g(C + 'Error_RBV'), cp=g('SP1L0:DCCM:CTC:Coupled_RBV'),
                        th1=g(P + 'MMS:TH1.RBV'), th2=g(P + 'MMS:TH2.RBV'))

        n0 = now()
        par = None if None in (n0['th1'], n0['th2']) else n0['th1'] - n0['th2']
        lines.append(f"NOW  E={f(n0['e'], '.1f')} cmd={f(n0['cmd'], '.1f')} "
                     f"state={f(n0['st'], '.0f')} done={f(n0['dn'], '.0f')} "
                     f"err={f(n0['err'], '.0f')} coupled={f(n0['cp'], '.0f')} "
                     f"TH1={f(n0['th1'])} TH2={f(n0['th2'])} TH1-TH2={f(par)}")

        def finish(lines):
            for line in lines:
                print(line)
            _post("dccm_test\n" + "\n".join(lines), tag='dccm')
            return lines

        if not move:
            return finish(lines)
        try:
            e0_keV = float(en.position)
        except Exception:
            e0_keV = None if n0['e'] is None else n0['e'] / 1000.0
        if e0_keV is None:
            lines.append("VERDICT no start energy readable, not moved")
            return finish(lines)

        def run(target_keV):
            st_seq, dn_seq = [], []
            b = now()
            t0, t_ret, err, status = time.time(), None, None, None
            try:
                status = en.move(target_keV, wait=False)
            except Exception as e:
                err = e
            while time.time() < t0 + timeout:
                for sq, v in ((st_seq, g(C + 'State_RBV')), (dn_seq, g(C + 'Done_RBV'))):
                    if not sq or sq[-1] != v:
                        sq.append(v)
                done = status is None or getattr(status, 'done', True)
                if done and t_ret is None:
                    t_ret = time.time() - t0
                if t_ret is not None and time.time() > t0 + t_ret + settle:
                    break
                time.sleep(0.05)
            ok = None
            if status is not None and getattr(status, 'done', False):
                ok = getattr(status, 'success', None)
                if ok is False and err is None:
                    try:
                        err = status.exception()
                    except Exception as e:
                        err = e
            a = now()
            d = {k: (None if None in (a[k], b[k]) else a[k] - b[k]) for k in ('th1', 'th2')}
            return dict(t=t_ret, st=st_seq, dn=dn_seq, ok=ok, err=err, a=a, d=d)

        e0 = e0_keV * 1000
        res, exp_up = {}, bragg(e0 + delta_eV) - bragg(e0)
        for name, tgt, exp in (('UP', e0 + delta_eV, exp_up), ('BACK', e0, -exp_up)):
            r = run(tgt / 1000.0)
            res[name] = r
            lines.append(
                f"{name:4s} {tgt:.1f}: ret={f(r['t'], '.1f')}s ok={r['ok']} "
                f"state {seq(r['st'])} done {seq(r['dn'])} dTH1={f(r['d']['th1'])} "
                f"dTH2={f(r['d']['th2'])} exp={exp:+.4f} E={f(r['a']['e'], '.1f')} "
                f"cmd={f(r['a']['cmd'], '.1f')}"
                + (f" ERR {str(r['err'])[:60]}" if r['err'] else ""))

        up = res['UP']
        moved = (up['d']['th1'] is not None and abs(up['d']['th1']) > 0.3 * abs(exp_up))
        if not moved:
            states = [int(v) for v in up['st'] if v is not None]
            if code == 'CTC' and 4 not in states:
                verdict = "NO MOTION, PLC state never 4 (MOVING)"
            elif code == 'CTC':
                verdict = "NO MOTION, PLC went MOVING but thetas did not change"
            else:
                verdict = "NO MOTION, direct TH1/TH2 move did not move the axes"
        else:
            verdict = "MOVED"
            if code == 'CTC' and where == 'OFF':
                verdict += ", but calib is in .OFF: CTC path uncalibrated"
            if code == 'DIRECT' and where == 'PLC':
                verdict += ", but calib is in the PLC: direct path uncalibrated"
        lines.append(f"VERDICT {verdict}")
        return finish(lines)

    def offset_check(self, k=None, lo=-20.0, hi=40.0, step=2.0, dwell=2.0,
                     record=True):
        """
        Find the request-to-real offset with the DCCM, at one K request.

        DCCM in. K at k (default x.edge_k + 10), the DCCM steps from K + lo
        to K + hi eV. The DG2 IPM against DCCM energy peaks at the real SASE
        center. The window holds the 10-26 offset (+20 eV, real above the
        machine-reported energy) and the 10-09 one (-5.2 eV) with the
        ~22 eV FWHM SASE profile around either. Then x.offset_fine(c)
        around the peak offset c, and x.set_offset(c). About 3 min at the
        defaults.
        """
        k = self.edge_k + 10.0 if k is None else k
        k = float(check_on_list([k])[0])
        offsets = [round(float(o), 2) for o in np.arange(lo, hi + step / 2, step)]
        _ns('dccm').insert()
        print(f"offset check: K {k:.1f} eV, DCCM {k + offsets[0]:.1f}-{k + offsets[-1]:.1f} "
              f"eV in {step:g} eV, dwell {dwell:g} s")
        request_k(_ns('exafs').acr_energy_k, k, k_max=ut.K_MAX_EV)
        return _ns('exafs').k_xas_scan(
            k_positions=[k], k_order='given', k_move_mode=K_MODE,
            dccm_offsets=offsets, dwell_time=dwell, record=record,
            sample=f'{PREFIX}_offset_check_k{k:.0f}', picker='open',
            dccm_from_center=False, **self.xrt_opts())

    def offset_fine(self, center, half=6.0, step=0.5, k=None, dwell=2.0,
                    record=True):
        """Fine offset scan: DCCM offsets center +- half eV in step eV (center = offset from K)."""
        return self.offset_check(k=k, lo=center - half, hi=center + half,
                                 step=step, dwell=dwell, record=record)

    # ---- SASE center and XRT calibration (DCCM in) -----------------------------

    def real(self, k_eV, prev_k_eV=None):
        """Real SASE center (eV) for a K request: calibration when on, else K + x.offset_eV."""
        if self.use_sase and self.sase is not None:
            return self.sase.center(k_eV, prev_k_eV)
        return float(k_eV) + self.offset_eV

    def k_for(self, real_eV, check=True):
        """K request (list step) whose SASE center is closest to real_eV."""
        if self.use_sase and self.sase is not None:
            k = self.sase.k_for(real_eV)
        else:
            k = float(real_eV) - self.offset_eV
        step = ut.ACR_LIST_EV[2]
        k = float(np.round(k / step) * step)
        return float(check_on_list([k])[0]) if check else k

    def _center_offsets(self, off):
        """DCCM offsets (eV from the SASE center) as k_xas_scan wants them."""
        if self.use_sase and self.sase is not None:
            return [round(float(o), 3) for o in off]
        return [round(self.offset_eV + float(o), 3) for o in off]

    def _cal_state(self, short=False):
        if self.use_sase and self.sase is not None and self.sase.ready:
            ref = self.sase.models['all']['ref']
            c = self.sase.center(ref)
            s = (f"SASE cal ON (center {c:.1f} eV at K {ref:.1f}, "
                 f"{self.sase.center(ref + 1.0) - c:.3f} eV per eV of K)")
        else:
            s = (f"offset {self.offset_eV:+.1f} eV (SASE cal "
                 f"{'loaded, off' if self.sase is not None else 'none'})")
        if short:
            return s
        if self.use_xrtcal and self.xrtcal is not None and self.xrtcal.ready:
            x = (f"XRT cal ON (corr {self.xrtcal.correction(self.real(self.edge_k) / 1000):+.4f}"
                 f" deg at the edge)")
        else:
            x = f"XRT cal {'loaded, off' if self.xrtcal is not None else 'none'}"
        return f"{s}, {x}"

    def _install_xrt(self):
        """Put the XRT correction on every XRTspec instance (beamline and exafs)."""
        fn = None
        if self.use_xrtcal and self.xrtcal is not None and self.xrtcal.ready:
            fn = self.xrtcal.correction
        seen = set()
        for name, get in (('xrtspec', lambda: _ns('xrtspec')),
                          ('exafs.xrtspec', lambda: _ns('exafs').xrtspec)):
            try:
                xs = get()
            except Exception as e:
                logger.warning(f"{name} not found for the XRT calibration: {e}")
                continue
            if xs is None or id(xs) in seen:
                continue
            seen.add(id(xs))
            xs.th_correction = fn

    def sase_on(self):
        """DCCM points, XRT tracking, x.mono and x.k_for use the SASE calibration."""
        if self.sase is None or not self.sase.ready:
            raise RuntimeError("no SASE calibration: x.sase_cal() or x.cal_load() first")
        self.use_sase = True
        _post("SASE calibration ON for every scan: " + self.sase.model_text(), tag='calib')

    def sase_off(self):
        """Back to the constant x.offset_eV."""
        self.use_sase = False
        _post(f"SASE calibration OFF, constant offset {self.offset_eV:+.1f} eV", tag='calib')

    def xrt_cal_on(self):
        """XRT crystal angle includes the measured correction (every scan and xrt_park)."""
        if self.xrtcal is None or not self.xrtcal.ready:
            raise RuntimeError("no XRT calibration: x.xrt_cal() or x.cal_load() first")
        off = self.xrtcal.meta.get('offset_deg')
        if off is not None and abs(off - self.xrt_offset) > 1e-6:
            logger.warning(f"XRT calibration was taken with x.xrt_offset {off:+.3f} deg, "
                           f"now {self.xrt_offset:+.3f}: the correction adds on top")
        self.use_xrtcal = True
        self._install_xrt()
        _post("XRT calibration ON: " + self.xrtcal.summary().splitlines()[-1].strip(),
              tag='calib')

    def xrt_cal_off(self):
        """XRT crystal angle from the polynomial and x.xrt_offset only."""
        self.use_xrtcal = False
        self._install_xrt()
        _post("XRT calibration OFF", tag='calib')

    def _cal_dir(self):
        d = _results_dir() / 'calib'
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _save_cal(self, cal, name):
        """Write cal as <name>_<time>.json and <name>_latest.json, plus a PNG."""
        d, ts = self._cal_dir(), time.strftime('%Y%m%d_%H%M%S')
        path = cal.save(d / f"{name}_{ts}.json")
        cal.save(d / f"{name}_latest.json")
        try:
            plot = ec.plot_sase if name == 'sase' else ec.plot_xrt
            plot(cal, d / f"{name}_{ts}.png")
        except Exception as e:
            logger.warning(f"{name} plot not written: {e}")
        return path

    def sase_cal(self, k=None, step=SASE_K_STEP_EV, half=SASE_HALF_EV,
                 dccm_step=SASE_DCCM_STEP_EV, read_s=SASE_READ_S, direction='up',
                 deg=1, by_direction=None, diag=SASE_DIAG, add=False, use=True):
        """
        Calibrate the real SASE center against the K request. DCCM in.

        At each K (default x.edge_k - 15 .. + 35 eV in 10 eV, the Mb sweep,
        clipped to the list) K is requested and settles, then the DCCM steps
        center +- half eV in dccm_step eV and the IPM (diag: 'dg2', 'dg1'
        or a PV) over the gas detector is averaged read_s s per point. A
        Gaussian fit gives the center; if the peak sits at the window edge
        the window moves once. The window follows the fit so far, starting
        from K + x.offset_eV.

        center - K is fit against K, degree deg (1: offset and slope; 0:
        constant offset like x.offset_eV). direction 'up' visits K
        ascending after an approach move 5 eV below, like every scan here;
        'down' descending; 'both' does both and, unless by_direction=False,
        fits up and down steps separately. add=True adds the points to the
        calibration in memory instead of starting over.

        Live EPICS reads, no DAQ run. The DCCM and K go back where they
        were. Saves JSON + PNG under results/shift_<date>/calib, posts the
        table, and with use=True switches the calibration on (x.sase_on).
        About 1.5 min per K at the defaults.
        """
        if direction not in ('up', 'down', 'both'):
            raise ValueError("direction must be 'up', 'down' or 'both'")
        if k is None:
            lo, hi = fit_window(self.edge_k - SASE_BELOW_EV, self.edge_k + SASE_ABOVE_EV, step)
            k = list(grid(lo, hi, step))
        ks = sorted(float(v) for v in check_on_list(list(np.atleast_1d(k))))
        appr = []
        if direction in ('up', 'both'):
            appr.append(ks[0] - SASE_APPROACH_EV)
        if direction in ('down', 'both'):
            appr.append(ks[-1] + SASE_APPROACH_EV)
        check_on_list(appr)
        if by_direction is None:
            by_direction = direction == 'both'
        if add and self.sase is not None:
            cal = self.sase
            cal.by_direction = cal.by_direction or by_direction
        else:
            cal = ec.SaseCalibration(deg=deg, by_direction=by_direction)
        cal.meta.update(diag=diag, half_eV=half, dccm_step_eV=dccm_step, read_s=read_s,
                        dead_band_um=self.db_um, offset_guess_eV=self.offset_eV)
        n_pts = int(round(2 * half / dccm_step)) + 1
        legs = 2 if direction == 'both' else 1
        est = legs * len(ks) * (12.0 + n_pts * (DCCM_MOVE_S + read_s + 0.2))
        print(f"SASE calibration: K {ks[0]:.1f}-{ks[-1]:.1f} eV ({len(ks)} points, "
              f"{direction}), DCCM center +- {half:g} eV in {dccm_step:g} eV ({n_pts} points), "
              f"{read_s:g} s each on {diag}, ~{est / 60:.0f} min. Ctrl+C keeps what is done.")
        exafs, dccm = _ns('exafs'), _ns('dccm')
        reader = ec.MeanReader(ec.SIGNAL_PVS.get(diag, diag))
        k0 = float(exafs.acr_energy_k.get().setpoint)
        dccm.insert()
        e0 = float(dccm.energy.position)
        try:
            ec.calibrate_sase(
                cal, ks, lambda kk: request_k(exafs.acr_energy_k, kk, k_max=ut.K_MAX_EV),
                dccm, reader, self.offset_eV, direction=direction,
                approach_eV=SASE_APPROACH_EV, half_eV=half, step_eV=dccm_step,
                read_s=read_s)
        except KeyboardInterrupt:
            print("SASE calibration stopped (Ctrl+C); keeping the points so far")
        finally:
            getattr(reader, 'close', lambda: None)()
            print(f"DCCM back to {e0 * 1000:.1f} eV, K back to {k0:.1f} eV")
            dccm.energy.move(e0, wait=True)
            request_k(exafs.acr_energy_k, k0, k_max=ut.K_MAX_EV)
        self.sase = cal
        path = self._save_cal(cal, 'sase')
        _post(f"{cal.summary()}\ndead band {self.db_um:g} um recorded. saved {path}",
              tag='calib')
        if use and cal.ready:
            self.sase_on()
        elif not cal.ready:
            print("no usable point: calibration not switched on")
        return cal

    def sase_check(self, k=None, half=12.0, dccm_step=1.5, read_s=SASE_READ_S,
                   diag=SASE_DIAG, rezero=False, add=False, approach=True):
        """
        One-K check of the SASE calibration (drift). DCCM in.

        K at k (default: the present K request), always reached from 5 eV
        below like the calibration and the scans: the center depends on the
        side K came from (-3.6 eV for down steps on 10-26), so a check at a
        K of unknown history would re-zero onto the wrong side. approach=
        False skips the approach move (K must have come up). DCCM scan
        predicted center +- half eV, fit. Prints measured minus predicted.
        rezero=True shifts the whole calibration by that amount (slope
        kept); add=True adds the point and refits. DCCM goes back.
        """
        if self.sase is None or not self.sase.ready:
            raise RuntimeError("no SASE calibration: x.sase_cal() or x.cal_load() first")
        exafs, dccm = _ns('exafs'), _ns('dccm')
        k = float(exafs.acr_energy_k.get().setpoint) if k is None else float(k)
        k = float(check_on_list([k])[0])
        prev = float(check_on_list([k - SASE_APPROACH_EV])[0])
        if approach:
            request_k(exafs.acr_energy_k, prev, k_max=ut.K_MAX_EV)
        request_k(exafs.acr_energy_k, k, k_max=ut.K_MAX_EV)
        direction = 'up'
        pred = k + self.sase.offset(k, direction)
        reader = ec.MeanReader(ec.SIGNAL_PVS.get(diag, diag))
        dccm.insert()
        e0 = float(dccm.energy.position)
        try:
            fit, es, rs = ec.measure_sase_center(dccm, reader, pred, half, dccm_step, read_s)
        finally:
            getattr(reader, 'close', lambda: None)()
            dccm.energy.move(e0, wait=True)
        if not fit['ok']:
            print(f"K {k:.1f} eV: no usable fit ({fit['reason']}); calibration unchanged")
            return fit
        d = fit['center'] - pred
        msg = (f"SASE check K {k:.1f} eV: center {fit['center']:.1f} eV, predicted "
               f"{pred:.1f} eV, measured - predicted {d:+.2f} eV, FWHM {fit['fwhm']:.1f} eV")
        if add:
            self.sase.add(k, fit, direction=direction, energies=es, signals=rs)
            self.sase.fit()
            msg += "; point added, refit: " + self.sase.model_text()
        elif rezero:
            sh = self.sase.rezero(k, fit['center'], direction)
            msg += f"; calibration shifted {sh:+.2f} eV"
        if add or rezero:
            self._save_cal(self.sase, 'sase')
        _post(msg, tag='calib')
        return fit

    def _zyla(self):
        return ec.ZylaLine(ZYLA_PV.rsplit(':', 1)[0])

    def xrt_line(self, frames=XRT_CAL_FRAMES, target_px=None):
        """Where the line sits on the Zyla now (column) against the target; no motion."""
        line = self._zyla()
        target = line.width() / 2.0 if target_px is None else float(target_px)
        r = line.read(frames)
        if not r['ok']:
            print(f"line not found: {r['reason']}")
        else:
            print(f"line at {r['px']:.1f} px (FWHM {r['fwhm_px']:.1f} px), target "
                  f"{target:.1f}: {r['px'] - target:+.1f} px")
        return r

    def xrt_cal(self, energies=None, n=XRT_CAL_N, delta=XRT_ROCK_DEG,
                frames=XRT_CAL_FRAMES, target_px=None, deg=1, use=True):
        """
        Calibrate the XRT crystal angle so the DCCM line sits on the target
        column (default the image center) at every energy. DCCM in, Zyla
        acquiring.

        energies (real eV) default to n points over the SASE centers of the
        Mb sweep (x.edge_k - 15 .. + 35 eV). At each: K to x.k_for(E) (run
        x.sase_cal first so the SASE sits on E), DCCM to E, XRT to E with
        the present correction, th rocked +- delta deg (3 points), line
        column fit against th and solved for the target. The correction
        (best - model th) is fit against energy, degree deg, saved and with
        use=True installed (x.xrt_cal_on). The XRT is then parked at the
        SASE center of the K it started at; K and the DCCM go back.
        th steps go straight to the motor, like x.xrt_tune; a solution more
        than 0.5 deg away is not applied.
        """
        exafs, dccm, xrt = _ns('exafs'), _ns('dccm'), _ns('xrtspec')
        if energies is None:
            lo = self.real(self.edge_k - SASE_BELOW_EV)
            hi = self.real(self.edge_k + SASE_ABOVE_EV)
            energies = [round(float(e) * 2) / 2 for e in np.linspace(lo, hi, n)]
        energies = [float(e) for e in energies]
        for e in energies:
            self.k_for(e)   # raises if the K for an energy is off the list
        line = self._zyla()
        target = line.width() / 2.0 if target_px is None else float(target_px)
        cal = ec.XrtCalibration(deg=deg)
        cal.meta.update(offset_deg=self.xrt_offset, target_px=target, delta_deg=delta,
                        frames=frames, sase_on=self.use_sase)
        print(f"XRT calibration: {len(energies)} energies {energies[0]:.1f}-{energies[-1]:.1f} "
              f"eV, th +- {delta:g} deg, line to column {target:.1f}, "
              f"~{len(energies) * 50 / 60:.0f} min. Ctrl+C keeps what is done.")
        k0 = float(exafs.acr_energy_k.get().setpoint)
        dccm.insert()
        e0 = float(dccm.energy.position)

        def set_energy(e):
            request_k(exafs.acr_energy_k, self.k_for(e), k_max=ut.K_MAX_EV)
            dccm.energy.move(e / 1000.0, wait=True)

        try:
            ec.calibrate_xrt(cal, energies, set_energy, xrt, line, self.xrt_offset, target,
                             delta_deg=delta, frames=frames)
        except KeyboardInterrupt:
            print("XRT calibration stopped (Ctrl+C); keeping the points so far")
        finally:
            print(f"DCCM back to {e0 * 1000:.1f} eV, K back to {k0:.1f} eV")
            dccm.energy.move(e0, wait=True)
            request_k(exafs.acr_energy_k, k0, k_max=ut.K_MAX_EV)
        self.xrtcal = cal
        path = self._save_cal(cal, 'xrt')
        _post(f"{cal.summary()}\nsaved {path}", tag='calib')
        if use and cal.ready:
            self.xrt_cal_on()
        elif not cal.ready:
            print("no usable point: XRT calibration not switched on")
        try:
            self.xrt_park(self.real(k0))
        except Exception as e:
            logger.warning(f"XRT park after the calibration failed: {e}")
        return cal

    def cal_show(self):
        """Print both calibrations and whether scans use them."""
        print(self._cal_state())
        for cal in (self.sase, self.xrtcal):
            if cal is not None:
                print(cal.summary())

    def cal_load(self, sase=True, xrt=True, folder=None, use=True):
        """
        Load the last saved calibrations (<name>_latest.json, or a folder /
        file given) and with use=True switch them on. For a new User() after
        a reload.
        """
        d = Path(folder) if folder is not None else self._cal_dir()
        for want, name, cls in ((sase, 'sase', ec.SaseCalibration),
                                (xrt, 'xrt', ec.XrtCalibration)):
            if not want:
                continue
            path = d if d.suffix == '.json' else d / f"{name}_latest.json"
            if not path.exists():
                print(f"no {name} calibration at {path}")
                continue
            try:
                cal = cls.load(path)
            except ValueError:
                continue    # a single file of the other kind
            setattr(self, 'sase' if name == 'sase' else 'xrtcal', cal)
            print(f"loaded {path}")
            print(cal.summary())
            if use and cal.ready:
                self.sase_on() if name == 'sase' else self.xrt_cal_on()

    # ---- dead band (19:00-21:00, with ACR) -------------------------------------

    def db_read(self, post=True):
        """
        Read DeadbandHgEnc on every segment (read-only) and post one line.

        Expect 0.125 um at 18:00 (restore after 10-27 never confirmed) and at
        06:00 after the energy GUI closes. Returns {segment: value or None}.
        """
        values = ut.read_deadband()
        text = (f"{ut.deadband_text(values)} (recorded {self.db_um:g} um, "
                f"{time.strftime('%H:%M')})")
        if post:
            _post(text, tag='deadband')
        else:
            print(text)
        return values

    def deadband(self, um, note=''):
        """
        Record the dead band ACR / undulator controls just set, in um.

        Hutch python never writes the band. Call this after every change so
        sample names and elog lines carry it, e.g. x.deadband(0.75).
        """
        self.db_um = float(um)
        rb = ut.deadband_text(ut.read_deadband(timeout=0.5))
        _post(f"dead band set to {self.db_um:g} um by ACR / undulator controls at "
              f"{time.strftime('%H:%M')}{(', ' + note) if note else ''}. Readback: {rb}",
              tag='deadband')

    def db_scan(self, step=1.0, n=DB_N, direction='updown', dwell=DB_DWELL_S,
                start=None, label=None, record=True):
        """
        Dead band test scan on the Fe foil, pink beam, DCCM out.

        n positions from start (default x.edge_k - 15 eV) in step eV, swept
        up and back down by default ('up', 'down' or 'updown'). K is first
        requested one step outside the start so step 1 is a real move.
        concurrent_settled with dwell 12 s, so a step takes max(dwell, K
        move) and the k_move column of the timing table is the measurement.
        After the run the pass rule is applied per leg (x.db_table() keeps
        the results): real-step median <= 12.5 s, at most one slow step
        (stage-2 tail) per 40, at most one leading null request and none
        after. The DCCM is never moved here; take it out first.
        """
        pos, approach = db_positions(self.edge_k, step, n, direction, start)
        um = self.db_um
        opts = self.xrt_opts()
        sample = f"{PREFIX}_db{_um_tag(um)}um_{step:g}eV_{direction}"
        sample = sample.replace('.', 'p') + (f"_{label}" if label else "")
        if opts['track_feespec']:
            sample += '_xrt'
        run = _next_run(record)
        msg = (f"dead band scan run {run}: band {um:g} um recorded; "
               f"{ut.deadband_text(ut.read_deadband(timeout=0.5))}. K {min(pos):.1f}-"
               f"{max(pos):.1f} eV in {step:g} eV, {direction}, {len(pos)} visits, "
               f"approach {approach:.1f} eV, dwell {dwell:g} s, {K_MODE}, XRT "
               f"tracking {'on' if opts['track_feespec'] else 'off'}"
               f"{(', ' + label) if label else ''}")
        _post(msg, tag='deadband') if record else print(msg)
        exafs = _ns('exafs')
        request_k(exafs.acr_energy_k, approach, k_max=ut.K_MAX_EV)
        out = exafs.k_xas_scan(
            k_positions=pos, k_order='given', k_move_mode=K_MODE,
            dwell_time=dwell, pink=True, record=record, sample=sample,
            picker='open', **opts)
        timer = getattr(exafs, '_step_timer', None)
        rows = list(getattr(timer, 'rows', None) or [])
        passed, legs, text = db_verdict(rows)
        # k_xas_scan returns normally after Ctrl+C; a partial sweep never
        # counts toward the band choice
        if len(rows) < len(pos):
            passed = False
            text = (f"INCOMPLETE, {len(rows)} of {len(pos)} visits (stopped), not "
                    f"judged. {text}")
        self.db_results.append(dict(
            time=time.strftime('%H:%M'), run=run, um=um, step=step,
            direction=direction, label=label or '', visits=len(pos),
            done=len(rows), passed=passed, legs=legs, text=text))
        line = (f"dead band {um:g} um, {step:g} eV {direction}"
                f"{(' ' + label) if label else ''}, run {run}: {text}")
        _post(line, tag='deadband', run=run) if record else print(line)
        return out

    def db_baseline(self, n=12, dwell=DB_DWELL_S):
        """
        D0: 1 eV up at the band in place at 19:00 (expect 0.125 um), list on.

        Measures the girder start and step time with the list at the
        original band, which separates the list from the dead band (report
        rec 9). About 4 min.
        """
        if abs(self.db_um - DB_RESTORE_UM) > 1e-9:
            logger.warning(f"recorded dead band is {self.db_um:g} um, not "
                           f"{DB_RESTORE_UM:g}: x.deadband() first if ACR changed it")
        return self.db_scan(step=1.0, n=n, direction='up', dwell=dwell,
                            label='baseline')

    def db_table(self):
        """Print every dead band scan so far with its pass/fail line."""
        if not self.db_results:
            print("no dead band scans yet")
            return []
        print(" time   run    band    step  direction  label      visits   result")
        for r in self.db_results:
            print(f" {r['time']}  {str(r['run']):>5s}  {r['um']:5g} um  {r['step']:4g}  "
                  f"{r['direction']:9s}  {r['label']:9s}  {r['done']:3d}/{r['visits']:<3d}  "
                  f"{'PASS' if r['passed'] else 'FAIL'}")
            print(f"        {r['text']}")
        ok = sorted({r['um'] for r in self.db_results if r['passed'] and r['step'] == 1.0})
        if ok:
            print(f"narrowest band that passed at 1 eV: {ok[0]:g} um")
        return self.db_results

    # ---- XRT spectrometer ---------------------------------------------------

    def xrt_park(self, real_eV=CENTER_EV, offset_deg=None):
        """
        Park the FEE (XRT) spectrometer at real_eV.

        Moves th, tth and camy together and backs off if XRT:HXS:TRNS.SEVR
        alarms. offset_deg defaults to x.xrt_offset. Check the filter wheel
        STEP:XRT1:446:MOTR.RBV first (it sat at 54 deg for 60 h after 10-27).
        """
        offset_deg = self.xrt_offset if offset_deg is None else offset_deg
        xrt = _ns('xrtspec')
        xrt.move_feespec_energy(real_eV / 1000.0, crystal_angle_offset=offset_deg)
        p = xrt.get_feespec_positions(real_eV / 1000.0, offset_deg)
        print(f"XRT parked for {real_eV:.1f} eV: th {p['crystal_angle']:.3f}, "
              f"tth {p['camera_angle']:.3f}, camy {p['camera_y']:.3f}")

    def xrt_tune(self, delta_deg):
        """
        Nudge the XRT crystal angle by delta_deg and keep it as x.xrt_offset.

        Use with the mono line on the fee_spec CamViewer: move the line to the
        image column that should hold CENTER_EV. th only; tth and camy stay.
        Steps of 0.05 deg or less.
        """
        if abs(delta_deg) > 0.2:
            raise ValueError("step larger than 0.2 deg, split it")
        xs = _ns('xrtspec').hxrsss
        xs.th.umv(xs.th.position + delta_deg)
        self.xrt_offset += delta_deg
        # posted so the value survives a reload (a new User() starts at -1.3)
        _post(f"XRT th {xs.th.position:.3f}, x.xrt_offset {self.xrt_offset:+.3f} deg",
              tag='xrt')

    def xrt_opts(self, xrt=None):
        """
        k_xas_scan keywords for XRT tracking and the SASE center; xrt=None
        uses x.xrt_track.

        Tracking on: before each K request the crystal, camera arm and camy
        move to the new real energy (non-blocking in concurrent_settled),
        after K settles check_feespec_crystal_angle runs (2.0 s per step on
        10-09), at every point the camera arm follows and at the end the
        XRT returns to the start energy. Off: none of these, the XRT stays
        put. The real energy is the calibrated SASE center when x.sase_on()
        (then DCCM offsets count from it too), else K request + x.offset_eV.
        With x.xrt_cal_on() the crystal angle includes the measured
        correction (installed on the spectrometer, not passed here).
        """
        on = self.xrt_track if xrt is None else bool(xrt)
        opts = dict(crystal_angle_offset=self.xrt_offset, track_feespec=on,
                    track_feespec_cam=on, track_feespec_blocking=False,
                    feespec_offset_eV=self.offset_eV)
        if self.use_sase and self.sase is not None:
            opts['energy_center'] = self.sase.center
        return opts

    def xrt_on(self):
        """XRT follows K in every scan from here on (default tonight)."""
        self.xrt_track = True
        print("XRT tracking ON for all scans (report rec 12): the crystal check "
              "after each K move adds ~2 s per step. x.xrt_off() to stop.")

    def xrt_off(self):
        """XRT stays parked in every scan from here on."""
        self.xrt_track = False
        print("XRT tracking OFF: scans never wait on the XRT. A parked XRT loses "
              "~9x throughput across 7080-7110 eV requested (10-26). x.xrt_park() "
              "to re-park at the window center.")

    def xrt_goto(self, real_eV):
        """One-off XRT move to real_eV between scans, camera restarted."""
        self.xrt_park(real_eV)

    def xrt_check(self, real_eV=None):
        """
        Run the crystal-angle check that tracked scans do after each K move.

        real_eV defaults to the SASE center at the current K request
        (x.real()), the energy tracked scans set the XRT for. Corrects th if
        it is off the calculated angle. Use after a manual XRT move.
        """
        if real_eV is None:
            real_eV = self.real(_ns('exafs').acr_energy_k.get().setpoint)
        _ns('xrtspec').check_feespec_crystal_angle(
            real_eV / 1000.0, crystal_angle_offset=self.xrt_offset)
        print(f"XRT angle checked for {real_eV:.1f} eV")

    def xrt_cam_scan(self, lo_eV=WINDOW_EV[0], hi_eV=WINDOW_EV[1], n=4,
                     run_length=30):
        """
        Camera-arm angle scan across lo_eV..hi_eV (real eV), n points.

        Wraps xrtspec.scan_feespec_camera_angle; checks for vignetting at the
        window edges with the crystal fixed. DCCM in, K fixed.
        """
        return _ns('xrtspec').scan_feespec_camera_angle(
            lo_eV / 1000.0, hi_eV / 1000.0, n, run_length=run_length)

    def spec_calib(self, lo_eV=7080, hi_eV=7120, step=5, run_length=10,
                   record=True):
        """
        XRT and SEER energy calibration: notch.series with K following.

        One DAQ run per DCCM energy (integer real eV, sample = energy, tag
        'dccm'). K follows at DCCM energy - x.offset_eV (rounded to the list
        step), so the SASE center sits on the DCCM energy at every point;
        the K values must be on the list and under the cap. XRT parked
        (x.xrt_park() first), SEER fixed. notch.series asks at the end
        whether to return the DCCM and K: answer n. Its return sends K to
        the raw DCCM readback, off the list; spec_calib puts the DCCM and K
        back where they were itself.
        """
        from mfx.macros import get_run
        lo, hi, step = int(lo_eV), int(hi_eV), int(step)
        num = len(range(lo, hi + step, step))
        l_step = ut.ACR_LIST_EV[2]
        offset = self.offset_eV
        if self.use_sase and self.sase is not None:
            # notch takes one constant K offset: the calibrated one at the
            # middle of the range, with the worst error over the range shown
            offs = [e - self.sase.k_for(e) for e in range(lo, hi + step, step)]
            offset = float(np.mean(offs))
            print(f"SASE calibration on: constant K offset {offset:+.1f} eV for notch, "
                  f"calibration varies {min(offs):+.1f} to {max(offs):+.1f} eV over "
                  f"{lo}-{hi} eV")
        k_off = float(np.round(offset / l_step) * l_step)
        check_on_list([e - k_off for e in range(lo, hi + step, step)])
        print(f"DCCM {lo}-{hi} eV in {step} eV, K = DCCM - {k_off:g} eV")
        exafs, dccm = _ns('exafs'), _ns('dccm')
        k0 = float(exafs.acr_energy_k.get().setpoint)
        dccm.insert()
        e0 = float(dccm.energy.position)
        self.last_calib = dict(run=get_run(station=0) + 1, energy=lo, step=step,
                               num=num)
        try:
            _ns('notch').series(lo, hi, step, run_length=run_length, tag='dccm',
                                record=record, k_energy=True, daq_num=2, exp=EXP,
                                k_offset_eV=k_off)
        finally:
            print(f"DCCM back to {e0 * 1000:.1f} eV, K back to {k0:.1f} eV")
            dccm.energy.move(e0, wait=True)
            request_k(exafs.acr_energy_k, k0, k_max=ut.K_MAX_EV)
        return self.last_calib

    def spec_calib_output(self, user, calib=None):
        """fee_calib.py on psana for the last x.spec_calib() (or notch) series."""
        c = calib or self.last_calib
        if not c:
            raise RuntimeError("no calibration series yet, run x.spec_calib()")
        _ns('notch').output(user=user, facility='S3DF', exp=EXP, daq_num=2, **c)

    # ---- Fe foil edge scans --------------------------------------------------

    def fe_foil_scan(self, lo=None, hi=None, step=5.0, dwell=20.0, record=True,
                     dccm_offset=None, reverse=False):
        """
        K scan across the Fe foil edge, one DAQ run.

        lo, hi default to x.edge_k - 20 and x.edge_k + 30 eV, clipped to the
        list and cap. reverse=True runs hi -> lo. K is first requested one
        step outside the start. dccm_offset=None: pink, the DCCM is not
        moved. 'center': the DCCM (put in by hand) sits on the SASE center
        at every step (the calibrated center with x.sase_on(), else K
        request + x.offset_eV). A number: the DCCM sits at K request +
        dccm_offset eV at every step, as before.
        concurrent_settled: a step holds max(0, dwell - K move) s settled.
        """
        lo = self.edge_k - 20.0 if lo is None else lo
        hi = self.edge_k + 30.0 if hi is None else hi
        lo, hi = fit_window(lo, hi, step)
        pos = [float(p) for p in grid(lo, hi, step)]
        approach = pos[0] - step
        if reverse:
            pos, approach = pos[::-1], pos[-1] + step
        approach = float(check_on_list([approach])[0])
        pink = dccm_offset is None
        opts = self.xrt_opts()
        on_center = isinstance(dccm_offset, str)
        if on_center and dccm_offset != 'center':
            raise ValueError("dccm_offset must be None, 'center' or eV from the K request")
        if pink:
            offsets = None
        elif on_center:
            offsets = self._center_offsets([0.0])
        else:
            offsets = [float(o) for o in np.atleast_1d(dccm_offset)]
            opts['dccm_from_center'] = False
        sample = f"{PREFIX}_fe_foil_{lo:.0f}_{hi:.0f}_{step:g}eV".replace('.', 'p')
        if reverse:
            sample += "_down"
        if pink:
            beam = "pink, DCCM out"
        elif on_center:
            sample += "_dccm_center"
            beam = f"DCCM in, DCCM on the SASE center ({self._cal_state(short=True)})"
        else:
            sample += "_dccm" + "_".join(f"{o:+g}" for o in offsets).replace('.', 'p')
            beam = f"DCCM in, DCCM = K {', '.join(f'{o:+g}' for o in offsets)} eV"
        run = _next_run(record)
        msg = (f"Fe foil scan run {run}: {beam}, K {pos[0]:.1f} -> {pos[-1]:.1f} eV "
               f"in {step:g} eV ({len(pos)} steps), {K_MODE}, dwell {dwell:g} s, "
               f"dead band {self.db_um:g} um")
        _post(msg, tag='fe_foil') if record else print(msg)
        exafs = _ns('exafs')
        request_k(exafs.acr_energy_k, approach, k_max=ut.K_MAX_EV)
        out = exafs.k_xas_scan(
            k_positions=pos, k_order='given', k_move_mode=K_MODE,
            dwell_time=dwell, pink=pink, dccm_offsets=offsets, record=record,
            sample=sample, picker='open', **opts)
        if record:
            _post(f"Fe foil scan run {run} done, {len(out)} points", tag='fe_foil',
                  run=run)
        return out

    # ---- DCCM fly test (21:00-22:00) -------------------------------------------

    def _dccm_in(self):
        """False only if the DCCM state readback says OUT; unreadable warns."""
        state = _caget(DCCM_STATE_RBV, as_string=True)
        if state is None:
            logger.warning(f"DCCM state not readable ({DCCM_STATE_RBV}): check the "
                           f"DCCM screen; going on")
            return True
        if 'OUT' in str(state).upper():
            print(f"DCCM reads {state}: put it in first (_ns('dccm').insert(), "
                  f"or x.mono()), then repeat")
            return False
        return True

    def fly(self, pattern='track', step=FLY_STEP_EV, n=FLY_N, dwell=FLY_DWELL_S,
            lo=None, hi=None, reverse=False, record=True):
        """
        DCCM points while the undulator moves (fly scan), on the Fe foil.

        K steps of step eV over x.edge_k - 20 .. x.edge_k + 20 (clipped), in
        'concurrent' mode: each K write goes out and the DCCM steps through
        n points of dwell s while the girders move. 'track' takes the DCCM
        from the old SASE center to the new one (-4..0 eV from the new
        center for +5 eV, +4..0 going down); 'center' puts the points
        symmetric around the new center (-2..+2 eV). The center is the
        calibrated one with x.sase_on(), else K request + x.offset_eV, so
        the points sit on the real SASE energy. The scan waits for each
        K request to finish before the next write (the hold-off that keeps it
        from running ahead), so a step takes max(n x (dwell + ~1.4 s DCCM
        move), K move): ~22 s at the defaults against an ~11-12 s K move,
        so the first 2-3 points fall inside the move. The per-point CSV
        (runNNNN_points.csv) tags each point. XRT tracking per x.xrt_track
        (crystal moved non-blocking before each K write, checked after K done),
        camera-arm tracking off. Refuses if the DCCM state readback reads
        OUT; runs with a warning if that PV does not answer.
        """
        if not self._dccm_in():
            return None
        pos, approach = fly_positions(self.edge_k, step, lo, hi, reverse)
        off = fly_offsets(pattern, step, n, going_up=not reverse)
        dccm_offsets = self._center_offsets(off)
        opts = self.xrt_opts()
        opts['track_feespec_cam'] = False
        sample = (f"{PREFIX}_fly_{pattern}_{min(pos):.0f}_{max(pos):.0f}_{step:g}eV_"
                  f"{n}x{dwell:g}s").replace('.', 'p')
        if reverse:
            sample += '_down'
        if opts['track_feespec']:
            sample += '_xrt'
        per_step = n * (dwell + 1.4)
        run = _next_run(record)
        msg = (f"fly scan run {run}: '{pattern}', K {pos[0]:.1f} -> {pos[-1]:.1f} eV "
               f"in {step:g} eV ({len(pos)} positions), DCCM offsets {off} eV from the "
               f"new SASE center ({self._cal_state(short=True)}), {dwell:g} s each, "
               f"~{per_step:.0f} s of DCCM points per step, dead band {self.db_um:g} um")
        _post(msg, tag='fly') if record else print(msg)
        exafs = _ns('exafs')
        request_k(exafs.acr_energy_k, approach, k_max=ut.K_MAX_EV)
        out = exafs.k_xas_scan(
            k_positions=pos, k_order='given', k_move_mode='concurrent',
            dccm_offsets=dccm_offsets, dwell_time=dwell, record=record,
            sample=sample, picker='open', **opts)
        if record:
            _post(f"fly scan run {run} done, {len(out)} DCCM points", tag='fly', run=run)
        return out

    def fly_ref(self, step=FLY_STEP_EV, dwell=None, points=False, pattern='track',
                n=FLY_N, lo=None, hi=None, reverse=False, record=True):
        """
        Reference for the fly scan, same K grid, K settled.

        points=False (F0): concurrent_settled with one DCCM point at the K
        center (calibrated with x.sase_on(), else K request + x.offset_eV).
        The DCCM moves to the new center
        after K done and the XRT check; the dwell (20 s by default) counts
        from the K write, so ~7 s per step sit at the new center with K
        settled. The timing CSV marks the dwell start (t_dwell_start).
        points=True (F4): the same n DCCM points as x.fly(pattern), all
        taken after K settles: pause mode (DAQ paused during the K move), so
        every point gets its full dwell (3 s by default).
        """
        if not self._dccm_in():
            return None
        pos, approach = fly_positions(self.edge_k, step, lo, hi, reverse)
        if points:
            dwell = FLY_DWELL_S if dwell is None else dwell
            off = fly_offsets(pattern, step, n, going_up=not reverse)
            mode = 'pause'
        else:
            dwell = FLY_REF_DWELL_S if dwell is None else dwell
            off = [0.0]
            mode = K_MODE
        dccm_offsets = self._center_offsets(off)
        opts = self.xrt_opts()
        opts['track_feespec_cam'] = False
        kind = f"points_{pattern}" if points else "center"
        sample = (f"{PREFIX}_flyref_{kind}_{min(pos):.0f}_{max(pos):.0f}_{step:g}eV_"
                  f"{dwell:g}s").replace('.', 'p')
        if reverse:
            sample += '_down'
        if opts['track_feespec']:
            sample += '_xrt'
        run = _next_run(record)
        msg = (f"fly reference run {run}: {kind}, K {pos[0]:.1f} -> {pos[-1]:.1f} eV "
               f"in {step:g} eV, DCCM offsets {off} eV from the K center, {mode}, "
               f"dwell {dwell:g} s, dead band {self.db_um:g} um")
        _post(msg, tag='fly') if record else print(msg)
        exafs = _ns('exafs')
        request_k(exafs.acr_energy_k, approach, k_max=ut.K_MAX_EV)
        out = exafs.k_xas_scan(
            k_positions=pos, k_order='given', k_move_mode=mode,
            dccm_offsets=dccm_offsets, dwell_time=dwell, record=record,
            sample=sample, picker='open', **opts)
        if record:
            _post(f"fly reference run {run} done, {len(out)} DCCM points", tag='fly',
                  run=run)
        return out

    # ---- pink beam, MESH, myoglobin --------------------------------------------

    def pink_switch(self, att_t=1e-2):
        """
        Mono to pink: attenuate, DCCM out, XRT parked at CENTER_EV.

        Removing the DCCM raises the flux on every downstream detector by
        about two orders of magnitude, hence the attenuator first: the DCCM
        stays in unless the attenuator reads at most att_t (x2 for filter
        steps). Never raises the transmission.
        """
        att = _ns('att')
        t = min(float(att.position), float(att_t))
        att(t, wait=True)
        if float(att.position) > 2.0 * t:
            raise RuntimeError(f"attenuator reads {att.position:.1e}, not {t:.1e}: "
                               f"DCCM left in")
        _ns('dccm').remove()
        self.xrt_park(CENTER_EV)
        print(f"Pink beam. Confirm on the DCCM screen and by the DG1/DG2 IPM jump. "
              f"xrt_track = {self.xrt_track}.")

    def mesh_status(self):
        """Print MESH setpoint and readback (V) and the hutch door state."""
        sp, rb = _caget(MESH_SP), _caget(MESH_RB)
        door = _caget(DOOR_PV, as_string=True)
        sp_v = None if sp is None else float(sp) * MESH_SCALE_V
        rb_v = None if rb is None else float(rb) * MESH_SCALE_V
        fmt = lambda v: '?' if v is None else f"{v:.0f} V"
        print(f"MESH setpoint {fmt(sp_v)} ({MESH_SP}), readback {fmt(rb_v)} "
              f"({MESH_RB}), door {door} ({DOOR_PV})")
        return dict(sp_v=sp_v, rb_v=rb_v, door=door)

    def mesh_set(self, kv, ramp_v=250.0, step_s=1.0, max_kv=MESH_MAX_KV, tol_v=150.0):
        """
        Ramp the MESH high voltage to kv (kilovolts) in ramp_v steps.

        The SED MESH lead decides the value. Refuses above max_kv, refuses a
        nonzero kv unless the hutch door reads closed (DOOR_PV = 1), and
        refuses to start when setpoint and readback disagree by more than
        tol_v (a trip: x.mesh_off() first). Waits step_s at each step and
        stops, leaving the setpoint where it is, if the readback is more
        than tol_v from the setpoint, the door opens (setpoint to 0), or
        someone else wrote the setpoint (the door watcher). Returns True
        when the target is reached. x.mesh_off() goes to 0 without any of
        these checks.
        """
        if abs(kv) > max_kv + 1e-9:
            raise ValueError(f"{kv} kV above the {max_kv} kV limit, not set")
        target = float(kv) * 1000.0
        if target and not _door_closed():
            raise RuntimeError(f"hutch door {DOOR_PV} does not read closed (1): HV not set")
        sp, rb = _caget(MESH_SP), _caget(MESH_RB)
        if sp is None:
            raise RuntimeError(f"MESH setpoint {MESH_SP} not readable, not set")
        v0 = float(sp) * MESH_SCALE_V
        if rb is not None and abs(float(rb) * MESH_SCALE_V - v0) > tol_v:
            raise RuntimeError(f"MESH setpoint {v0:.0f} V and readback "
                               f"{float(rb) * MESH_SCALE_V:.0f} V disagree (trip?): "
                               f"x.mesh_off() first")
        from epics import caput
        n = max(1, int(np.ceil(abs(target - v0) / ramp_v)))
        rb_v, last = None, v0
        for v in np.linspace(v0, target, n + 1)[1:]:
            now = _caget(MESH_SP)
            if now is None or abs(float(now) * MESH_SCALE_V - last) > 5.0:
                _post(f"MESH ramp stopped: setpoint changed outside mesh_set "
                      f"({'?' if now is None else f'{float(now) * MESH_SCALE_V:.0f} V'}, "
                      f"last written {last:.0f} V)", tag='mesh')
                return False
            if target and not _door_closed():
                caput(MESH_SP, 0.0, wait=True)
                _post("MESH ramp stopped, hutch door not closed: setpoint 0", tag='mesh')
                return False
            caput(MESH_SP, v / MESH_SCALE_V, wait=True)
            last = v
            time.sleep(step_s)
            rb = _caget(MESH_RB)
            rb_v = None if rb is None else float(rb) * MESH_SCALE_V
            if rb_v is None or abs(rb_v - v) > tol_v:
                _post(f"MESH ramp stopped at setpoint {v:.0f} V: readback "
                      f"{'?' if rb_v is None else f'{rb_v:.0f} V'} (tolerance "
                      f"{tol_v:.0f} V). Call the SED MESH lead.", tag='mesh')
                return False
        _post(f"MESH HV {target:.0f} V, readback {rb_v:.0f} V", tag='mesh')
        return True

    def mesh_off(self, timeout_s=30.0):
        """
        Write 0 V to the MESH setpoint at once and wait for the readback.

        No ramp and no readback check before the write, so it works after a
        trip or with the setpoint unreadable. Returns True once the setpoint
        reads 0 and the readback is under 50 V within timeout_s.
        """
        from epics import caput
        caput(MESH_SP, 0.0, wait=True)
        rb_v, t_end = None, time.time() + timeout_s
        while time.time() < t_end:
            sp, rb = _caget(MESH_SP), _caget(MESH_RB)
            rb_v = None if rb is None else float(rb) * MESH_SCALE_V
            if sp is not None and abs(float(sp)) < 1e-6 and rb_v is not None                     and abs(rb_v) < 50.0:
                _post(f"MESH off, readback {rb_v:.0f} V", tag='mesh')
                return True
            time.sleep(0.5)
        _post(f"MESH off NOT confirmed after {timeout_s:.0f} s: setpoint written 0, "
              f"readback {'?' if rb_v is None else f'{rb_v:.0f} V'}. Call the SED MESH "
              f"lead.", tag='mesh')
        return False

    def mb_grid(self, step=MB_STEP_EV):
        """Production sweep x.edge_k - 15 -> x.edge_k + 35 -> x.edge_k - 15 eV."""
        return mb_positions(self.edge_k, step)

    def _context(self):
        """MESH, attenuation, dead band and offsets for the elog line of a run."""
        sp, rb = _caget(MESH_SP), _caget(MESH_RB)
        mesh = (f"MESH SP {float(sp) * MESH_SCALE_V:.0f} V RB "
                f"{float(rb) * MESH_SCALE_V:.0f} V" if sp is not None and rb is not None
                else "MESH ?")
        try:
            att = f"att {_ns('att').position:.1e}"
        except Exception:
            att = "att ?"
        rb_db = ut.deadband_text(ut.read_deadband(timeout=0.5))
        return (f"{mesh}, {att}, dead band {self.db_um:g} um recorded ({rb_db}), XRT "
                f"tracking {'on' if self.xrt_track else 'off'}, "
                f"{self._cal_state(short=True)}, edge K {self.edge_k:.1f} eV")

    def _pink_run(self, pos, dwell, sample, what, record=True):
        exafs = _ns('exafs')
        run = _next_run(record)
        msg = (f"{what} run {run}: {self._context()}. K {pos[0]:.1f} eV start, "
               f"{min(pos):.1f}-{max(pos):.1f} eV, {len(pos)} visits, dwell {dwell:g} s, "
               f"{K_MODE}, pink")
        _post(msg, tag='mb_mesh') if record else print(msg)
        request_k(exafs.acr_energy_k, pos[0], k_max=ut.K_MAX_EV)
        out = exafs.k_xas_scan(
            k_positions=pos, k_order='given', k_move_mode=K_MODE,
            dwell_time=dwell, pink=True, record=record, sample=sample,
            picker='open', **self.xrt_opts())
        if record:
            _post(f"{what} run {run} done, {len(out)} points", tag='mb_mesh', run=run)
        return out

    def mb_blank(self, label, step=5.0, dwell=20.0, record=True):
        """
        Mother-liquor blank pass on the MESH (no crystals), pink.

        'start' before the first Mb reservoir, 'end' after the last: beam
        and stream background, sigma(T/I0), epix100 and JF16M background.
        """
        pos = mb_positions(self.edge_k, step)
        return self._pink_run(pos, dwell, f"{PREFIX}_mb_mesh_blank_{label}",
                              f"MESH blank '{label}'", record)

    def mb_park(self, r, k=None, dwell=MB_PARK_DWELL_S, record=True):
        """
        Mb reservoir r with K parked (default x.edge_k + 10 eV), one run.

        Hit rate, indexing, emission per hit against the blank, first
        hit-minus-miss transmission. Then the go/no-go table.
        """
        k = self.edge_k + MB_PARK_ABOVE_EV if k is None else k
        k = float(check_on_list([k])[0])
        return self._pink_run([k], dwell, f"{PREFIX}_mb_mesh_park_r{r}_k{k:.0f}",
                              f"Mb park (reservoir {r})", record)

    def mb_pass(self, n, r, step=MB_STEP_EV, dwell=MB_DWELL_S, updown=True,
                record=True):
        """
        Production pass n on reservoir r: sweep up and down, 30 s per visit.

        One call is one DAQ run, so reservoir changes, clog clears and HV
        changes fall between calls. ~21 min at 2.5 eV for edge 7080 eV.
        updown=False goes up only (21 visits, ~11 min). Rerun an aborted
        pass with the same n.
        """
        pos = mb_positions(self.edge_k, step)
        if not updown:
            pos = pos[:pos.index(max(pos)) + 1]
        return self._pink_run(pos, dwell, f"{PREFIX}_mb_mesh_P{n}_r{r}",
                              f"Mb pass P{n} (reservoir {r})", record)

    def mb_edge(self, n, r, edge_eV=None, half=30.0, step=5.0, dwell=MB_DWELL_S,
                updown=False, record=True):
        """
        Pass n on reservoir r over the real edge +- half eV in step eV, pink.

        edge_eV is a real photon energy, default x.real(x.edge_k) (the foil
        edge as set tonight). Each K point is x.k_for(real): the calibrated
        inverse with x.sase_on(), else real - x.offset_eV, rounded to the
        list step; points off the loaded list or above the cap are dropped
        with a warning. Goes up only by default (13 points at 30 s, ~7 min);
        updown=True sweeps up and back in one DAQ run.
        """
        edge = self.real(self.edge_k) if edge_eV is None else float(edge_eV)
        lo, hi, l_step = list_bounds()
        offs = np.arange(-half, half + step / 2, step)
        k_all = [self.k_for(edge + o, check=False) for o in offs]
        k_pts = [k for k in k_all if lo - 1e-6 <= k <= hi + 1e-6]
        if len(k_pts) < len(k_all):
            logger.warning(f"edge pass clipped to {len(k_pts)} of {len(k_all)} points "
                           f"by the list or cap ({lo:.1f}-{hi:.1f} eV K)")
        if len(k_pts) < 2:
            raise ValueError(f"edge {edge:.1f} eV +- {half:g} eV does not fit the loaded "
                             f"list {lo:.1f}-{hi:.1f} eV K ({self._cal_state(short=True)})")
        check_on_list(k_pts)
        pos = k_pts + k_pts[-2::-1] if updown else k_pts
        print(f"edge pass: real {self.real(k_pts[0]):.1f}-"
              f"{self.real(k_pts[-1]):.1f} eV around {edge:.1f} eV, K "
              f"{k_pts[0]:.1f}-{k_pts[-1]:.1f} eV in {step:g} eV, {len(pos)} visits")
        return self._pink_run(
            pos, dwell, f"{PREFIX}_mb_mesh_edge_P{n}_r{r}",
            f"Mb edge pass P{n} (reservoir {r}), real edge {edge:.1f} eV +- {half:g} eV",
            record)

    def _close_beam(self, timeout=10.0):
        """Close the pulse picker and set att(0); True once either is confirmed."""
        from mfx.db import mfx_pulsepicker
        att = _ns('att')
        mfx_pulsepicker.close()
        att(0)
        t_end = time.time() + timeout
        while time.time() < t_end:
            try:
                # att(0) reads back ~1e-76, not exactly 0
                if mfx_pulsepicker.position == 'CLOSED' or att.position < 1e-9:
                    return True
            except Exception as e:
                logger.warning(f'beam state read failed: {e}')
            time.sleep(0.2)
        return False

    # ---- transfocator -------------------------------------------------------

    def tfs_combo(self):
        """
        Print the lens combination and the per-lens radii.

        Prefocus OUT, TFS 04 + 05 + 06 IN (10-26 stack, confirm at 18:00),
        all other lenses out. Reads each lens :RADIUS PV so the elog has the
        actual stack, then checks the combined radius against TFS_R_UM.
        """
        tfs = _ns('tfs')
        print(f"Prefocus (MFX:DIA:XFLS) OUT. TFS lenses {list(TFS_LENSES)} IN, "
              f"others OUT. R_eff {TFS_R_UM} um, z ~{TFS_Z_MM} mm at {TFS_E_EV} eV "
              f"(196.5 mm at 7100, 158.8 mm at 7130), DOF +/-{TFS_DOF_MM} mm.")
        r = {}
        for n in range(2, 11):
            lens = getattr(tfs, f'tfs_{n:02d}')
            try:
                r[n] = float(lens.radius)
            except Exception:
                r[n] = float('nan')
            mark = '<-' if n in TFS_LENSES else ''
            print(f"  TFS {n:02d}  R {r[n]:8.1f} um  {mark}")
        r_eff = 1.0 / sum(1.0 / r[n] for n in TFS_LENSES)
        print(f"  1/sum(1/R) for {list(TFS_LENSES)}: {r_eff:.1f} um")
        if abs(r_eff - TFS_R_UM) > 1:
            logger.warning(f"lens radii give {r_eff:.1f} um, not {TFS_R_UM} um: "
                           f"rerun tfs.find_best_combo before inserting")
        return r

    def tfs_prep(self):
        """Prefocus out, TFS stage to 100 mm, check the 4,5,6 combination."""
        tfs = _ns('tfs')
        _ns('crl1').remove()
        tfs.remove_all()
        tfs.translation.umv(100)
        tfs.try_combo(energy=TFS_E_EV, prefocus=None, tfs=list(TFS_LENSES))
        tfs.find_best_combo(energy_eV=TFS_E_EV, enable_prefocus=False,
                            avoid_forbidden=True)

    def tfs_insert(self, z=TFS_Z_MM):
        """Insert lenses 4, 5, 6 and move the stage to z (mm)."""
        tfs = _ns('tfs')
        for n in TFS_LENSES:
            getattr(tfs, f'tfs_{n:02d}').insert()
        tfs.translation.umv(z)
        inserted = [n for n in range(2, 11) if getattr(tfs, f'tfs_{n:02d}').inserted]
        try:
            r_eff = float(tfs.tfs_radius.get())
        except Exception:
            r_eff = float('nan')
        print(f"TFS lenses in: {inserted}, effective radius {r_eff:.1f} um "
              f"(want {list(TFS_LENSES)}, {TFS_R_UM} um), z {tfs.translation.position:.2f} mm. "
              f"Check DG2 centroid and DG2 IPM ratio lenses in/out (~0.2).")
        if inserted != list(TFS_LENSES) or abs(r_eff - TFS_R_UM) > 1:
            logger.warning("TFS stack is not 04,05,06 alone: check the TFS screen "
                           "before putting beam on the YAG")

    def tfs_zscan(self, z=None, image_sec=3.0, cam_pv=IP_CAM, tag='coarse',
                  min_sum_frac=0.3):
        """
        Transfocator z scan on the IP YAG; returns (z, fwhm_x_px, fwhm_y_px).

        At each z: move, average camera frames for image_sec (at least 10),
        fit Gaussians to the x and y projections inside the Cross1/Cross2
        markers. Points whose summed image falls below min_sum_frac of the
        scan median are rejected as beam-off (pulse picker or lens interlock).
        Prints the waist from fit_waist(), saves a CSV and a PNG in the
        results folder and stores the result in x.last_zscan.

        transfocator_aligner.fit_scan uses exp(-((x-m)/(4 s))**2), so the
        FWHM is 8 sqrt(ln 2) |s| = 6.66 |s|, not 2.355 |s|.
        """
        import matplotlib.pyplot as plt
        from tfs.transfocator_scan import transfocator_aligner
        tfs = _ns('tfs')
        z = TFS_COARSE if z is None else np.asarray(z, float)
        cam = transfocator_aligner(cam_pv)
        k = 8 * np.sqrt(np.log(2))
        rows = []
        for pos in z:
            tfs.translation.umv(pos)
            # running sum keeps memory at one frame however long image_sec is
            total, n_frames, t_end = None, 0, time.time() + image_sec
            while time.time() < t_end or n_frames < 10:
                frame = np.asarray(cam.get_image_roi(), float)
                total = frame if total is None else total + frame
                n_frames += 1
            img = total / n_frames
            cam.active_image = img - img.min()
            px, py = cam.get_projections()
            sx = abs(cam.fit_scan(np.arange(len(px)), px)[2]) * k
            sy = abs(cam.fit_scan(np.arange(len(py)), py)[2]) * k
            rows.append((pos, sx, sy, float(img.sum()), float(img.max())))
            # a flat-topped peak near the waist means the YAG camera saturates:
            # FWHM then stops shrinking and the waist fit is biased wide
            print(f"  z {pos:7.2f}  fwhm x {sx:7.1f} px  y {sy:7.1f} px  "
                  f"peak {img.max():8.0f}")
        r = np.array(rows)
        # fit_scan returns zeros on a failed fit
        bad = (r[:, 3] < min_sum_frac * np.median(r[:, 3])) | (r[:, 1] == 0) | (r[:, 2] == 0)
        r[bad, 1:3] = np.nan
        zx, zy = fit_waist(r[:, 0], r[:, 1]), fit_waist(r[:, 0], r[:, 2])
        zmin = np.nanmean([zx, zy])
        out = _results_dir() / f"tfs_zscan_{tag}_{time.strftime('%H%M%S')}"
        np.savetxt(f"{out}.csv", r, delimiter=',',
                   header='z_mm,fwhm_x_px,fwhm_y_px,image_sum,peak', comments='')
        fig, ax = plt.subplots(figsize=(6, 3.5))
        ax.plot(r[:, 0], r[:, 1], 'o-', label=f'x, waist {zx:.1f} mm')
        ax.plot(r[:, 0], r[:, 2], 's-', label=f'y, waist {zy:.1f} mm')
        ax.set_xlabel('TFS z (mm)')
        ax.set_ylabel('FWHM (px)')
        ax.legend()
        ax.set_title(f'TFS {TFS_LENSES} z scan ({tag}), {cam_pv}')
        fig.tight_layout()
        fig.savefig(f"{out}.png")
        plt.show(block=False)
        self.last_zscan = r
        msg = (f"TFS z scan {tag}: lenses {TFS_LENSES}, {len(z)} points "
               f"{z.min():.1f}-{z.max():.1f} mm, {int(bad.sum())} rejected. "
               f"Waist x {zx:.1f} mm, y {zy:.1f} mm, mean {zmin:.1f} mm "
               f"(expected {TFS_Z_MM:.0f}). {out}.csv")
        _post(msg, tag='tfs')
        if abs(zmin - TFS_Z_MM) > 15:
            print("Waist more than 15 mm from 177 mm: recheck the photon energy "
                  "(x.offset_check) before trusting either number.")
        return r[:, 0], r[:, 1], r[:, 2]

    def tfs_fine(self, zmin, half=12.0, step=1.5, image_sec=4.0, cam_pv=IP_CAM):
        """Fine z scan, zmin +- half in step mm."""
        return self.tfs_zscan(np.arange(zmin - half, zmin + half + 0.01, step),
                              image_sec=image_sec, cam_pv=cam_pv, tag='fine')

    def tfs_park(self, z):
        """Move the stage to the measured waist and remember it."""
        _ns('tfs').translation.umv(z)
        self.tfs_zmin = float(z)
        _post(f"TFS parked at {z:.2f} mm (lenses {TFS_LENSES}, {TFS_E_EV:.0f} eV)",
              tag='tfs')

    def tfs_pink_check(self, image_sec=4.0, cam_pv=IP_CAM):
        """Three-point z check in pink beam around x.tfs_zmin, then park there."""
        z0 = self.tfs_zmin
        out = self.tfs_zscan([z0 - 10, z0, z0 + 10], image_sec=image_sec,
                             cam_pv=cam_pv, tag='pink3')
        _ns('tfs').translation.umv(z0)
        return out

    def tfs_minder(self):
        """Hold the lenses on their y setpoints. Blocks; run in a second mfx3."""
        return _ns('tfs').lens_minder(lenses=TFS_LENSES)

    # ---- geometry ------------------------------------------------------------

    def geom_rings(self, det_dist_mm, calibrant='LaB6', energy_eV=TFS_E_EV):
        """Calibrant ring radii for the chosen JF16M distance (LaB6 or AgBe)."""
        geom_rings(det_dist_mm, calibrant, energy_eV)

    def geom_run(self, det_dist_mm, calibrant='LaB6', run_length=60, att_t=None,
                 record=True):
        """
        Geometry run on the JF16M (DCCM in, TFS focused), calibrant at the IP.

        Detector at its final distance for the night. Sets the attenuator if
        att_t is given, prints the expected rings, then one geomrun (tag
        geom). Analysis: BayFAI / pyFAI with the same calibrant and the DCCM
        energy. Redo it if the detector moves (10-26: moved ~25 mm after
        the calibration).
        """
        geom_rings(det_dist_mm, calibrant)
        if att_t is not None:
            # wait: geomrun opens the pulse picker at once
            _ns('att')(att_t, wait=True)
        _ns('geomrun')(run_length=run_length, record=record, runs=1, picker='open')
        _post(f"{calibrant} geometry run: JF16M at {det_dist_mm} mm (nominal), "
              f"DCCM {TFS_E_EV:.1f} eV, TFS {TFS_LENSES} at {self.tfs_zmin:.1f} mm, "
              f"att {att_t}", tag='geom')


# ---- procedures --------------------------------------------------------------

_PROC = {
    'deadband': """
Dead band test with ACR, 19:00-21:00. Fe foil in, DCCM out, pink, XRT tracking on.
ACR / undulator controls change USEG:UNDH:XX50:DeadbandHgEnc; MFX only asks and
records. After EVERY change: x.deadband(um) (shift log line with time and value).
 D0 x.db_baseline()            band as found (expect 0.125 um), list on, 1 eV up, 12 steps
 D1 ask 0.75 um, x.deadband(0.75), x.db_scan()     1 eV, 10 up + 9 down, ~4-6 min
 D2 ask 0.5 um,  x.deadband(0.5),  x.db_scan()
 D3 chosen band (0.5, or 0.625 if 0.5 shows slow steps): x.db_scan(step=0.5)
 D4 optional, only if the listener can run without the list, same band:
    x.db_scan(label='nolist')
 D5 x.db_table(): narrowest band that passes. It stays for the night; ACR
    restores 0.125 um when the energy GUI closes at 06:00.
 Pass rule per leg (printed after each run): real-step median <= 12.5 s, at most
 one slow step (> 15 s) per 40, at most one leading null request, none after.
 Ask during the block: the listener timing log for one step (the ~4 s unlabeled
 block, the ~6.9 s before the girders move), archiving DeadbandHgEnc, and whether
 the energy GUI can set the band and always restore 0.125 um on close.
""",
    'fly': """
DCCM fly test, 21:00-22:00, Fe foil, chosen dead band. DCCM IN (x.mono(7115) or
dccm.insert()), DCCM energy from hutch python only. x.offset_eV measured first.
 F0 x.fly_ref()                 DCCM at the K center, 5 eV K steps, 15 s
 F1 x.fly('track')              5 points, old -> new center (-4..0 eV), 3 s each
 F2 x.fly('center')             5 points around the new center (-2..+2 eV)
 F3 x.fly('track', reverse=True)  same going down (+4..0 eV)
 F4 x.fly_ref(points=True)      same 5 points, K settled (pause mode), 3 s each
 A step takes max(5 x (3 s + ~1.4 s), K move) ~ 22 s: points 1-3 in the move.
 Look at: runNNNN_points.csv (in move vs settled per point), flux per point
 against the offset from the SASE centroid, foil spectrum in move vs reference,
 DCCM readback within each dwell, per-shot I0 after the DCCM.
""",
    'mesh': """
MESH myoglobin, pink, from 22:00. The SED MESH lead runs the MESH.
 1. x.pink_switch(); Fe foil out; x.mesh_status() (0 V reads 0 V, door state).
 2. Mother liquor (no crystals) loaded; SED MESH lead sets the HV: x.mesh_set(kv)
    (ramps, refuses above 5 kV, stops if the readback drifts). Jet on the beam.
 3. Attenuation chosen and kept for the night (quick_att_scan if needed).
 4. x.mb_blank('start')
 5. Reservoir 1: x.mb_park(r=1) (900 s), then the go/no-go table in the plan.
 6. x.mb_pass(n, r) per pass, one DAQ run each; reservoir changes, clog clears
    and HV changes between calls only. Rerun an aborted pass with the same n.
 7. x.mb_blank('end'), x.mesh_off(), capillary flush (SED MESH lead).
 If the HV trips or arcs: x.mesh_off(), close the beam, call the SED MESH lead.
""",
    'xrt': """
XRT (FEE) spectrometer, Si(111), tracking ON tonight (report rec 12)
 1. Filter wheel STEP:XRT1:446:MOTR.RBV as expected. DCCM in: x.mono(7117.5).
 2. x.xrt_park(); CamViewer fee_spec, mono line on the sensor.
 3. x.xrt_tune(+-0.05) until the line sits at the image center column.
 4. Optional: x.spec_calib(), then x.spec_calib_output('user'), spec_window(...).
 x.xrt_on() / x.xrt_off() switch tracking for every scan; x.xrt_check() after a
manual move. Do not calibrate the XRT on the DCCM and then trust it in SASE
without a check: the DCCM shifts the pointing slightly.
Measured correction instead of step 3: x.procedure('calib').
""",
    'calib': """
SASE center and XRT calibration, DCCM in, Fe foil out, ~15 min. Run after the
dead band is chosen (the center moves with the band) and repeat after a band change.
 1. Beam at 7.1 keV, x.mono() (DCCM in), Zyla acquiring, att so DG2 is not saturated.
 2. x.sase_cal()       K edge-15..edge+35 in 10 eV, DCCM scan +-20 eV at each K, live
                       DG2/GDET, Gaussian center. Prints center-K per K and the fit:
                       'center = K +a +b x (K - Kref)'. Check: FWHM ~15-30 eV, resid
                       < ~2 eV (girder scatter at a wide band), slope b near 0 means a
                       constant offset was fine. Switched on (x.sase_on) when done.
                       x.sase_cal(direction='both') measures up and down steps apart.
 3. x.xrt_cal()        5 energies over the same range; at each the crystal is rocked
                       +-0.03 deg and solved for the line on the center column. Switched
                       on (x.xrt_cal_on). x.xrt_line() any time: line column vs target.
 4. x.cal_show()       both tables; files in results/shift_<date>/calib (json + png).
 From here every scan uses them: fly/fly_ref points sit on the calibrated center,
 x.fe_foil_scan(dccm_offset='center') follows it, x.mono(E)/x.k_for(E) invert it,
 XRT tracking goes to the calibrated center with the measured crystal angle.
 Drift during the night: x.sase_check() at the present K (DCCM in); rezero=True
 shifts the calibration by the measured difference. Pink check of the XRT: DCCM
 out, x.xrt_line() fits the SASE spectrum itself, expect a few px from target.
 After a reload: x.cal_load(). Back to constants: x.sase_off(), x.xrt_cal_off().
""",
    'tfs': """
TFS 04,05,06 z scan, no prefocus, DCCM in at 7115 eV (10-26 stack; confirm)
 1. Beam closed or att 1e-4. x.tfs_combo(); x.tfs_prep(); x.tfs_insert().
 2. Second mfx3: x.tfs_minder() and leave it running.
 3. IP YAG in, att 1e-3. Cross1/Cross2 around the spot.
 4. x.tfs_zscan(), x.tfs_fine(zmin), x.tfs_park(zmin).
 5. After DCCM out: x.tfs_pink_check().
""",
    'geom': """
JF16M geometry, LaB6 (the 10-26 calibrant; the elog said silver behenate)
 1. TFS parked, DCCM in at 7115 eV, calibrant at the IP plane, YAG out.
 2. x.geom_rings(D): >= 4 rings between the beamstop and the edge.
 3. x.geom_run(D, att_t=T). Redo it if the detector moves later in the night.
""",
}


# ---- checklists --------------------------------------------------------------

_CHECK_PRE = """
PRE-EXPERIMENT, short form (the plan PDF has the full list)
 code and controls (by 17:00)
 [ ] branch 1020945-undulator-1116 pulled and checked out on the operator machine;
     mfx3 restarted (or modules reloaded) so `x` is the 11-16 file; x.status() runs
 [ ] active experiment mfx102095027; results folder writable; kinit done
 [ ] x.dry_run() passes on the default list (grids clip until 18:00)
 [ ] python scripts/undulator_pv_check.py; epicsArch undulator include (~683 aliases)
 [ ] DCCM state PVs answer cainfo (SP1L0:DCCM:MMS:STATE:SET, :State:SET,
     :STATE:GET_RBV used by x.fly); DCCM energy from hutch python only
 [ ] mfx102095027 on the S3DF on-shift queue (pedestals waited ~30 min on 10-27)
 [ ] XRT tracking ON (x.xrt_track True, report rec 12); XRT filter wheel
     STEP:XRT1:446:MOTR.RBV read; Zyla acquiring (left on all night)
 ACR (before 18:00)
 [ ] list sent and confirmed in writing: 7040-7160 eV in 0.5 eV (241 points),
     highest K 7160 eV asked
 [ ] dead band test 19:00-21:00 agreed with the ACR machine physicist and undulator
     controls; DeadbandHgEnc archiving asked; the GUI restores 0.125 um on close
 [ ] 10-26 girder start times (19:30, 19:31 steps) read from the archiver
 [ ] x.db_read() at 18:00 before D0 (expect 0.125 um), again at 06:00
 MESH (hutch access 17:00-18:00, SED MESH lead)
 [ ] MESH horizontal at the XLJ IP; grounding; no metal inside the counter-electrode ring
 [ ] BNC jumpers at the wall panel; x.mesh_status(): 0 V written reads 0 V
 [ ] door watcher running; a door-open test zeroes the setpoint
 [ ] helium on flight tubes and cones only (the MESH chamber stays in air)
 [ ] shadowing checked on the JF16M, von Hamos and SEER lines of sight
 [ ] Mb microcrystals: volume, ammonium sulfate concentration, crystal size and form
     recorded; mother liquor (no crystals) for the blanks
 foil, XES, analysis
 [ ] Fe foil on the diagnostic stick at the YAG crosshair height; out-of-beam position known
 [ ] von Hamos untouched; epix100 ROIs defined; SEER crystal noted
 [ ] smalldata carries XRT and SEER projections, epix100 ROIs, IPMs, JF16M hits, BLD,
     SET2/AO805
 [ ] JF16M distance for the night fixed; geometry run in the DCCM-in hour if it changed
"""

_CHECK_POST = """
POST-EXPERIMENT
 at 06:00
 [ ] x.mesh_off() confirmed; MESH cleaned by the SED MESH lead
 [ ] ACR closes the energy GUI; x.db_read() shows 0.125 um on every segment
     (if not: ACR / undulator controls restore it before anyone leaves); x.deadband(0.125)
 [ ] Fe foil out of the beam path
 [ ] Ctrl+C lens_minder; TFS and DCCM state as the next shift needs
 [ ] camonitor log copied next to the timing CSVs; per-run elog lines complete
 [ ] active experiment and branch for the next shift
 within a day
 [ ] dead band tables (x.db_table()) and the chosen band to the machine side
 [ ] fly runs: points CSVs, in move vs settled, against the F0/F4 references
 [ ] Mb run list (passes, reservoirs, HV) to the analysis lead
 [ ] MESH notes for the 11-19 MESH user experiment
 [ ] plan and results into the notes once final
"""
