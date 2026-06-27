"""
Von Hamos six-crystal spectrometer alignment.
  PVs: ami:ana:graph:data:centroids -> [cx, cy, rms]
       ami:ana:graph:data:goal      -> [goal_x, goal_y]
       ami:ana:graph:heartbeats     -> int
"""
import os
import re
import subprocess
import time
import logging
import numpy as np

log = logging.getLogger(__name__)

_PV_CEN  = "ami:ana:graph:data:centroids"
_PV_GOAL = "ami:ana:graph:data:goal"
_PV_HB   = "ami:ana:graph:heartbeats"

_NO_SIGNAL = 1e-3   # rms at or below this means "no signal" (AMI sentinel is 0)


class AMIReadError(RuntimeError):
    """A PV could not be read at all (comms failure / timeout). Distinct from a
    successful read that simply shows no signal, so callers can stop driving
    motors instead of mistaking a dropout for 'nothing here'."""


def _parse_value(out, pv):
    # NTScalarArray:  "... [v1,v2,...]"  ("[]" when empty = a real no-signal read)
    m = re.search(r'\[([^\]]*)\]', out)
    if m:
        body = m.group(1).strip()
        return np.array([float(x) for x in body.split(',')]) if body else np.array([])
    # scalar fallback (e.g. heartbeats):  "... <int>"
    m = re.search(r'\b(\d+)\s*$', out.strip())
    if m:
        return np.array([float(m.group(1))])
    raise AMIReadError(f"could not parse pvget output for {pv}: {out!r}")


def _pvget(pv, timeout=5.0, addr="172.21.152.83", retries=1):
    """Read a PV's value via the PVAccess CLI. Returns a float array (possibly
    empty when the PV itself holds an empty array = no signal). Raises
    AMIReadError when the PV can't be read, with one retry to ride out a
    transient search timeout. `-w` gives pvget a real wait window so a cold
    connect to the off-broadcast host isn't cut short."""
    env  = {**os.environ, "EPICS_PVA_ADDR_LIST": addr}
    last = "unknown error"
    for attempt in range(retries + 1):
        try:
            result = subprocess.run(
                ["pvget", "-w", str(timeout), "-r", "value", pv],
                capture_output=True, timeout=timeout + 2, env=env, text=True,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            last = f"{type(exc).__name__}: {exc}"
        else:
            if result.returncode == 0:
                return _parse_value(result.stdout, pv)
            last = f"rc={result.returncode}: {result.stderr.strip()}"
        if attempt < retries:
            time.sleep(0.2)
    raise AMIReadError(f"pvget {pv} failed: {last}")


class AMI:
    def __init__(self, fresh_events=3, timeout=10.0, addr="172.21.152.83"):
        if addr:
            os.environ["EPICS_PVA_ADDR_LIST"] = addr   # PVA export moved off the broadcast domain
        self._addr         = addr
        self._fresh_events = fresh_events
        self._timeout      = timeout
        goal               = _pvget(_PV_GOAL, timeout=timeout, addr=addr)
        self.goal_x        = float(goal[0])
        self.goal_y        = float(goal[1])

    def _wait_fresh(self):
        """Block until the heartbeat advances by fresh_events. Propagates
        AMIReadError if the heartbeat PV can't be read, so the caller stops
        rather than driving motors against stale/absent data."""
        hb_timeout = min(3.0, self._timeout)
        start      = int(_pvget(_PV_HB, timeout=hb_timeout, addr=self._addr)[0])
        deadline   = time.time() + self._timeout
        while time.time() < deadline:
            if int(_pvget(_PV_HB, timeout=hb_timeout, addr=self._addr)[0]) >= start + self._fresh_events:
                return
            time.sleep(0.2)
        log.warning("heartbeat timeout — data may be stale")

    def _read(self):
        """Fresh [cx, cy, rms] for the first signal. Zeros if the PV is empty."""
        self._wait_fresh()
        arr = _pvget(_PV_CEN, timeout=self._timeout, addr=self._addr).astype(np.float32).flatten()
        return arr if arr.size >= 3 else np.zeros(3, dtype=np.float32)

    def centroid(self):
        """(cx, cy), or None if no signal."""
        arr = self._read()
        if arr[2] > _NO_SIGNAL:
            return (float(arr[0]), float(arr[1]))
        return None

    def rms(self):
        """Vertical RMS of the spot (minimize for focus); inf if no signal."""
        arr = self._read()
        return float(arr[2]) if arr[2] > _NO_SIGNAL else float('inf')


def find_signal(rot, ami, step=2.0, n_confirm=3):
    """Sweep rot up to its high limit, then down to its low limit, stopping at
    the first position where the centroid is seen n_confirm times in a row."""
    lo, hi = rot.limits
    p0     = rot.position
    if not np.isfinite(lo):
        lo = p0 - 15.0
    if not np.isfinite(hi):
        hi = p0 + 15.0

    sweep = np.concatenate([np.arange(p0, hi, step), np.arange(hi, lo, -step)])
    for pos in sweep:
        rot.move(pos)
        confirmed = 0
        for _ in range(n_confirm):
            try:
                seen = ami.centroid() is not None
            except AMIReadError as exc:
                print(f"  ! lost contact with AMI ({exc}) — stopping sweep at rot={rot.position:.2f}°")
                return False
            if seen:
                confirmed += 1
        if confirmed == n_confirm:
            print(f"  signal at rot={pos:.2f}°")
            return True

    print(f"  no signal in [{lo:.1f}°, {hi:.1f}°]")
    return False


def measure_sensitivity(rot, ami, nudge=0.5):
    """cy shift (px) per degree of rot. None if the signal is lost.

    The yaw moves the spot vertically (the detector is rotated 90°, so the streak
    lays horizontally), so the steered coordinate is cy, not cx."""
    before = ami.centroid()
    if before is None:
        return None
    p0 = rot.position
    rot.move(p0 + nudge)
    after = ami.centroid()
    rot.move(p0)
    if after is None:
        return None
    return (after[1] - before[1]) / nudge


def align_yaw(rot, ami, nudge=0.5, n_iter=15, tol=1.0, max_step=2.0):
    """Move rot to bring cy onto goal_y. Returns a result dict; check
    ['converged'], and ['reason'] when it did not converge."""
    sens = measure_sensitivity(rot, ami, nudge)
    if sens is None:
        return {'converged': False, 'reason': 'signal lost while measuring sensitivity'}
    if abs(sens) < 1e-6:
        return {'converged': False, 'reason': 'zero sensitivity'}

    for i in range(n_iter):
        c = ami.centroid()
        if c is None:
            return {'converged': False, 'reason': 'signal lost mid-iteration'}
        err = c[1] - ami.goal_y
        print(f"  yaw {i+1:2d}: cy={c[1]:.1f}  err={err:+.1f}")
        if abs(err) < tol:
            return {'converged': True, 'reason': None, 'cy': c[1], 'err': err, 'sens': sens}
        rot.move(rot.position + np.clip(-err / sens, -max_step, max_step))

    return {'converged': False, 'reason': 'did not converge', 'cy': c[1], 'err': err, 'sens': sens}


def optimize_focus(x_motor, ami, span=2.0, steps=11):
    """Scan x over +/-span and move to the position of minimum rms. Returns a
    result dict; check ['converged']."""
    start     = x_motor.position
    positions = np.linspace(start - span, start + span, steps)
    rms_vals  = []
    for p in positions:
        x_motor.move(p)
        rms_vals.append(ami.rms())
        print(f"  x={p:.3f}  rms={rms_vals[-1]:.2f}")

    if not np.isfinite(rms_vals).any():
        x_motor.move(start)
        return {'converged': False, 'reason': 'no signal during focus scan', 'best_x': start}

    best = float(positions[np.argmin(rms_vals)])
    x_motor.move(best)
    return {'converged': True, 'reason': None, 'best_x': best,
            'positions': positions.tolist(), 'rms': rms_vals}


def align_one_crystal(crystal, ami, interactive=True):
    """find_signal -> align_yaw -> optimize_focus, then park rot where it
    started. Returns a result dict, or None if no signal could be found.

    When interactive, pause after the auto-align so you can fine-tune the
    motors by hand (from a motor GUI or a second session), then press Enter.
    Whatever positions the motors are at when you continue are what gets saved."""
    print(f"\n── {crystal.name}  goal_y={ami.goal_y:.1f} ──")
    park = crystal.rot.position

    try:
        if ami.centroid() is None and not find_signal(crystal.rot, ami):
            return None
        yaw   = align_yaw(crystal.rot, ami)
        focus = optimize_focus(crystal.x, ami)
    except AMIReadError as exc:
        print(f"  ! lost contact with AMI ({exc}); skipping {crystal.name}")
        crystal.rot.move(park)
        return None

    if not yaw['converged']:
        print(f"  ! yaw did not converge: {yaw['reason']}")
    if not focus['converged']:
        print(f"  ! focus did not converge: {focus['reason']}")

    if interactive:
        c = ami.centroid()
        cy = c[1] if c else float('nan')
        print(f"  auto: rot={crystal.rot.position:.3f}°  x={crystal.x.position:.3f}mm  "
              f"cy={cy:.1f} (goal {ami.goal_y:.1f})  rms={ami.rms():.2f}")
        input(f"  fine-tune {crystal.name}, then press Enter to save and continue…")

    aligned_rot = crystal.rot.position
    aligned_x   = crystal.x.position
    print(f"  saved: rot={aligned_rot:.3f}°  x={aligned_x:.3f}mm")
    crystal.rot.move(park)

    return {'rot': aligned_rot, 'x': aligned_x, 'yaw': yaw, 'focus': focus}


def align_all_crystals(spectrometer, ami, interactive=True):
    """Align c1..c6 one at a time, then restore each to its saved position.
    When interactive, pause after each crystal so you can fine-tune it by hand
    before its position is saved."""
    saved = {}
    for i in range(1, 7):
        crystal = getattr(spectrometer, f"c{i}")
        result  = align_one_crystal(crystal, ami, interactive=interactive)
        if result:
            saved[f"c{i}"] = result

    print("\nRestoring saved positions…")
    for name, result in saved.items():
        crystal = getattr(spectrometer, name)
        crystal.rot.move(result['rot'])
        crystal.x.move(result['x'])

    return saved
