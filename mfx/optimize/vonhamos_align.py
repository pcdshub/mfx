"""
Von Hamos six-crystal spectrometer alignment.
  PVs: ami:ana:graph:data:centroids -> [cx, cy, rms]
       ami:ana:graph:data:goal      -> [goal_x, goal_y]
       ami:ana:graph:heartbeat      -> int
"""
import time
import logging
import numpy as np

log = logging.getLogger(__name__)

_PV_CEN  = "ami:ana:graph:data:centroids"
_PV_GOAL = "ami:ana:graph:data:goal"
_PV_HB   = "ami:ana:graph:heartbeat"

_NO_SIGNAL = 1e-3   # rms at or below this means "no signal" (AMI sentinel is 0)


class AMI:
    def __init__(self, fresh_events=3, timeout=10.0):
        from p4p.client.thread import Context
        self._ctx          = Context('pva')
        self._fresh_events = fresh_events
        self._timeout      = timeout
        self.goal_x        = float(np.asarray(self._ctx.get(_PV_GOAL, timeout=timeout))[0])

    def _wait_fresh(self):
        """Block until the heartbeat advances by fresh_events (or timeout)."""
        start    = int(self._ctx.get(_PV_HB))
        deadline = time.time() + self._timeout
        while time.time() < deadline:
            if int(self._ctx.get(_PV_HB)) >= start + self._fresh_events:
                return
            time.sleep(0.05)
        log.warning("heartbeat timeout — data may be stale")

    def _read(self):
        """Fresh [cx, cy, rms] for the first signal. Zeros if the PV is empty."""
        self._wait_fresh()
        arr = np.asarray(self._ctx.get(_PV_CEN), dtype=np.float32).flatten()
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
            if ami.centroid() is not None:
                confirmed += 1
        if confirmed == n_confirm:
            print(f"  signal at rot={pos:.2f}°")
            return True

    print(f"  no signal in [{lo:.1f}°, {hi:.1f}°]")
    return False


def measure_sensitivity(rot, ami, nudge=0.5):
    """cx shift (px) per degree of rot. None if the signal is lost."""
    before = ami.centroid()
    if before is None:
        return None
    p0 = rot.position
    rot.move(p0 + nudge)
    after = ami.centroid()
    rot.move(p0)
    if after is None:
        return None
    return (after[0] - before[0]) / nudge


def align_yaw(rot, ami, nudge=0.5, n_iter=15, tol=1.0, max_step=2.0):
    """Move rot to bring cx onto goal_x. Returns a result dict; check
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
        err = c[0] - ami.goal_x
        print(f"  yaw {i+1:2d}: cx={c[0]:.1f}  err={err:+.1f}")
        if abs(err) < tol:
            return {'converged': True, 'reason': None, 'cx': c[0], 'err': err, 'sens': sens}
        rot.move(rot.position + np.clip(-err / sens, -max_step, max_step))

    return {'converged': False, 'reason': 'did not converge', 'cx': c[0], 'err': err, 'sens': sens}


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


def align_one_crystal(crystal, ami):
    """find_signal -> align_yaw -> optimize_focus, then park rot where it
    started. Returns a result dict, or None if no signal could be found."""
    print(f"\n── {crystal.name}  goal_x={ami.goal_x:.1f} ──")
    park = crystal.rot.position

    if ami.centroid() is None and not find_signal(crystal.rot, ami):
        return None

    yaw         = align_yaw(crystal.rot, ami)
    focus       = optimize_focus(crystal.x, ami)
    aligned_rot = crystal.rot.position
    crystal.rot.move(park)

    if not yaw['converged']:
        print(f"  ! yaw did not converge: {yaw['reason']}")
    if not focus['converged']:
        print(f"  ! focus did not converge: {focus['reason']}")

    return {'rot': aligned_rot, 'x': focus['best_x'], 'yaw': yaw, 'focus': focus}


def align_all_crystals(spectrometer, ami):
    """Align c1..c6 one at a time, then restore each to its saved position."""
    saved = {}
    for i in range(1, 7):
        crystal = getattr(spectrometer, f"c{i}")
        result  = align_one_crystal(crystal, ami)
        if result:
            saved[f"c{i}"] = result

    print("\nRestoring saved positions…")
    for name, result in saved.items():
        crystal = getattr(spectrometer, name)
        crystal.rot.move(result['rot'])
        crystal.x.move(result['x'])

    return saved
