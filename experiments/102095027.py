"""
Experiment mfx102095027, shift 2026-10-26 18:00 to 10-27 06:00.

Undulator timing with the precomputed ACR energy list, 7.1 keV focus with
TFS 04,05,06 and no prefocus, silver behenate geometry, XRT and SEER
alignment (SEER on Ge(620) for this shift only), then pink-beam SFX + XES +
stochastic analysis on myoglobin from the HVE.

hutch-python loads this file when mfx102095027 is the active experiment and
exposes the User instance as `x` (and `user`). If another experiment is
active, load it by hand in mfx3:

    exec(open('experiments/102095027.py').read()); x = User()

Every method prints what it is about to do. Start with x.checklist_pre(),
x.status() and x.dry_run(). The shift plan PDF (shift_plan_20261026) gives
the order of the blocks and the decisions between them.
"""
import json
import logging
import os
import time
from pathlib import Path

import numpy as np

from mfx.undulator_timing import (acr_list, check_on_list, grid, sweep,
                                  window_ladder)

logger = logging.getLogger(__name__)

EXP = 'mfx102095027'

# ---- energies ---------------------------------------------------------------
# BLD photon energy = requested K energy + REQ_OFFSET_EV (measured 10-09)
REQ_OFFSET_EV = -5.2
# real photon energy the XRT and SEER images must cover in one frame: pink
# centroid 7099.8-7134.8 eV, +-10 eV SASE half width, +-2 sigma of 6 eV jitter
WINDOW_EV = (7080.0, 7155.0)
CENTER_EV = 7117.5
# FEE spectrometer crystal offset that centers the 7.1 keV spectrum
XRT_OFFSET_DEG = -1.3
XRT_NPX = 2048

# ---- transfocator -----------------------------------------------------------
TFS_LENSES = (4, 5, 6)          # legal without prefocus (December focus report)
TFS_R_UM = 58.8                 # effective radius of 04+05+06
TFS_E_EV = 7115.0               # center of the XANES window, real eV
TFS_Z_MM = 177.0                # expected waist at 7115 eV, -1.3 mm/eV
TFS_DOF_MM = 31.0
TFS_COARSE = np.arange(137.0, 218.1, 4.0)
# IP camera base PV; transfocator_aligner appends :IMAGE1:ArrayData.
# Unconfirmed: check before the shift which camera views the IP YAG.
IP_CAM = 'MFX:GIGE:LBL:01'

# ---- geometry calibrant ------------------------------------------------------
AGBE_D001_A = 58.38             # silver behenate long spacing
JF16M_HALF_MM = 0.075 * 4400 / 2
JF16M_BEAMSTOP_MM = 10.0

# ---- SEER --------------------------------------------------------------------
GE_A = 5.6579
HC = 12398.42
SEER_PARKER = {'z': 'MFX:USR:MMS:08', 'y': 'MFX:USR:MMS:09'}
SEER_SAVE = Path(os.path.expanduser('~/seer_positions'))
# Ge(660) at 9580 eV is the configuration of the 1019410 experiment shifts.
# Restore it after tonight.
SEER_HOME = {'hkl': (6, 6, 0), 'energy_eV': 9580.0}
SEER_TONIGHT = {'hkl': (6, 2, 0), 'energy_eV': CENTER_EV}

# ---- scan presets -------------------------------------------------------------
TIMING = {
    # name: (positions, mode, k_order, extra kwargs, sample, K before start)
    'T1': (lambda: grid(7100, 7120, 1), 'pause', 'ascending', {},
           'und1026_T1_pause_1eV', 7100.0),
    'T2': (lambda: grid(7100, 7120, 0.5), 'pause', 'ascending', {},
           'und1026_T2_pause_0p5eV', 7100.0),
    'T3': (lambda: window_ladder(6990), 'concurrent_settled', 'given', {},
           'und1026_T3_cs_ladder', 6990.0),
    'T4': (lambda: grid(7100, 7130, 0.5), 'concurrent_settled', 'random',
           {'seed': 1026}, 'und1026_T4_cs_random_0p5eV', None),
    'T5': (lambda: grid(7100, 7120, 1), 'concurrent_settled', 'ascending', {},
           'und1026_T5_cs_1eV', 7100.0),
}

PINK = {
    # name: (step eV or None for parked, dwell s, sample)
    'P0a': (2.5, 20, 'pink_P0a_beam_only_sweep2p5'),
    'P0b': (5.0, 20, 'pink_P0b_beam_only_sweep5'),
    'P1': (2.5, 20, 'pink_P1_carrier'),
    'P2': (None, 900, 'pink_P2_Mb_r1_park7120'),
    'P': (2.5, 30, 'pink_P{n}_Mb_r{r}'),
    'Pend': (2.5, 20, 'pink_Pend_carrier'),
}
PINK_LO, PINK_HI, PINK_PARK = 7105.0, 7140.0, 7120.0


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
    for folder in (Path(f'/sdf/data/lcls/ds/mfx/{EXP}/results/shift_20261026'),
                   Path(os.path.expanduser('~/shift_20261026'))):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            return folder
        except OSError as e:
            logger.warning(f'Cannot write {folder}: {e}')
    return Path('.')


def _post(msg, tag='shift_1026', run=None):
    print(msg)
    try:
        from mfx.db import elog
        elog.post(msg=msg, tags=tag, run=run)
    except Exception as e:
        logger.warning(f'elog post failed: {e}')


def bragg_deg(energy_eV, hkl, a=GE_A):
    """Bragg angle in degrees for a cubic crystal, a in Angstrom."""
    d = a / np.sqrt(sum(i * i for i in hkl))
    return float(np.degrees(np.arcsin(HC / (2 * d * energy_eV))))


def bragg_energy(theta_deg, hkl, a=GE_A):
    """Photon energy in eV reflected at theta_deg."""
    d = a / np.sqrt(sum(i * i for i in hkl))
    return float(HC / (2 * d * np.sin(np.radians(theta_deg))))


def seer_swap_table(radius_mm=250.0):
    """
    Print the Ge(660) to Ge(620) comparison used for the SEER swap.

    Dispersion is dtheta/dE = tan(theta)/E. The axial source-to-image
    distance 2R/tan(theta) assumes a von Hamos geometry with bending radius
    radius_mm; confirm the SEER geometry and the Ge(660) radius before using
    the mm column.
    """
    h0, e0 = SEER_HOME['hkl'], SEER_HOME['energy_eV']
    t0 = bragg_deg(e0, h0)
    disp0 = np.degrees(np.tan(np.radians(t0)) / e0)
    print(f"Ge{h0} at {e0:.0f} eV: theta {t0:.3f} deg, "
          f"{disp0:.4f} deg/eV, 2R/tan {2 * radius_mm / np.tan(np.radians(t0)):.1f} mm")
    h1 = SEER_TONIGHT['hkl']
    print(f"Ge{h1} at the Ge{h0} angle reflects {bragg_energy(t0, h1):.1f} eV")
    print(" E (eV)   theta    dtheta vs home   deg/eV   2R/tan (mm)")
    for e in (WINDOW_EV[0], 7100.0, CENTER_EV, 7130.0, WINDOW_EV[1]):
        t = bragg_deg(e, h1)
        print(f"{e:7.1f}  {t:7.3f}   {t - t0:+7.3f}        "
              f"{np.degrees(np.tan(np.radians(t)) / e):.4f}   "
              f"{2 * radius_mm / np.tan(np.radians(t)):6.1f}")
    span = bragg_deg(WINDOW_EV[0], h1) - bragg_deg(WINDOW_EV[1], h1)
    disp1 = np.degrees(np.tan(np.radians(bragg_deg(CENTER_EV, h1))) / CENTER_EV)
    print(f"Window {WINDOW_EV[0]:.0f}-{WINDOW_EV[1]:.0f} eV spans {span:.2f} deg "
          f"on Ge{h1}. Dispersion is {disp1 / disp0:.2f}x the Ge{h0} value, so a "
          f"detector window of N eV at {e0:.0f} eV covers N/{disp1 / disp0:.2f} eV tonight.")


def agbe_rings(det_dist_mm, energy_eV=TFS_E_EV, n_max=12):
    """
    Print silver behenate (00l) ring radii on the JF16M.

    Rings inside the 10 mm beamstop or beyond the detector edge are marked.
    Use the table to pick a detector distance with at least four orders on
    the sensor before the geometry run.
    """
    lam = HC / energy_eV
    print(f"AgBe d001 {AGBE_D001_A} A, {energy_eV:.1f} eV (lambda {lam:.4f} A), "
          f"JF16M at {det_dist_mm:.1f} mm")
    print("  l   2theta (deg)   r (mm)")
    for n in range(1, n_max + 1):
        s = lam * n / (2 * AGBE_D001_A)
        if s >= 1:
            break
        tth = 2 * np.arcsin(s)
        r = det_dist_mm * np.tan(tth)
        flag = ('  behind beamstop' if r < JF16M_BEAMSTOP_MM else
                '  off detector edge' if r > JF16M_HALF_MM else '')
        print(f"{n:3d}   {np.degrees(tth):10.3f}   {r:7.1f}{flag}")


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
    """Nearest K request on the ACR list for a real photon energy."""
    req = np.round((real_eV - offset_eV) * 2) / 2
    return float(check_on_list([req])[0])


# ---- the experiment object ----------------------------------------------------

class User:
    """Shift 2026-10-26 procedures. Call x.help() for the method list."""

    def __init__(self):
        # measured request-to-BLD offset; update after x.offset_check()
        self.offset_eV = REQ_OFFSET_EV
        # False once x.spec_calib() shows one XRT image covers WINDOW_EV
        self.xrt_track = True
        # crystal-only offset (tth does not follow); retune at 18:00 if the
        # spectrum is off center, then every scan below picks it up
        self.xrt_offset = XRT_OFFSET_DEG
        self.tfs_zmin = TFS_Z_MM
        self.last_zscan = None

    # ---- overview ---------------------------------------------------------

    def help(self):
        """Print the methods in shift order."""
        print("""
before beam   x.checklist_pre()  x.status()  x.dry_run()  x.seer_save('ge660')
18:00 align   x.mono(7115)  x.offset_check()  x.xrt_park()  x.spec_calib()
              x.seer_table()  x.seer_check()
19:00 timing  x.timing('T1') ... x.timing('T5')
21:00 focus   x.tfs_combo()  x.tfs_prep()  x.tfs_insert()  x.tfs_zscan()  x.tfs_fine(zmin)
              x.tfs_park(zmin)  x.agbe_rings(D)  x.agbe_run(D)  x.tfs_minder()
22:00 pink    x.pink_switch()  x.tfs_pink_check()  x.pink('P0a') ... x.pink('P', n=3, r=2)
06:00         x.checklist_post()  x.seer_restore('ge660') after the crystal swap back
""")

    def status(self):
        """Print K, done PV, DCCM, XRT, TFS, prefocus, attenuator and SEER state."""
        from epics import caget

        def show(label, fn):
            try:
                print(f"  {label:22s} {fn()}")
            except Exception as e:
                print(f"  {label:22s} ? ({e.__class__.__name__})")

        exafs, tfs = _ns('exafs'), _ns('tfs')
        print(f"experiment file {EXP}, offset {self.offset_eV:+.1f} eV, "
              f"xrt_track {self.xrt_track}, tfs_zmin {self.tfs_zmin:.1f} mm")
        show('K request (eV)', lambda: f"{exafs.acr_energy_k.get().setpoint:.1f}")
        show('done PV AO805', lambda: caget('SIOC:SYS0:ML07:AO805'))
        show('DCCM energy (keV)', lambda: f"{_ns('dccm').energy.position}")
        xs = _ns('xrtspec').hxrsss
        show('XRT th/tth/camy', lambda: f"{xs.th.position:.3f} / "
             f"{xs.tth.position:.3f} / {xs.camy.position:.3f}")
        show('XRT camera', lambda: caget('XRT:ZYLA:CAM:01:Acquire', as_string=True))
        show('TFS z (mm)', lambda: f"{tfs.translation.position:.2f}")
        show('TFS lenses in', lambda: [n for n in range(2, 11)
                                       if getattr(tfs, f'tfs_{n:02d}').inserted])
        show('prefocus', lambda: _ns('crl1').state.get())
        show('attenuator T', lambda: f"{_ns('att').position:.2e}")
        for k, pv in SEER_PARKER.items():
            show(f'SEER Parker {k}', lambda pv=pv: caget(pv + '.RBV'))

    def procedure(self, block=None):
        """Print the step list for 'xrt', 'seer', 'tfs', 'agbe' or 'pink'."""
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
        Simulate one timing scan and one pink pass, and print the lists.

        Moves nothing. Raises if any position is off the ACR list.
        """
        exafs = _ns('exafs')
        print(f"ACR list: {len(acr_list())} points")
        for name, (pos, *_rest) in TIMING.items():
            print(f"  {name}: {len(pos())} positions")
        print(f"  pink pass: {len(self.kx())} positions, "
              f"{self.kx()[0]:.1f}-{self.kx().max():.1f} eV requested")
        exafs.k_xas_scan(k_positions=window_ladder(6990), k_order='given',
                         dccm_offsets=[0], dwell_time=0.1, simulate=True)
        exafs.k_xas_scan(k_positions=self.kx(), k_order='given', pink=True,
                         k_move_mode='concurrent_settled', dwell_time=0.1,
                         simulate=True)

    # ---- alignment ----------------------------------------------------------

    def mono(self, real_eV=TFS_E_EV):
        """
        DCCM in and set to real_eV, K requested to the matching list point.

        Uses self.offset_eV, so run x.offset_check() first if the offset is
        in doubt. The DCCM moves on its own energy axis, not with the
        vernier.
        """
        k = k_for_real(real_eV, self.offset_eV)
        dccm = _ns('dccm')
        print(f"DCCM in, DCCM {real_eV:.1f} eV, K request {k:.1f} eV "
              f"(real {k + self.offset_eV:.1f})")
        dccm.insert()
        _ns('exafs').acr_energy_k.move(k)
        dccm.energy.move(real_eV / 1000.0, wait=True)

    def offset_check(self, k_points=(7120.0, 7100.0, 7140.0), dwell=2.0,
                     record=True):
        """
        Measure the request-to-real offset at three K requests.

        DCCM in. At each K the DCCM steps from -15 to +5 eV around the
        request. The DG2 IPM against DCCM energy peaks at the real SASE
        center; the BLD photon energy in the same run gives the BLD offset.
        About 5 min. Afterwards set x.offset_eV to the measured value
        (real = request + offset). If it differs from -5.2 eV by more than
        3 eV, x.kx() shifts the pink sweep.
        """
        _ns('dccm').insert()
        return _ns('exafs').k_xas_scan(
            k_positions=list(k_points), k_order='given', k_move_mode='pause',
            dccm_offsets=list(np.arange(-15.0, 5.1, 1.0)), dwell_time=dwell,
            crystal_angle_offset=self.xrt_offset, track_feespec=True,
            record=record, sample='und1026_offset_check')

    # ---- XRT spectrometer ---------------------------------------------------

    def xrt_park(self, real_eV=CENTER_EV, offset_deg=None):
        """
        Park the FEE (XRT) spectrometer at real_eV and restart the camera.

        move_feespec_energy stops the Zyla and leaves it stopped, so the
        camera is restarted here. Moves th, tth and camy together and backs
        off if XRT:HXS:TRNS.SEVR alarms. offset_deg defaults to x.xrt_offset.
        """
        from epics import caput
        offset_deg = self.xrt_offset if offset_deg is None else offset_deg
        xrt = _ns('xrtspec')
        xrt.move_feespec_energy(real_eV / 1000.0, crystal_angle_offset=offset_deg)
        caput('XRT:ZYLA:CAM:01:Acquire', 1)
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
        print(f"XRT th {xs.th.position:.3f}, x.xrt_offset {self.xrt_offset:+.3f} deg")

    def spec_calib(self, step=5.0, dwell=5.0, record=True):
        """
        DCCM-referenced energy calibration of XRT and SEER in one run.

        XRT stays parked (x.xrt_park() first) and SEER stays fixed. K and the
        DCCM step together across WINDOW_EV with the DCCM on the SASE center
        (DCCM = K request + self.offset_eV), so each step puts one narrow
        line on both cameras. 16 steps at 5 eV, ~7 min in pause mode.

        Analysis: centroid pixel per step on feespec/hproj (XRT, 2048 px)
        and the SEER epix100 ROI projection, against the DCCM energy. Feed
        two well-separated points to spec_window(). If the XRT window fits,
        set x.xrt_track = False so the pink passes keep one XRT energy axis
        for the whole data set.
        """
        lo = k_for_real(WINDOW_EV[0], self.offset_eV)
        hi = k_for_real(WINDOW_EV[1], self.offset_eV)
        _ns('dccm').insert()
        return _ns('exafs').k_xas_scan(
            k_positions=grid(lo, hi, step), k_order='given', k_move_mode='pause',
            dccm_offsets=[self.offset_eV], dwell_time=dwell, track_feespec=False,
            record=record, sample='und1026_spec_calib')

    # ---- SEER ----------------------------------------------------------------

    def seer_table(self, radius_mm=250.0):
        """Ge(660) vs Ge(620) angles, dispersion and window span."""
        seer_swap_table(radius_mm)

    def seer_save(self, tag, extra_pvs=()):
        """
        Save SEER motor readbacks to ~/seer_positions/<tag>.json.

        Run before the crystal swap with tag 'ge660' so the 1019410 setup can
        be restored, and after alignment tonight with tag 'ge620'. Add the
        crystal-stack motor PVs in extra_pvs once their names are confirmed.
        A copy goes to the shift results folder.
        """
        from epics import caget
        pvs = dict(SEER_PARKER)
        pvs.update({p: p for p in extra_pvs})
        pos = {k: caget(pv + '.RBV') for k, pv in pvs.items()}
        rec = {'tag': tag, 'time': time.strftime('%Y-%m-%d %H:%M:%S'),
               'pvs': pvs, 'rbv': pos}
        for folder in (SEER_SAVE, _results_dir()):
            try:
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f'{tag}.json').write_text(json.dumps(rec, indent=1))
            except OSError as e:
                logger.warning(f'Cannot write {folder}: {e}')
        _post(f"SEER positions saved as {tag}: {pos}", tag='seer')
        return rec

    def seer_restore(self, tag):
        """
        Move SEER motors back to a saved set, after typing 'yes'.

        Beam closed first. Prints current and saved readbacks for every
        motor before asking.
        """
        from epics import caget, caput
        rec = json.loads((SEER_SAVE / f'{tag}.json').read_text())
        for k, pv in rec['pvs'].items():
            print(f"  {k:6s} {pv}: now {caget(pv + '.RBV')}, saved {rec['rbv'][k]}")
        if input(f"Move SEER to '{tag}' ({rec['time']})? yes/no: ").strip() != 'yes':
            print("not moved")
            return
        for k, pv in rec['pvs'].items():
            if rec['rbv'][k] is not None:
                caput(pv + '.VAL', rec['rbv'][k], wait=True, timeout=120)
        self.seer_save(f'{tag}_restored_{time.strftime("%m%d_%H%M")}')

    def seer_check(self, run_length=60, record=True):
        """
        One mono run for the SEER elastic line, DCCM at CENTER_EV.

        Kapton flag (shutter 4) in, epix100 in the partition. Expect the
        line near the middle of the ROI. If it is off the sensor, move the
        Parker stages by hand in small steps and repeat; record each move in
        the elog.
        """
        self.mono(CENTER_EV)
        _ns('autorun')(sample='seer_ge620_elastic', tag='seer', run_length=run_length,
                       record=record, runs=1, picker='open')

    # ---- undulator timing ---------------------------------------------------

    def timing(self, name, change=None, dwell=1.0, record=True):
        """
        Run timing scan T1..T5 (DCCM in, XRT tracking, no sample).

        Requests K to the start position first where the table defines one,
        so the first step costs no motion. For T5 give a short label for the
        listener change, e.g. x.timing('T5', change='seg_skip').
        """
        pos, mode, order, extra, sample, k0 = TIMING[name]
        if name == 'T5':
            sample = f"{sample}_{change or 'baseline'}"
        exafs = _ns('exafs')
        if k0 is not None:
            exafs.acr_energy_k.move(k0)
        return exafs.k_xas_scan(
            k_positions=pos(), k_order=order, k_move_mode=mode, sample=sample,
            dwell_time=dwell, dccm_offsets=[self.offset_eV],
            crystal_angle_offset=self.xrt_offset, track_feespec=True,
            track_feespec_cam=True, track_feespec_blocking=False,
            record=record, **extra)

    # ---- transfocator -------------------------------------------------------

    def tfs_combo(self):
        """
        Print the lens combination for tonight and the per-lens radii.

        Prefocus OUT, TFS 04 + 05 + 06 IN, all other lenses out. Reads each
        lens :RADIUS PV so the elog has the actual stack, then checks the
        combined radius against TFS_R_UM.
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
        """
        Prefocus out, TFS stage to 100 mm, check the 4,5,6 combination.

        The calculator reads the current stage position, hence the 100 mm
        move. A 'prefocus recommended' log line is expected tonight.
        """
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
            frames, t_end = [], time.time() + image_sec
            while time.time() < t_end or len(frames) < 10:
                frames.append(np.asarray(cam.get_image_roi(), float))
            img = np.mean(frames, axis=0)
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
        """Hold lenses 4, 5, 6 on their y setpoints. Blocks; run in a second mfx3."""
        return _ns('tfs').lens_minder(lenses=TFS_LENSES)

    # ---- geometry ------------------------------------------------------------

    def agbe_rings(self, det_dist_mm, energy_eV=TFS_E_EV):
        """Ring radii for the chosen JF16M distance."""
        agbe_rings(det_dist_mm, energy_eV)

    def agbe_run(self, det_dist_mm, run_length=60, att_t=None, record=True):
        """
        Silver behenate geometry run on the JF16M (DCCM in, TFS focused).

        Detector at its final distance for the shift, AgBe at the IP. Sets
        the attenuator if att_t is given, prints the expected rings, then one
        geomrun (tag geom, run type GEOM). Analysis: BayFAI / pyFAI with
        calibrant 'AgBh' and the DCCM energy. Distance, beam center and tilt
        go into the poni file in the results folder.
        """
        agbe_rings(det_dist_mm)
        if att_t is not None:
            _ns('att')(att_t)
        _ns('geomrun')(run_length=run_length, record=record, runs=1, picker='open')
        _post(f"AgBe geometry run: JF16M at {det_dist_mm} mm (nominal), "
              f"DCCM {TFS_E_EV:.1f} eV, TFS {TFS_LENSES} at {self.tfs_zmin:.1f} mm, "
              f"att {att_t}", tag='geom')

    # ---- pink beam -----------------------------------------------------------

    def kx(self, step=2.5):
        """
        Pink sweep lo -> hi -> lo, shifted for the measured offset.

        The shift applies only when the measured offset differs from -5.2 eV
        by more than 3 eV, rounded to the 0.5 eV list spacing.
        """
        d = REQ_OFFSET_EV - self.offset_eV
        shift = np.round(d * 2) / 2 if abs(d) > 3 else 0.0
        return sweep(PINK_LO + shift, PINK_HI + shift, step)

    def pink_switch(self, att_t=1e-2):
        """
        Mono to pink: attenuate, DCCM out, XRT parked at CENTER_EV.

        Removing the DCCM raises the flux on every downstream detector by
        about two orders of magnitude, hence the attenuator first.
        """
        _ns('att')(att_t)
        _ns('dccm').remove()
        self.xrt_park(CENTER_EV)
        print(f"Pink beam. Confirm on the DCCM screen and by the DG1/DG2 IPM jump. "
              f"xrt_track = {self.xrt_track}.")

    def pink_opts(self):
        return dict(pink=True, k_move_mode='concurrent_settled',
                    crystal_angle_offset=self.xrt_offset,
                    track_feespec=self.xrt_track, track_feespec_cam=self.xrt_track,
                    track_feespec_blocking=False, record=True)

    def pink(self, name, n=None, r=None, dwell=None):
        """
        Pink-beam run P0a, P0b, P1, P2, P (production) or Pend.

        Sweeps run concurrent_settled in visiting order; K is requested to
        the sweep start first. P2 parks K at 7120 eV. For production give the
        pass and reservoir numbers: x.pink('P', n=3, r=2). One call is one
        DAQ run, so reservoir swaps fall between calls.
        """
        step, dw, sample = PINK[name]
        dwell = dw if dwell is None else dwell
        exafs = _ns('exafs')
        if name == 'P':
            if n is None or r is None:
                raise ValueError("production needs n= and r=")
            sample = sample.format(n=n, r=r)
        if step is None:
            pos = [PINK_PARK]
        else:
            pos = self.kx(step)
            if round(exafs.acr_energy_k.get().setpoint, 1) != pos[0]:
                exafs.acr_energy_k.move(pos[0])
        return exafs.k_xas_scan(k_positions=pos, k_order='given',
                                dwell_time=dwell, sample=sample, **self.pink_opts())


# ---- procedures --------------------------------------------------------------

_PROC = {
    'xrt': """
XRT (FEE) spectrometer, Si(111), one image must hold 7080-7155 eV real
 1. DCCM in at 7117.5 eV: x.mono(7117.5). Attenuate for the FEE camera.
 2. x.xrt_park(). CamViewer fee_spec, check the mono line is on the sensor.
 3. x.xrt_tune(+-0.05) until the line sits at the image center column.
 4. x.spec_calib(): 16 K + DCCM steps, 7080-7155 eV real, one run.
 5. From the run: centroid pixel at the two end steps, then
    spec_window(px_a, e_a, px_b, e_b). Fits: x.xrt_track = False.
    Does not fit: keep x.xrt_track = True (spectrometer follows K, energy
    axis changes per step), note it in the elog.
 6. Optional cross-check of the camera arm:
    xrtspec.scan_feespec_camera_angle(7.08, 7.155, 4, run_length=30)
""",
    'seer': """
SEER, swap Ge(660) -> Ge(620) for tonight, comparable Bragg angle
 1. Hutch access, beam off. x.seer_save('ge660'). Photos of the crystal mount.
 2. Ge(660) out, Ge(620) in the same mount. Log both serials and radii.
 3. Laser diode: reflection from the new crystal lands on the detector plate.
    Ge(620) at 7117.5 eV sits 0.77 deg above the Ge(660) 9580 eV angle
    (x.seer_table()), so expect a small crystal tilt and no stage move.
 4. Power the epix100 (MPOD ch104, wait 5 s, ch105, ch206, ch2); in partition.
 5. Beam: Kapton flag in (shutter 4), x.seer_check(). Find the elastic line.
 6. Off the ROI: Parker MMS:08 / MMS:09 by hand, <= 0.5 mm steps, one
    x.seer_check() per step. Crystal tilt only if the Kohzu motors are up.
 7. x.spec_calib() puts the 7080-7155 eV scan on SEER too; read the span.
 8. x.seer_save('ge620'). Do not move SEER during a pink pass.
 After the shift: reverse 1-2 with Ge(660), x.seer_restore('ge660'),
 elastic line check at 9.58 keV on the first 1019410 shift.
""",
    'tfs': """
TFS 04,05,06 z scan, no prefocus, DCCM in at 7115 eV
 Combination: prefocus (MFX:DIA:XFLS) OUT, TFS lenses 04 + 05 + 06 in
 (MFX:LENS:TFS:04-06), nothing else. Effective radius 58.8 um, legal
 without prefocus. Stage MFX:TFS:MMS:21 ~177 mm at 7115 eV.
 1. Beam closed or att 1e-4. x.tfs_combo(): combination and lens radii.
 2. x.tfs_prep(): prefocus out, stage 100, combo check.
 3. x.tfs_insert(): lenses in, stage 177 mm. DG2 centroid, IPM ratio ~0.2.
 4. Second mfx3: x.tfs_minder() and leave it running.
 5. IP YAG in, att 1e-3. Cross1/Cross2 around the spot with margin.
 6. x.tfs_zscan(): 137-217 mm, 4 mm, 3 s per point (~3 min). Watch:
    fwhm columns fall then rise; peak column below camera saturation;
    'rejected' points mean beam off (lens_minder closes the picker).
 7. x.tfs_fine(zmin): zmin +- 12 mm, 1.5 mm, 4 s per point (~2 min).
 8. x.tfs_park(zmin). More than 15 mm from 177: x.offset_check() first.
 9. After DCCM out: x.tfs_pink_check(), three points.
""",
    'agbe': """
Silver behenate geometry, JF16M at the shift distance
 1. TFS parked, DCCM in at 7115 eV, AgBe at the IP plane, YAG out.
 2. x.agbe_rings(D): >= 4 rings between the beamstop and the edge.
 3. Start at att 1e-3 and raise until rings 4-8 are clear, below saturation.
 4. x.agbe_run(D, run_length=60, att_t=T).
 5. Geometry fit: BayFAI / pyFAI, calibrant AgBh, energy 7115 eV. poni to the
    results folder. Refine later on indexed Mb hits (cctbx.geom_refine).
 6. AgBe out before the HVE goes in.
""",
    'pink': """
Pink beam
 1. x.pink_switch() (att 1e-2, DCCM out, XRT parked).
 2. x.tfs_pink_check().
 3. x.pink('P0a'), x.pink('P0b'), HVE carrier: x.pink('P1').
 4. Mb: x.pink('P2'), data check, then x.pink('P', n=3, r=1) ...
 5. x.pink('Pend') on carrier.
""",
}


# ---- checklists --------------------------------------------------------------

_CHECK_PRE = """
PRE-EXPERIMENT (done by 17:30 unless marked)
 code and controls
 [ ] branch 1020945-undulator-1026 pushed and checked out on the operator machine
 [ ] active experiment is mfx102095027; `x` exists in mfx3; x.status() runs
 [ ] results folder writable, kinit done (BayFAI failed on 10-23 on permissions)
 [ ] x.dry_run() passes; epicsArch include fixed (~683 aliases)
 [ ] python scripts/undulator_pv_check.py, NC lines to the elog
 [ ] DCCM state PVs (STATE:SET / State:SET) answer cainfo
 [ ] ACR: 6970-7160 eV, 0.5 eV list loaded in preset mode; tracking GUI will not pin K
 SEER (hutch access, before beam)
 [ ] crystal-stack motors connected? (HERA IMS ch 2, 3, 4; not connected 10-24 to 10-26)
 [ ] confirm which PVs drive them; MFX:HRA:MMS:02-04 are named xlj_fast_rx/rz/ry in beamline.py
 [ ] MMS:08 axis: Z or X (notes disagree); jog and check
 [ ] x.seer_save('ge660') plus photos of the mount, epix100 ROI and rotation noted
 [ ] Ge(660) out, Ge(620) in; radius of both crystals checked; swap logged in crystal tracking
 [ ] laser diode reflection lands on the detector; epix100 powered (ch104, 5 s, ch105, ch206, ch2)
 [ ] epix100 (SEER) in the DAQ partition
 XRT
 [ ] feespec/hproj saved in smalldata over the full 2048 px
 TFS and IP
 [ ] IP camera PV confirmed (x.tfs_zscan uses MFX:GIGE:LBL:01); Cross1/Cross2 set
 [ ] lens 4, 5, 6 x/y noted; TFS USB hub and encoder cables OK
 geometry
 [ ] AgBe sample mounted at the IP plane; JF16M distance for the shift decided
 [ ] x.agbe_rings(D) shows >= 4 orders on the sensor
 [ ] BayFAI/pyFAI config uses calibrant AgBh (the 1019410 setup used LaB6)
 sample, XES, analysis
 [ ] >= 3 Mb reservoirs + 1 carrier-only reservoir, carrier and salt recorded
 [ ] von Hamos untouched (3 Kb, 2+1 Ka); epix100 ROIs defined
 [ ] smalldata carries XRT and SEER projections, epix100 ROIs, IPMs, JF16M hits, BLD, SET2/AO805
 [ ] transmitted channel chosen (DG3 IPM assumed)
"""

_CHECK_POST = """
POST-EXPERIMENT
 at 06:00
 [ ] Ctrl+C lens_minder; tfs.remove_all() unless the next shift keeps the stack
 [ ] DCCM state and XRT energy for the next shift (9.58 keV for the 1019410 shifts)
 [ ] AgBe sample out; Kapton flag state as the next shift needs
 [ ] camonitor log copied next to the timing CSVs; per-run elog lines complete
 [ ] branch for the next shift checked out; active experiment switched back
 SEER swap back (hutch access, before the next 1019410 shift)
 [ ] x.seer_save('ge620') before touching the crystal
 [ ] Ge(620) out, Ge(660) back in the same mount; swap logged in crystal tracking
 [ ] x.seer_restore('ge660'); laser diode check
 [ ] first beam at 9.58 keV: elastic line at the pixel recorded for Ge(660)
 within a day
 [ ] timing tables for T1-T4 and every pink pass posted; 1 eV k_move vs 18.3 s
 [ ] SASE-in-transit curves, up/down split, hysteresis, recovery vs AO805
 [ ] XRT and SEER eV/px from x.spec_calib() posted with the run number
 [ ] AgBe poni in the results folder; geometry used for Mb indexing
 [ ] waist position (mono and pink) posted
 [ ] stochastic data set and run list to the analysis lead
 [ ] transmission go / partial / no-go to the December planning thread
 [ ] timing results to the machine side
 [ ] plan and results into the notes and the project board once final
"""
