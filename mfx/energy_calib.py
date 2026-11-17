"""
Keep the DCCM and the XRT (FEE) spectrometer centered on the SASE while
the undulator K moves.

Two calibrations, both measured with the DCCM in:

SaseCalibration
    Real SASE center against the K request. At each K the DCCM steps
    across the SASE and a downstream IPM, normalized by the gas detector,
    traces the SASE spectrum; a Gaussian fit gives the center. The offset
    (center - K request) is fit as a polynomial in K: degree 0 is the
    constant x.offset_eV used so far, degree 1 adds a slope (on 10-26 the
    XRT centroid followed the request at ~0.56 eV per eV, which a constant
    offset cannot follow). Up and down steps can get separate fits (they
    sat -3.6 +- 2.4 eV apart on 10-26). ``center(k, prev_k)`` is what
    Exafs.k_xas_scan(energy_center=...) calls at every K step.

XrtCalibration
    Crystal-angle correction that puts the DCCM line on the target column
    of the XRT Zyla at every energy. At each energy the crystal is rocked
    by +-delta around the angle the model gives, the line position is fit
    linearly against th and solved for the target column. The correction
    (best th - model th) is fit as a polynomial in energy and installed as
    XRTspec.th_correction, so tracking, parking and the angle check all
    use it.

Fitting and bookkeeping need numpy only (scipy refines the peak fit when
present) and run offline. The live readers and the measurement loops take
their devices as arguments and import epics lazily, so tests can drive
them with fakes. Python 3.9 compatible (pcds-5.9.1).
"""

import json
import logging
import threading
import time
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

FWHM_PER_SIGMA = 2.0 * np.sqrt(2.0 * np.log(2.0))

# downstream IPMs (beamline_hw names) and the gas detector for normalization
SIGNAL_PVS = {
    'dg1': 'MFX:DG1:W8:01:SUM',
    'dg2': 'MFX:DG2:BMMON:SUM',
}
NORM_PV = 'GDET:FEE1:241:ENRC'
# below this mean gas detector reading (mJ) a point counts as no beam
NORM_MIN = 0.02

ZYLA_PREFIX = 'XRT:ZYLA:CAM:01'


# ---- small helpers -------------------------------------------------------------

def _f(v):
    """float that survives json (nan -> None)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, np.ndarray)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return _f(obj)
    return obj


def _nan(v):
    return np.nan if v is None else float(v)


def _polyfit(x, y, deg):
    """
    Polynomial fit of y(x) about the mean of x. Degree is capped at
    len(x) - 1. Returns a model dict, or None for no points.
    """
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) == 0:
        return None
    deg = int(max(0, min(deg, len(x) - 1)))
    # a slope from two points closer than 1 eV is noise
    if deg >= 1 and np.ptp(x) < 1.0:
        deg = 0
    ref = float(np.mean(x))
    coef = np.polyfit(x - ref, y, deg) if deg > 0 else np.array([np.mean(y)])
    resid = y - np.polyval(coef, x - ref)
    dof = max(1, len(x) - deg - 1)
    return dict(coef=[float(c) for c in coef], ref=ref, deg=deg,
                lo=float(np.min(x)), hi=float(np.max(x)), n=int(len(x)),
                rms=float(np.sqrt(np.sum(resid ** 2) / dof)) if len(x) > deg + 1 else np.nan,
                max_abs=float(np.max(np.abs(resid))))


def _peval(model, x, extrap):
    """Evaluate a model; outside lo-extrap .. hi+extrap the value is held."""
    xx = float(np.clip(x, model['lo'] - extrap, model['hi'] + extrap))
    return float(np.polyval(model['coef'], xx - model['ref']))


def _slope(model):
    """d(model)/dx at the reference point."""
    return float(model['coef'][-2]) if model['deg'] >= 1 else 0.0


def step_direction(k_eV, prev_k_eV):
    if prev_k_eV is None or not np.isfinite(prev_k_eV) or abs(k_eV - prev_k_eV) < 1e-6:
        return None
    return 'up' if k_eV > prev_k_eV else 'down'


# ---- peak and line fits ------------------------------------------------------------

def _gauss(x, a, c, s, b):
    return b + a * np.exp(-0.5 * ((x - c) / s) ** 2)


def fit_peak(x, y, fwhm_min=None, fwhm_max=None):
    """
    Gaussian + constant fit to one peak, with a half-maximum centroid
    as the start value and fallback.

    Returns a dict: center, fwhm, amp, bg, err (1 sigma on the center),
    method, ok, reason, edge (-1 / +1 when the peak sits at the low / high
    end of the scanned range, so the caller can move the window; 0 inside).
    fwhm_min, fwhm_max default to 2 steps and 2x the scanned span.
    """
    x, y = np.asarray(x, float), np.asarray(y, float)
    good = np.isfinite(x) & np.isfinite(y)
    x, y = x[good], y[good]
    order = np.argsort(x)
    x, y = x[order], y[order]
    out = dict(ok=False, center=np.nan, fwhm=np.nan, amp=np.nan, bg=np.nan,
               err=np.nan, method='none', reason='', edge=0, n=int(len(x)))
    if len(x) < 5:
        out['reason'] = f'{len(x)} points, need 5'
        return out
    span = float(x[-1] - x[0])
    step = float(np.median(np.diff(x)))
    fwhm_min = 2.0 * step if fwhm_min is None else float(fwhm_min)
    fwhm_max = 2.0 * span if fwhm_max is None else float(fwhm_max)

    bg = float(np.percentile(y, 10))
    i = int(np.argmax(y))
    amp = float(y[i] - bg)
    d = np.diff(y)
    noise = float(1.4826 * np.median(np.abs(d - np.median(d))) / np.sqrt(2.0))
    if amp <= 0:
        out['reason'] = 'flat signal'
        return out
    if noise > 0 and amp < 3.0 * noise:
        out.update(amp=amp, bg=bg, reason=f'peak {amp:.3g} below 3x noise {noise:.3g}')
        return out

    # contiguous half-maximum region around the highest point
    above = (y - bg) >= 0.5 * amp
    lo = hi = i
    while lo > 0 and above[lo - 1]:
        lo -= 1
    while hi < len(x) - 1 and above[hi + 1]:
        hi += 1
    w = y[lo:hi + 1] - bg
    c0 = float(np.sum(x[lo:hi + 1] * w) / np.sum(w))
    fwhm0 = float(max(x[hi] - x[lo] + step, step))
    out.update(center=c0, fwhm=fwhm0, amp=amp, bg=bg, err=step / 2.0,
               method='half-max centroid')

    try:
        from scipy.optimize import curve_fit
        p0 = [amp, c0, max(fwhm0, fwhm_min) / FWHM_PER_SIGMA, bg]
        lower = [0.0, x[0] - span, fwhm_min / FWHM_PER_SIGMA / 2.0, -np.inf]
        upper = [np.inf, x[-1] + span, 2.0 * fwhm_max / FWHM_PER_SIGMA, np.inf]
        p0 = list(np.clip(p0, lower, upper))
        popt, pcov = curve_fit(_gauss, x, y, p0=p0, bounds=(lower, upper), maxfev=5000)
        perr = np.sqrt(np.diag(pcov)) if np.all(np.isfinite(pcov)) else [np.nan] * 4
        out.update(center=float(popt[1]), fwhm=float(popt[2] * FWHM_PER_SIGMA),
                   amp=float(popt[0]), bg=float(popt[3]), err=float(perr[1]),
                   method='gaussian')
    except ImportError:
        pass
    except Exception as e:
        out['reason'] = f'gaussian fit failed ({e.__class__.__name__}), centroid kept'

    # peak at the scan edge: the real center may lie outside the window
    if i == 0 or out['center'] < x[0] + 0.5 * step:
        out['edge'] = -1
    elif i == len(x) - 1 or out['center'] > x[-1] - 0.5 * step:
        out['edge'] = 1
    if out['edge']:
        out['reason'] = (f"peak at the {'low' if out['edge'] < 0 else 'high'} end of "
                         f"{x[0]:.1f}-{x[-1]:.1f}")
        return out
    if not fwhm_min <= out['fwhm'] <= fwhm_max:
        out['reason'] = (f"FWHM {out['fwhm']:.2f} outside {fwhm_min:.2f}-"
                         f"{fwhm_max:.2f}")
        return out
    out['ok'] = True
    return out


def solve_th(ths, pxs, target_px):
    """
    Linear fit of line position (px) against crystal angle (deg), solved
    for the target column.

    Returns dict(th, slope (px/deg), intercept_px at th mean, r2, ok,
    reason).
    """
    ths, pxs = np.asarray(ths, float), np.asarray(pxs, float)
    good = np.isfinite(ths) & np.isfinite(pxs)
    ths, pxs = ths[good], pxs[good]
    out = dict(th=np.nan, slope=np.nan, px_at_mean=np.nan, r2=np.nan, ok=False, reason='')
    if len(ths) < 2 or np.ptp(ths) <= 0:
        out['reason'] = f'{len(ths)} usable rocking points, need 2 at different th'
        return out
    t0 = float(np.mean(ths))
    slope, icpt = np.polyfit(ths - t0, pxs, 1)
    pred = icpt + slope * (ths - t0)
    ss = float(np.sum((pxs - np.mean(pxs)) ** 2))
    r2 = 1.0 - float(np.sum((pxs - pred) ** 2)) / ss if ss > 0 else np.nan
    out.update(slope=float(slope), px_at_mean=float(icpt), r2=r2)
    if abs(slope) < 1e-6:
        out['reason'] = 'line does not move with th'
        return out
    out['th'] = t0 + (float(target_px) - icpt) / slope
    if len(ths) > 2 and np.isfinite(r2) and r2 < 0.8:
        out['reason'] = f'rocking fit r2 {r2:.2f} < 0.8'
        return out
    out['ok'] = True
    return out


# ---- calibrations -----------------------------------------------------------------

class _Calibration:
    """Points, a fit and json persistence."""

    kind = 'base'

    def __init__(self):
        self.points = []
        self.meta = {}

    def to_dict(self):
        d = {k: v for k, v in self.__dict__.items() if not k.startswith('_')}
        d['kind'] = self.kind
        return _jsonable(d)

    @classmethod
    def from_dict(cls, d):
        if d.get('kind') != cls.kind:
            raise ValueError(f"file holds a {d.get('kind')!r} calibration, not {cls.kind!r}")
        obj = cls()
        for k, v in d.items():
            if k != 'kind':
                setattr(obj, k, v)
        return obj

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=1)
        return path

    @classmethod
    def load(cls, path):
        with open(path) as f:
            return cls.from_dict(json.load(f))

    def good(self):
        return [p for p in self.points if p.get('ok')]


class SaseCalibration(_Calibration):
    """
    Real SASE center against the K request (both eV).

    offset(K) = center - K is fit as a polynomial of degree `deg` (0 =
    constant offset). With by_direction=True and enough points for both,
    up steps and down steps get their own fits; a step with no known
    direction (first step, repeated K) uses the common fit. Outside the
    measured K range +- extrap_eV the offset is held at the end value.
    shift_eV is added on top after a one-point re-zero (drift); fit()
    clears it.
    """

    kind = 'sase'

    def __init__(self, deg=1, by_direction=False, extrap_eV=10.0):
        super().__init__()
        self.deg = int(deg)
        self.by_direction = bool(by_direction)
        self.extrap_eV = float(extrap_eV)
        self.models = {}
        self.shift_eV = 0.0

    # -- data
    def add(self, k_eV, fit, direction=None, energies=None, signals=None, **meta):
        """Add one measured point; fit is a fit_peak() result."""
        p = dict(k_eV=float(k_eV), center_eV=_f(fit.get('center')),
                 fwhm_eV=_f(fit.get('fwhm')), amp=_f(fit.get('amp')),
                 err_eV=_f(fit.get('err')), ok=bool(fit.get('ok')),
                 reason=fit.get('reason', ''), direction=direction,
                 time=time.strftime('%Y-%m-%d %H:%M:%S'))
        if energies is not None:
            p['energies_eV'] = [_f(e) for e in energies]
            p['signals'] = [_f(s) for s in signals]
        p.update(meta)
        self.points.append(p)
        return p

    @property
    def ready(self):
        return 'all' in self.models

    def fit(self, deg=None, by_direction=None):
        """Fit the offset model(s) from the good points; returns self.models."""
        if deg is not None:
            self.deg = int(deg)
        if by_direction is not None:
            self.by_direction = bool(by_direction)
        good = self.good()
        self.models = {}
        self.shift_eV = 0.0
        if not good:
            return self.models
        k = [p['k_eV'] for p in good]
        off = [p['center_eV'] - p['k_eV'] for p in good]
        self.models['all'] = _polyfit(k, off, self.deg)
        if self.by_direction:
            for d in ('up', 'down'):
                sel = [p for p in good if p.get('direction') == d]
                if len(sel) >= self.deg + 1:
                    self.models[d] = _polyfit([p['k_eV'] for p in sel],
                                              [p['center_eV'] - p['k_eV'] for p in sel],
                                              self.deg)
        return self.models

    # -- use
    def _model(self, direction):
        if not self.models:
            raise RuntimeError('SASE calibration has no fit yet')
        return self.models.get(direction) or self.models['all']

    def offset(self, k_eV, direction=None):
        """center - K for one K request, eV."""
        return _peval(self._model(direction), k_eV, self.extrap_eV) + self.shift_eV

    def center(self, k_eV, prev_k_eV=None):
        """Real SASE center for K request k_eV reached from prev_k_eV (eV)."""
        return float(k_eV) + self.offset(k_eV, step_direction(k_eV, prev_k_eV))

    def k_for(self, real_eV, direction=None):
        """K request whose SASE center is real_eV (unrounded)."""
        k = float(real_eV) - self.offset(real_eV, direction)
        for _ in range(50):
            k_new = float(real_eV) - self.offset(k, direction)
            if abs(k_new - k) < 1e-4:
                break
            k = k_new
        return k

    def rezero(self, k_eV, center_eV, direction=None):
        """
        Shift every model so the center at k_eV is center_eV (drift), keeping
        the slope. Returns the shift; the next fit() clears it.
        """
        self.shift_eV = 0.0
        self.shift_eV = float(center_eV) - (float(k_eV) + self.offset(k_eV, direction))
        return self.shift_eV

    def model_text(self, name='all'):
        m = self.models.get(name)
        if not m:
            return f"{name}: no fit"
        if m['deg'] == 0:
            form = f"center = K {m['coef'][-1]:+.2f} eV"
        else:
            form = (f"center = K {m['coef'][-1]:+.2f} {_slope(m):+.4f} x (K - {m['ref']:.1f}) eV"
                    f"  (center moves {1 + _slope(m):.3f} eV per eV of K)")
            if m['deg'] > 1:
                form += f", degree {m['deg']}"
        rms = f"rms {m['rms']:.2f} eV" if np.isfinite(_nan(m['rms'])) else "rms n/a"
        return (f"{name}: {form}; {m['n']} points, K {m['lo']:.1f}-{m['hi']:.1f} eV, "
                f"{rms}, max |resid| {m['max_abs']:.2f} eV")

    def summary(self):
        lines = ["SASE calibration (real center vs K request)",
                 "    K req   dir    center    fwhm   center-K   resid   ok"]
        for p in self.points:
            c = _nan(p.get('center_eV'))
            res = np.nan
            if self.models and np.isfinite(c):
                res = c - p['k_eV'] - self.offset(p['k_eV'], p.get('direction'))
            lines.append(f"  {p['k_eV']:7.1f}  {str(p.get('direction') or '-'):5s} "
                         f"{c:8.1f}  {_nan(p.get('fwhm_eV')):6.1f}  {c - p['k_eV']:+8.1f}  "
                         f"{res:+6.2f}   {'yes' if p.get('ok') else 'NO ' + p.get('reason', '')}")
        for name in ('all', 'up', 'down'):
            if name in self.models:
                lines.append("  " + self.model_text(name))
        if self.shift_eV:
            lines.append(f"  re-zero shift {self.shift_eV:+.2f} eV on top")
        return "\n".join(lines)


class XrtCalibration(_Calibration):
    """
    XRT crystal-angle correction (deg) against energy (eV in the points,
    keV in correction(), like XRTspec).

    The correction is best th - model th, where the model is the XRTspec
    polynomial plus the constant crystal offset in use when the point was
    taken (meta 'offset_deg'). Held at the end values outside the measured
    range +- extrap_eV.
    """

    kind = 'xrt'

    def __init__(self, deg=1, extrap_eV=20.0):
        super().__init__()
        self.deg = int(deg)
        self.extrap_eV = float(extrap_eV)
        self.model = None

    def add(self, energy_eV, th_model, th_best, ok, **meta):
        p = dict(energy_eV=float(energy_eV), th_model=_f(th_model), th_best=_f(th_best),
                 corr_deg=_f(_nan(th_best) - _nan(th_model)), ok=bool(ok),
                 time=time.strftime('%Y-%m-%d %H:%M:%S'))
        p.update(_jsonable(meta))
        self.points.append(p)
        return p

    @property
    def ready(self):
        return self.model is not None

    def fit(self, deg=None):
        if deg is not None:
            self.deg = int(deg)
        good = [p for p in self.good() if p.get('corr_deg') is not None]
        self.model = _polyfit([p['energy_eV'] for p in good],
                              [p['corr_deg'] for p in good], self.deg) if good else None
        return self.model

    def correction(self, energy_keV):
        """Crystal-angle correction in deg at energy_keV (0 without a fit)."""
        if self.model is None:
            return 0.0
        return _peval(self.model, float(energy_keV) * 1000.0, self.extrap_eV)

    def summary(self):
        lines = ["XRT calibration (crystal angle that centers the DCCM line)",
                 "   energy    th model   th best    corr     px/deg   line px  "
                 "-> px    ok"]
        for p in self.points:
            lines.append(
                f"  {p['energy_eV']:7.1f}  {_nan(p.get('th_model')):9.4f} "
                f"{_nan(p.get('th_best')):9.4f}  {_nan(p.get('corr_deg')):+7.4f}  "
                f"{_nan(p.get('slope_px_per_deg')):8.0f}  {_nan(p.get('px_start')):7.1f}  "
                f"{_nan(p.get('px_best')):6.1f}   "
                f"{'yes' if p.get('ok') else 'NO ' + str(p.get('reason', ''))}")
        m = self.model
        if m:
            form = f"corr = {m['coef'][-1]:+.4f} deg"
            if m['deg'] >= 1:
                form += f" {_slope(m) * 1000:+.4f} deg/keV x (E - {m['ref']:.1f} eV)"
            rms = f"rms {m['rms']:.4f} deg" if np.isfinite(_nan(m['rms'])) else "rms n/a"
            lines.append(f"  {form}; {m['n']} points, {m['lo']:.1f}-{m['hi']:.1f} eV, {rms}")
        else:
            lines.append("  no fit")
        return "\n".join(lines)


# ---- live readers -----------------------------------------------------------------

class MeanReader:
    """
    Mean of a signal PV and a normalization PV over a time window, from
    CA monitors (polls if a PV does not update, e.g. a slow IOC).

    read() returns dict(ratio, signal, norm, n_signal, n_norm, ok, reason).
    ratio = mean(signal) / mean(norm); with norm_pv=None, mean(signal).
    """

    def __init__(self, signal_pv, norm_pv=NORM_PV, norm_min=NORM_MIN, timeout=2.0):
        from epics import PV
        self.signal_pv, self.norm_pv, self.norm_min = signal_pv, norm_pv, norm_min
        self._pvs = {'signal': PV(signal_pv, auto_monitor=True)}
        if norm_pv:
            self._pvs['norm'] = PV(norm_pv, auto_monitor=True)
        for name, pv in self._pvs.items():
            if not pv.wait_for_connection(timeout=timeout):
                raise RuntimeError(f"{pv.pvname} ({name}) not connected")
        self._lock = threading.Lock()
        self._buf = {k: [] for k in self._pvs}
        for name, pv in self._pvs.items():
            pv.add_callback(self._make_cb(name))

    def _make_cb(self, name):
        def cb(value=None, **kw):
            with self._lock:
                self._buf[name].append(value)
        return cb

    def read(self, seconds=1.0, min_n=5):
        with self._lock:
            for k in self._buf:
                self._buf[k] = []
        t0 = time.time()
        while time.time() - t0 < seconds:
            time.sleep(0.05)
        with self._lock:
            vals = {k: list(v) for k, v in self._buf.items()}
        for k, pv in self._pvs.items():
            if len(vals[k]) < min_n:   # not updating on monitors: poll
                vals[k] += [pv.get(use_monitor=False) for _ in range(min_n)]
        sig = np.asarray([v for v in vals['signal'] if v is not None], float)
        out = dict(signal=float(np.mean(sig)) if len(sig) else np.nan,
                   n_signal=int(len(sig)), norm=np.nan, n_norm=0, ok=True, reason='')
        out['ratio'] = out['signal']
        if 'norm' in vals:
            nv = np.asarray([v for v in vals['norm'] if v is not None], float)
            out.update(norm=float(np.mean(nv)) if len(nv) else np.nan, n_norm=int(len(nv)))
            if not np.isfinite(out['norm']) or out['norm'] < self.norm_min:
                out.update(ok=False, ratio=np.nan,
                           reason=f"{self.norm_pv} {out['norm']:.3g} < {self.norm_min:g}: no beam")
            else:
                out['ratio'] = out['signal'] / out['norm']
        return out

    def __call__(self, seconds=1.0):
        return self.read(seconds)

    def close(self):
        """Drop the monitors (call when the calibration is done)."""
        for pv in self._pvs.values():
            try:
                pv.clear_callbacks()
                pv.disconnect()
            except Exception:
                pass


class ZylaLine:
    """
    Position of the DCCM line on the XRT Zyla along the dispersive axis.

    source='image' (default): the image from <prefix>:IMAGE1 is projected
    onto `axis` ('x' = columns, the dispersive axis on the XRT),
    averaged over `frames` new frames, background-subtracted and fit with
    fit_peak. source='stats': <prefix>:<stats>:CentroidX_RBV (or Y),
    averaged; faster, but without a background cut the centroid is pulled
    toward the image center, so use it only after checking it against the
    image.

    read() returns dict(px, fwhm_px, total, n, ok, reason).
    """

    def __init__(self, prefix=ZYLA_PREFIX, axis='x', source='image', stats='Stats1',
                 plugin='IMAGE1', timeout=2.0):
        from epics import PV
        if axis not in ('x', 'y'):
            raise ValueError("axis must be 'x' or 'y'")
        if source not in ('image', 'stats'):
            raise ValueError("source must be 'image' or 'stats'")
        self.prefix, self.axis, self.source = prefix, axis, source
        self.timeout = timeout
        p = f"{prefix}:{plugin}"
        self._data = PV(f"{p}:ArrayData", auto_monitor=False)
        self._s0 = PV(f"{p}:ArraySize0_RBV")
        self._s1 = PV(f"{p}:ArraySize1_RBV")
        self._count = PV(f"{p}:ArrayCounter_RBV")
        c = 'CentroidX_RBV' if axis == 'x' else 'CentroidY_RBV'
        self._cent = PV(f"{prefix}:{stats}:{c}")
        self._total = PV(f"{prefix}:{stats}:Total_RBV")

    def width(self):
        """Pixels along the dispersive axis."""
        s = self._s0.get(timeout=self.timeout) if self.axis == 'x' else \
            self._s1.get(timeout=self.timeout)
        if not s:
            raise RuntimeError(f"{self.prefix} image size not readable")
        return int(s)

    def _next_frame(self, last):
        t0 = time.time()
        while time.time() - t0 < self.timeout:
            c = self._count.get(use_monitor=False)
            if c is not None and c != last:
                return c
            time.sleep(0.02)
        raise RuntimeError(f"{self.prefix}: no new frame in {self.timeout:g} s "
                           f"(Zyla acquiring?)")

    def profile(self, frames=5):
        """Mean background-subtracted projection over `frames` new frames."""
        s0, s1 = int(self._s0.get(timeout=self.timeout)), int(self._s1.get(timeout=self.timeout))
        last = self._count.get(use_monitor=False)
        acc = None
        for _ in range(frames):
            last = self._next_frame(last)
            img = self._data.get(count=s0 * s1, timeout=self.timeout)
            if img is None or len(img) < s0 * s1:
                raise RuntimeError(f"{self.prefix}: short image read")
            img = np.asarray(img, float).reshape(s1, s0)
            prof = img.sum(axis=0) if self.axis == 'x' else img.sum(axis=1)
            acc = prof if acc is None else acc + prof
        prof = acc / frames
        return prof - np.percentile(prof, 20)

    def read(self, frames=5):
        if self.source == 'stats':
            vals, tot = [], []
            last = self._count.get(use_monitor=False)
            for _ in range(frames):
                last = self._next_frame(last)
                vals.append(self._cent.get(use_monitor=False))
                tot.append(self._total.get(use_monitor=False))
            v = np.asarray([x for x in vals if x is not None], float)
            return dict(px=float(np.mean(v)) if len(v) else np.nan, fwhm_px=np.nan,
                        total=float(np.nanmean(np.asarray(tot, float))), n=len(v),
                        ok=len(v) > 0, reason='' if len(v) else 'no centroid read')
        prof = self.profile(frames)
        x = np.arange(len(prof), dtype=float)
        fit = fit_peak(x, prof, fwhm_min=2.0, fwhm_max=len(prof) / 2.0)
        return dict(px=fit['center'], fwhm_px=fit['fwhm'], total=float(np.sum(prof)),
                    n=frames, ok=fit['ok'], reason=fit['reason'])

    def __call__(self, frames=5):
        return self.read(frames)


# ---- measurement loops (devices passed in) ----------------------------------------

def dccm_grid(center_eV, half_eV, step_eV):
    n = int(round(2 * half_eV / step_eV))
    return [round(center_eV - half_eV + i * step_eV, 3) for i in range(n + 1)]


def scan_dccm(dccm, energies_eV, read, read_s=1.0, settle_s=0.2, log=print):
    """
    Step the DCCM (dccm.energy.move(keV, wait=True)) over energies_eV and
    read the normalized intensity at each. Returns (energies, ratios).
    """
    es, rs = [], []
    for e in energies_eV:
        dccm.energy.move(e / 1000.0, wait=True)
        if settle_s:
            time.sleep(settle_s)
        r = read(read_s)
        es.append(float(e))
        rs.append(float(r['ratio']) if r.get('ok', True) else np.nan)
        if not r.get('ok', True):
            log(f"    DCCM {e:.1f} eV: {r.get('reason')}")
    return es, rs


def measure_sase_center(dccm, read, guess_eV, half_eV=20.0, step_eV=2.0, read_s=1.0,
                        settle_s=0.2, recenter=1, fwhm_max=60.0, log=print):
    """
    SASE center at the present K: DCCM scan guess +- half, Gaussian fit.

    If the peak sits at the window edge the window moves there and the
    scan repeats, at most `recenter` times. Returns (fit, energies,
    signals) of the last scan.
    """
    guess = float(guess_eV)
    for attempt in range(recenter + 1):
        es, rs = scan_dccm(dccm, dccm_grid(guess, half_eV, step_eV), read,
                           read_s, settle_s, log)
        fit = fit_peak(es, rs, fwhm_max=fwhm_max)
        if fit['ok'] or not fit['edge'] or attempt == recenter:
            return fit, es, rs
        ok = np.isfinite(rs)
        peak = float(np.asarray(es)[ok][np.argmax(np.asarray(rs)[ok])]) if ok.any() else guess
        guess = peak + fit['edge'] * 0.5 * half_eV
        log(f"    {fit['reason']}: window moves to {guess:.1f} eV")
    return fit, es, rs


def calibrate_sase(cal, k_list, request_k, dccm, read, guess_offset_eV,
                   direction='up', approach_eV=5.0, half_eV=20.0, step_eV=2.0,
                   read_s=1.0, settle_s=0.2, log=print):
    """
    Measure the SASE center at every K in k_list and fit cal after each.

    request_k(k_eV) moves K and waits for the done PV. direction 'up'
    visits k_list ascending, 'down' descending, 'both' up then down; each
    leg starts with an approach move approach_eV outside its first K, so
    every point is reached from the stated side (None: no approach move).
    The DCCM window is centered on the calibration so far, else on K +
    guess_offset_eV. Returns cal.
    """
    if direction not in ('up', 'down', 'both'):
        raise ValueError("direction must be 'up', 'down' or 'both'")
    ks = sorted(float(k) for k in k_list)
    legs = {'up': [('up', ks)], 'down': [('down', ks[::-1])],
            'both': [('up', ks), ('down', ks[::-1])]}[direction]
    for d, leg in legs:
        prev = None
        if approach_eV:
            prev = leg[0] - approach_eV if d == 'up' else leg[0] + approach_eV
            log(f"  approach K {prev:.1f} eV ({d})")
            request_k(prev)
        for k in leg:
            request_k(k)
            guess = cal.center(k, prev) if cal.ready else k + guess_offset_eV
            log(f"  K {k:.1f} eV ({d}): DCCM {guess - half_eV:.1f}-{guess + half_eV:.1f} eV "
                f"in {step_eV:g} eV")
            fit, es, rs = measure_sase_center(dccm, read, guess, half_eV, step_eV, read_s,
                                              settle_s, log=log)
            cal.add(k, fit, direction=d if prev is not None else None,
                    energies=es, signals=rs)
            if fit['ok']:
                log(f"    center {fit['center']:.1f} eV (K {fit['center'] - k:+.1f}), "
                    f"FWHM {fit['fwhm']:.1f} eV")
            else:
                log(f"    NOT USED: {fit['reason']}")
            cal.fit()
            prev = k
    return cal


def measure_xrt_point(xrt, line, energy_eV, offset_deg, target_px, delta_deg=0.03,
                      n_rock=3, settle_s=0.5, frames=5, max_step_deg=0.5, verify=True,
                      log=print):
    """
    Crystal angle that puts the line at energy_eV on target_px.

    xrt is an XRTspec. The spectrometer first moves to energy_eV with its
    present correction, then th is rocked over n_rock angles within
    +-delta_deg, the line position is fit against th and solved for
    target_px. th is left at the solution if it is within max_step_deg of
    the start (else back at the start). Returns a dict for
    XrtCalibration.add.
    """
    keV = energy_eV / 1000.0
    saved = getattr(xrt, 'th_correction', None)
    xrt.th_correction = None
    try:
        th_model = xrt.get_feespec_positions(keV, crystal_angle_offset=offset_deg)['crystal_angle']
    finally:
        xrt.th_correction = saved
    xrt.move_feespec_energy(keV, crystal_angle_offset=offset_deg)
    th = xrt.hxrsss.th
    th0 = float(th.position)
    ths, pxs, rows = [], [], []
    for t in th0 + np.linspace(-delta_deg, delta_deg, n_rock):
        th.umv(float(t))
        if settle_s:
            time.sleep(settle_s)
        r = line.read(frames)
        rows.append(dict(th=float(t), **{k: r.get(k) for k in ('px', 'fwhm_px', 'total', 'ok')}))
        log(f"    th {t:.4f}: line {r['px']:.1f} px" + ("" if r['ok'] else f" ({r['reason']})"))
        if r['ok']:
            ths.append(float(t))
            pxs.append(float(r['px']))
    sol = solve_th(ths, pxs, target_px)
    px_start = float(np.interp(th0, ths, pxs)) if len(ths) >= 2 else np.nan
    point = dict(energy_eV=energy_eV, th_model=th_model, th_best=sol['th'], ok=sol['ok'],
                 reason=sol['reason'], slope_px_per_deg=sol['slope'], r2=sol['r2'],
                 px_start=px_start, target_px=target_px, offset_deg=offset_deg,
                 th_start=th0, rocking=rows, px_best=np.nan)
    if sol['ok'] and abs(sol['th'] - th0) > max_step_deg:
        point.update(ok=False, reason=f"solution {sol['th'] - th0:+.3f} deg from start, "
                                      f"over {max_step_deg:g}")
    th.umv(float(sol['th']) if point['ok'] else th0)
    if point['ok'] and verify:
        if settle_s:
            time.sleep(settle_s)
        r = line.read(frames)
        point['px_best'] = r['px'] if r['ok'] else np.nan
    return point


def calibrate_xrt(cal, energies_eV, set_energy, xrt, line, offset_deg, target_px,
                  delta_deg=0.03, n_rock=3, settle_s=0.5, frames=5, log=print):
    """
    XRT calibration over energies_eV. set_energy(E) puts K and the DCCM so
    the DCCM line at E sits on the SASE. Fits cal after each point.
    """
    for e in energies_eV:
        log(f"  {e:.1f} eV")
        set_energy(e)
        p = measure_xrt_point(xrt, line, e, offset_deg, target_px, delta_deg, n_rock,
                              settle_s, frames, log=log)
        cal.add(**p)
        if p['ok']:
            log(f"    th {p['th_best']:.4f} (model {p['th_model']:.4f}, corr "
                f"{p['th_best'] - p['th_model']:+.4f} deg), {p['slope_px_per_deg']:.0f} px/deg, "
                f"line now {p['px_best']:.1f} px (target {target_px:.1f})")
        else:
            log(f"    NOT USED: {p['reason']}")
        cal.fit()
    return cal


# ---- plots --------------------------------------------------------------------

def plot_sase(cal, path):
    """Scans with fits, and center - K against K with the model. PNG at path."""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    fig = Figure(figsize=(11, 4.5))
    FigureCanvasAgg(fig)
    a1, a2 = fig.add_subplot(1, 2, 1), fig.add_subplot(1, 2, 2)
    for p in cal.points:
        if not p.get('energies_eV'):
            continue
        e = np.asarray([_nan(v) for v in p['energies_eV']])
        s = np.asarray([_nan(v) for v in p['signals']])
        mx = np.nanmax(s) if np.isfinite(s).any() else 1.0
        a1.plot(e - p['k_eV'], s / mx, '.-', label=f"K {p['k_eV']:.0f} {p.get('direction') or ''}")
    a1.set_xlabel('DCCM - K request (eV)')
    a1.set_ylabel('IPM / GDET (norm.)')
    a1.legend(fontsize=7)
    for d, mk in (('up', '^'), ('down', 'v'), (None, 'o')):
        sel = [p for p in cal.good() if p.get('direction') == d]
        if sel:
            a2.plot([p['k_eV'] for p in sel], [p['center_eV'] - p['k_eV'] for p in sel], mk,
                    label=d or 'no direction')
    bad = [p for p in cal.points if not p.get('ok') and p.get('center_eV') is not None]
    if bad:
        a2.plot([p['k_eV'] for p in bad], [p['center_eV'] - p['k_eV'] for p in bad], 'rx',
                label='not used')
    for name, m in cal.models.items():
        k = np.linspace(m['lo'] - cal.extrap_eV, m['hi'] + cal.extrap_eV, 100)
        a2.plot(k, [_peval(m, kk, cal.extrap_eV) + cal.shift_eV for kk in k], '-',
                label=f'fit {name}')
    a2.set_xlabel('K request (eV)')
    a2.set_ylabel('SASE center - K request (eV)')
    a2.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(path, dpi=90)
    return path


def plot_xrt(cal, path):
    """Correction against energy with the model. PNG at path."""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    fig = Figure(figsize=(6, 4.5))
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(1, 1, 1)
    good = cal.good()
    if good:
        ax.plot([p['energy_eV'] for p in good], [p['corr_deg'] for p in good], 'o', label='measured')
    if cal.model:
        m = cal.model
        e = np.linspace(m['lo'] - cal.extrap_eV, m['hi'] + cal.extrap_eV, 100)
        ax.plot(e, [_peval(m, ee, cal.extrap_eV) for ee in e], '-', label='fit')
    ax.set_xlabel('energy (eV)')
    ax.set_ylabel('crystal angle correction (deg)')
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=90)
    return path
