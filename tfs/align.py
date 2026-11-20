"""
Align TFS lenses on the beam, one lens at a time, with a downstream YAG (DG2).

    from tfs.align import *
    cam = gigE_camera_accessor("MFX:GIGE:DG2:YAG")

    combo = tfs.find_best_combo(enable_prefocus=False, avoid_forbidden=True)
    align_lenses(tfs, combo.lenses, cam)

Both align_lens and align_lenses print what they do, lens by lens. method="centroid" uses the centroid
method for every lens.

Centroid method: an off-center lens bends the beam like a prism, so the beam
centroid on DG2 moves with the lens. Move the lens until the centroid is back on
the spot it hits without the lens.

Ring method: the edge of a lens's aperture casts a thin ring on DG2, dark or bright. The
ring moves with the lens, much more than the centroid does (tfs_06 x: about
270 px/mm against 4 px/mm). Move the lens until the ring is centered on the
spot. A lens with no ring (a beam narrower than its aperture), or whose ring does
not converge, goes back to where it was and its IN_SET is left as it is: the centroid moves
about 4 px per mm of lens against 10 px of frame-to-frame jitter at the hutch, too little to
align on.
Where the ring should be comes from the optics: its size from the lens's aperture, energy and
distance to DG2, and how far it moves per mm of lens (thin lenses, rays through the aperture's
edges). The candidates are the circles of that size in the image divided by one with all lenses
out, which leaves only what the lens changed: a matched filter on its thin dark and bright lines.
The lens then steps in x and in y; the ring is the candidate that moved as the optics says. Fixed
marks on the YAG and the beam's own edges don't move with the lens. If none or several did, the
frame is shown with the candidates numbered and the operator clicks the ring. The spot is
measured once, from many frames (the centroid jumps 10 px from frame to frame), and every lens is
centred on it.

A lens illegal alone is aligned with a partner in: its own edge doesn't show behind the
partner's, but it focuses the light through the partner's aperture, which shrinks the partner's
ring and moves it with the lens (about L/f of the lens's offset). It is moved until the
partner's shrunk ring is centred where the partner's ring is without it.

Both assume camera x/y are along motor x/y.

The lens interlock faults when a lens is neither In nor Out, which includes every y move, and when
the lenses in are an illegal configuration at the beam energy; while faulted it puts attenuator
blade 11 in. Lenses are aligned with the prefocus lenses out. Before anything moves, align_lenses
checks each configuration it will use against the interlock's rules and prints the plan: a lens
that is illegal alone is aligned with the fewest lenses already aligned that make it legal, in at
their aligned positions, or else with a helper lens from outside the combo, taken out at the end. Before each image the code waits for the interlock to clear and puts the transmission
and pulse picker back. A lens reads In only within IN_DELTA of IN_SET, so IN_DELTA is 1 mm while
aligning; at the end it asks before writing the aligned y to IN_SET.
"""
import contextlib
import io
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path

import numpy as np
from epics import caget, caput
from scipy import fft, ndimage
from skimage.filters import sato

from tfs.transfocator_scan import gigE_camera_accessor

__all__ = ["gigE_camera_accessor", "align_lens", "align_lenses"]

INTERLOCK = "MFX:LENS:BEAM"
BLADE = "MFX:ATT:11"  # the attenuator blade the interlock puts in
ALIGN_DELTA = 1.0  # mm, IN_DELTA while a lens is being aligned
SPOT_FRAMES = 50  # frames averaged for the spot and the all-lenses-out image (10 s at 5 Hz)


# -- image analysis -----------------------------------------------------------------------------


def _centroid(image, threshold=0.1):
    """Beam centroid (col, row) in pixels, background subtracted."""
    image = image - np.median(image)
    image[image < threshold * image.max()] = 0
    if not image.sum() > 0:
        raise RuntimeError("no beam on the camera: check the beam, the pulse picker, the YAG and the attenuator")
    rows, cols = np.indices(image.shape)
    return np.array([(cols * image).sum(), (rows * image).sum()]) / image.sum()


def _ridges(image, reference):
    """
    The thin dark lines and the thin bright lines in image / reference, which leaves what the lens changed:
    scikit-image's Sato ridge filter, weighted by the square root of the beam (shot noise), less its local
    median. Returns ({"dark": map, "bright": map}, where the maps are, where the beam is).
    """
    ref = ndimage.gaussian_filter(reference.astype(float), 2)
    lit = ref > 0.2 * ref.max()  # the ratio is noise where the reference is dark
    ratio = np.where(lit, ndimage.gaussian_filter(image.astype(float), 1) / np.maximum(ref, 1e-9), 1.0)
    ratio = np.minimum(ratio, np.percentile(ratio[lit], 99.5))
    inside = ndimage.binary_erosion(lit, iterations=8)  # away from the beam's edge
    maps = {}
    for kind in ("dark", "bright"):
        line = sato(ratio, sigmas=[1, 2, 3], black_ridges=kind == "dark") * np.sqrt(ref)
        maps[kind] = np.where(inside, line - ndimage.median_filter(line, 15), 0.0)
    return maps, inside, lit


def _circles(line, inside, lit, radii, count=3, near=None, within=None):
    """
    The `count` circles (col, row, radius, score) with a radius in `radii` that run along the most of ridge map
    `line`, best first: a matched filter, the map convolved with a thin ring of each radius, and the parabola
    through each peak for its fraction of a pixel. A circle's centre is in the beam, within `within` px of
    `near` if given, and half of it at least is in the beam. score: its strength over the frame's spread.
    """
    shape = line.shape
    rows, cols = np.indices(shape)
    distance = np.hypot(rows - shape[0] // 2, cols - shape[1] // 2)
    lines, area = fft.rfft2(line), fft.rfft2(inside.astype(float))
    best, best_radius = np.full(shape, -np.inf), np.zeros(shape)
    for radius in radii:
        ring = fft.rfft2(fft.ifftshift(np.clip(1.5 - np.abs(distance - radius), 0, 1)))
        total, n = fft.irfft2(lines * ring, shape), fft.irfft2(area * ring, shape)
        score = np.where(n > 1.5 * np.pi * radius, total / np.maximum(n, 1.0), -np.inf)
        better = score > best
        best[better], best_radius[better] = score[better], radius
    best[~lit] = -np.inf
    if near is not None:
        best[np.hypot(cols - near[0], rows - near[1]) > within] = -np.inf
    scores = best[np.isfinite(best)]
    if not scores.size:
        return []
    spread = 1.48 * np.median(np.abs(scores - np.median(scores))) or 1.0
    rows, cols = np.nonzero(np.isfinite(best) & (best == ndimage.maximum_filter(best, size=max(3, int(min(radii)) // 2))))
    found = []
    for i in np.argsort(best[rows, cols])[::-1][:count]:
        row, col = rows[i], cols[i]
        found.append((col + _vertex(best[row, col - 1:col + 2]), row + _vertex(best[row - 1:row + 2, col]),
                      best_radius[row, col], (best[row, col] - np.median(scores)) / spread))
    return found


def _vertex(y):
    """Where the parabola through three values one pixel apart peaks, from the middle one."""
    curve = y[0] - 2 * y[1] + y[2] if len(y) == 3 and np.all(np.isfinite(y)) else 0.0
    return float(np.clip(0.5 * (y[0] - y[2]) / curve, -0.5, 0.5)) if curve < 0 else 0.0


def _circle(cols, rows):
    """Least-squares circle (col, row, radius) through points: x^2 + y^2 + D x + E y + F = 0."""
    A = np.column_stack([cols, rows, np.ones_like(cols)])
    (D, E, F), *_ = np.linalg.lstsq(A, -(cols ** 2 + rows ** 2), rcond=None)
    col, row = -D / 2, -E / 2
    return np.array([col, row, np.sqrt(max(col ** 2 + row ** 2 - F, 0.0))])


def _candidates(image, reference, radii, count=3, near=None, within=None):
    """
    The circles in image / reference that may be a lens's ring, strongest first, as (circle, kind, score):
    `count` dark ones and `count` bright ones (an edge shows either way), each circle once.
    """
    maps, inside, lit = _ridges(image, reference)
    found = sorted(((np.array(c[:3]), kind, c[3]) for kind in maps
                    for c in _circles(maps[kind], inside, lit, radii, count, near, within)), key=lambda c: -c[2])
    kept = []
    for circle, kind, score in found:
        if all(np.hypot(*(circle[:2] - other[:2])) > 10 for other, _, _ in kept):
            kept.append((circle, kind, score))
    return kept[:count]


def _find_ring(image, reference, radii, centre=None, within=80):
    """
    The strongest circle (col, row, radius) px in image / reference with a radius in `radii` (low, high) and,
    given a `centre` (col, row), within `within` px of it; None if there is none. Strongest is not proof:
    _pick_ring checks that a circle moves with the lens.
    """
    found = _candidates(image, reference, np.arange(radii[0], radii[1], 1.0), 1, centre, within)
    return found[0][0] if found else None


# -- where a ring should be: the optics ---------------------------------------------------------

DG2_Z = 397.095  # m, DG2's YAG in tfs z (source at 0): LCLS z 1021.74 m
DG2_PIXEL = 3.76e-6  # m on the YAG per camera pixel: the size and the motion of the 2026-11-16 rings


def _aperture(lens):
    """A TFS lens's aperture radius [m]: 2 R0 = 63.2 um sqrt(R [um]), Confluence's "Working Transfocator Combinations"."""
    return 31.6e-6 * np.sqrt(float(lens.radius))


def _ray(lenses, energy, slope, offsets):
    """
    A paraxial ray from the source (tfs z 0, on axis) at `slope` through thin `lenses`, each `offsets[lens]` m
    off the axis: its height [m] at each lens, and on DG2.
    """
    y, z, at = 0.0, 0.0, {}
    for lens in sorted(lenses, key=lambda lens: float(lens.z)):
        y += slope * (float(lens.z) - z)
        z, at[lens] = float(lens.z), y
        slope -= (y - offsets.get(lens, 0.0)) / lens.focus(energy)
    return at, y + slope * (DG2_Z - z)


def _expected_ring(ring_lens, moved, lenses, energy):
    """
    The ring of `ring_lens`'s aperture on DG2 with `lenses` in at `energy` [eV]: its radius [px], and how many px
    it moves per mm of `moved`. The rays through the aperture's edges, thin lenses as in MFX's LensConnect.
    """
    on_axis, through = _ray(lenses, energy, 1.0, {}), _ray(lenses, energy, 0.0, {moved: 1e-3})
    edges = []
    for height in (-_aperture(ring_lens), _aperture(ring_lens)):
        height += 1e-3 if ring_lens is moved else 0.0
        slope = (height - through[0][ring_lens]) / on_axis[0][ring_lens]
        edges.append(through[1] + slope * on_axis[1])
    return abs(edges[1] - edges[0]) / 2 / DG2_PIXEL, (edges[0] + edges[1]) / 2 / DG2_PIXEL


def _check_bright(image, min_counts=20):
    """Stop if the beam's peak is less than `min_counts` over the background: rings are lost in the noise."""
    peak = float(image.max() - np.median(image))
    if peak < min_counts:
        raise RuntimeError(f"DG2 peak {peak:.0f} counts over the background, too dim to align on: "
                           f"raise the transmission and run again")


# -- camera and motors --------------------------------------------------------------------------


def _fresh_image(camera, average=5, timeout=10.0):
    """
    The mean of `average` frames taken after this call. The camera serves its
    last frame, which can predate a move, so the first new frame is skipped.
    """
    _beam_back()
    counter = camera.camera_pv + ":IMAGE1:ArrayCounter_RBV"
    deadline = time.monotonic() + timeout
    last = caget(counter) + 1
    frames = []
    while len(frames) < average:
        if time.monotonic() > deadline:
            raise TimeoutError(f"{camera.camera_pv}: {len(frames)} of {average} new frames in {timeout} s")
        count = caget(counter)
        if count > last:
            frames.append(camera.get_image().astype(float))
            last = count
        else:
            time.sleep(0.01)
    image = np.mean(frames, axis=0)
    _note("frames", image)
    return image


def _wait_for(pv, value, timeout=30.0):
    """Wait until `pv` reads `value`."""
    deadline = time.monotonic() + timeout
    while caget(pv) != value:
        if time.monotonic() > deadline:
            raise TimeoutError(f"{pv} not {value} after {timeout} s")
        time.sleep(0.02)


def _wait_stopped(motor):
    """Wait for the motor record's done-moving flag (.DMOV)."""
    _wait_for(motor.prefix + ".DMOV", 1)
    _note("moves", motor.name, _readback(motor))


_RECORD = None  # while align_lenses runs: the frames it took and where the motors stopped


def _note(kind, *values):
    if _RECORD is not None:
        _RECORD[kind].append((time.time(), *values))


class _Tee(io.StringIO):
    """Prints, and keeps a copy."""

    def __init__(self, out):
        super().__init__()
        self.out = out

    def write(self, text):
        self.out.write(text)
        return super().write(text)


@contextlib.contextmanager
def _recording():
    """
    Record the frames (_fresh_image), the motors' stops (_wait_stopped) and what is printed, and zip them to
    ~/tfs_align_<date>_<time>.zip at the end, however it ends: frames.npz, moves.csv, printed.txt.
    """
    global _RECORD
    _RECORD, printed = {"frames": [], "moves": []}, _Tee(sys.stdout)
    try:
        with contextlib.redirect_stdout(printed):
            yield
    finally:
        record, _RECORD = _RECORD, None
        path = Path.home() / f"tfs_align_{time.strftime('%Y%m%d_%H%M%S')}.zip"
        frames = io.BytesIO()
        np.savez(frames, times=np.array([t for t, _ in record["frames"]]),
                 frames=np.array([image for _, image in record["frames"]], dtype=np.float32))
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as saved:
            saved.writestr("frames.npz", frames.getvalue())
            saved.writestr("moves.csv", "time,motor,readback\n" + "".join(f"{t:.3f},{motor},{at:.4f}\n"
                                                                          for t, motor, at in record["moves"]))
            saved.writestr("printed.txt", printed.getvalue())
        print(f"saved {len(record['frames'])} frames and {len(record['moves'])} motor stops to {path}")


_SAVED = {}  # the transmission and pulse picker state when the alignment started


def _save_beam():
    """Save the transmission and the pulse picker's state, which _beam_back puts back."""
    from mfx.db import mfx_attenuator as att, mfx_pulsepicker as pp

    _SAVED.update(att=float(caget(att.prefix + ":COM:R_DES")), pp=pp.position)
    print(f"saved: att {_SAVED['att']:.3g}, pulse picker {_SAVED['pp']}")


def _beam_back():
    """
    Wait for the lens interlock to clear, then take blade 11 out if it is in, by re-applying the
    saved transmission, and put the pulse picker back as saved, as lens_minder does after a lens move.
    """
    from mfx.db import mfx_attenuator as att, mfx_pulsepicker as pp

    _wait_for(INTERLOCK + ":FAULTED", 0)
    deadline = time.monotonic() + 30.0
    while att.done.get() != att.done_value:  # COM:STATUS: the interlock may still be putting blade 11 in
        if time.monotonic() > deadline:
            raise TimeoutError("attenuator still moving after 30 s")
        time.sleep(0.05)
    if caget(BLADE + ":STATE", as_string=True) == "IN":
        att.mv(_SAVED.get("att", caget(att.prefix + ":COM:R_DES")), wait=True)
        while caget(BLADE + ":STATE", as_string=True) != "OUT":
            if time.monotonic() > deadline:
                raise TimeoutError(f"{BLADE} not OUT after 30 s")
            time.sleep(0.05)
    state = _SAVED.get("pp")
    if state in ("OPEN", "CLOSED") and pp.position != state:
        print(f"pulse picker {pp.position}, back to {state}")
        (pp.open if state == "OPEN" else pp.close)(wait=True)


def _readback(motor):
    """Where the motor is (.RBV). A lens motor's `position` is its setpoint."""
    return float(caget(motor.prefix + ".RBV"))


def _move(motor, target):
    motor.mv(target, wait=True)
    _wait_stopped(motor)


def _step_by(motor, distance):
    """Move by `distance` mm; returns how far it actually moved. Stops if it did not move."""
    start = _readback(motor)
    _move(motor, start + distance)
    moved = _readback(motor) - start
    if moved == 0:
        raise RuntimeError(f"{motor.prefix} did not move from {start:.4f}")
    return moved


def _insert(lens):
    """Insert, then wait for y to stop: lens.insert(wait=True) returns as soon as the lens reads In."""
    lens.insert(wait=True)
    _wait_stopped(lens.y)


def _remove(lens):
    lens.remove(wait=True)
    _wait_stopped(lens.y)


def _together(task, items):
    """task(item) for every item at once, each in its own thread: ladders travel together."""
    with ThreadPoolExecutor(max_workers=max(1, len(items))) as pool:
        list(pool.map(task, items))


def _put_back(removed):
    """Move each lens back to its saved x and y. lens.insert would move it to IN_SET instead."""
    for lens, (x, y) in removed.items():
        _move(lens.x, x)
        _move(lens.y, y)


_FAULTS = {"state_fault": "lens position unknown", "min_fault": "energy below the minimum for the lenses in",
           "lens_required_fault": "a TFS lens is required with the lenses in",
           "table_fault": "effective radius in a disallowed area"}


def _interlock_faults(tfs):
    """The TFS interlock's active faults, by MFX's descriptions; empty if it is not faulted."""
    if not tfs.interlock.faulted.get():
        return []
    return [text for name, text in _FAULTS.items() if getattr(tfs.interlock, name).get()] or ["faulted"]


def _check_interlock(tfs):
    """Stop before anything moves if the TFS interlock is already faulted."""
    faults = _interlock_faults(tfs)
    if faults:
        raise RuntimeError(f"TFS interlock faulted: {', '.join(faults)}")


def _in_record(lens):
    """The lens's states record, MFX:TFS:XFLS:nn, with its IN_SET and IN_DELTA."""
    return "MFX:TFS:XFLS:" + lens.prefix.rsplit(":", 1)[1]


# The interlock PLC's rules for each prefocus lens radius: its table, and the energies [eV] from which it may
# be in and up to which it needs a TFS lens in with it. Without a prefocus lens: NO_LENS.
_PREFOCUS = {750: ("LENS1_750", 5960, 8020), 428: ("LENS2_428", 8280, 10020), 333: ("LENS3_333", 9500, 11110)}
NONE_IN = 10000.0  # um, the PLC's effective radius with no TFS lens in


def _radius(lenses):
    """The TFS lenses' effective radius 1/sum(1/R) in um, as the interlock computes it."""
    radii = [float(lens.radius) for lens in lenses if float(lens.radius) > 0]
    return 1 / sum(1 / r for r in radii) if radii else NONE_IN


def _trip_range(prefocus, energy):
    """The interlock's trip range (low, high) in um at `energy`, interpolated in transfocate's table as the
    PLC does; None outside the table."""
    from transfocate.table.info import data

    table = data[_PREFOCUS[int(prefocus.radius)][0] if prefocus else "NO_LENS"]
    e = table["energy"].to_numpy()
    if not e[0] <= energy <= e[-1]:
        return None
    return float(np.interp(energy, e, table["trip_min"])), float(np.interp(energy, e, table["trip_max"]))


def _trips(lenses, energy, prefocus=None):
    """Why the interlock would fault with the TFS `lenses` and `prefocus` in at `energy`, or None."""
    if prefocus is not None:
        _, minimum, needs_tfs = _PREFOCUS[int(prefocus.radius)]
        if energy < minimum:
            return f"{energy:.0f} eV is below the prefocus lens's minimum, {minimum} eV"
        if energy <= needs_tfs and not lenses:
            return "the prefocus lens needs a TFS lens in"
    trip, radius = _trip_range(prefocus, energy), _radius(lenses)
    if trip is not None and trip[1] > trip[0] and trip[0] <= radius <= trip[1]:
        return f"{radius:.1f} um is in the trip range {trip[0]:.1f}-{trip[1]:.1f} um"
    return None


def _plan(lenses, energy, prefocus=None, spares=()):
    """
    ([(lens, partners)], helpers): the lenses legal alone first, each aligned alone (no partners), then each
    of the others with the fewest lenses already aligned that make it legal (partners). If none do, a lens
    legal alone from `spares` is aligned first to be one (a helper, out at the end). Prints it. Raises before
    anything moves if a step would fault the interlock, or the lenses with `prefocus` at the end would.
    """
    if _trips([], energy):
        raise RuntimeError(f"all lenses out would fault the interlock: {_trips([], energy)}")
    plan = [(lens, ()) for lens in lenses if not _trips([lens], energy)]
    aligned, helpers = [lens for lens, _ in plan], []
    spares = sorted((lens for lens in spares if lens not in lenses and not _trips([lens], energy)),
                    key=lambda lens: float(lens.radius))  # the strongest first: fewer helpers
    todo = [lens for lens in lenses if lens not in aligned]
    while todo:
        step = next(((lens, partners) for lens in todo for n in range(1, len(aligned) + 1)
                     for partners in combinations(aligned, n) if not _trips([*partners, lens], energy)), None)
        if step is None:
            if not spares:
                raise RuntimeError(f"{todo[0].attr_name} would fault the interlock with any of the lenses legal "
                                   f"alone in ({_trips([todo[0]], energy)} alone)")
            helper = spares.pop(0)
            plan.append((helper, ()))
            aligned.append(helper)
            helpers.append(helper)
            continue
        plan.append(step)
        aligned.append(step[0])
        todo.remove(step[0])
    end = _trips(lenses, energy, prefocus)
    if end:
        raise RuntimeError(f"the lenses in together would fault the interlock: {end}")
    low, high = _trip_range(None, energy) or (0, 0)
    print(f"plan at {energy:.0f} eV, no prefocus lens, trip range {low:.1f}-{high:.1f} um:")
    for lens, partners in plan:
        with_ = f"with {', '.join(p.attr_name for p in partners)} in ({_radius([lens, *partners]):.1f} um)" \
            if partners else f"alone ({_radius([lens]):.0f} um)"
        print(f"  {lens.attr_name} {with_}{', a helper: out at the end' if lens in helpers else ''}")
    if prefocus is not None:
        print(f"  then {prefocus.attr_name} in with them")
    return plan, helpers


def _in_windows(lenses, delta):
    """Set each lens's IN_DELTA to `delta`. Returns {lens: (IN_SET, IN_DELTA)} as they were."""
    before = {lens: (caget(_in_record(lens) + ":IN_SET"), caget(_in_record(lens) + ":IN_DELTA")) for lens in lenses}
    for lens, (_, old) in before.items():
        caput(_in_record(lens) + ":IN_DELTA", max(old, delta), wait=True)
    print(f"IN_DELTA {delta:g} while aligning; was {_deltas(before)}")
    return before


def _restore_windows(before):
    for lens, (_, delta) in before.items():
        caput(_in_record(lens) + ":IN_DELTA", delta, wait=True)
    print(f"IN_DELTA back: {_deltas(before)}")


def _deltas(before):
    """Each lens's IN_DELTA as saved, for the printout: "tfs_03 0.2, tfs_05 0.5"."""
    return ", ".join(f"{lens.attr_name} {delta:g}" for lens, (_, delta) in before.items())


def _finish(aligned, before, write_in_set):
    """
    Show each lens's IN_SET and its aligned y, ask before writing them (unless `write_in_set` is
    True or False), then put the lenses in: at their aligned x and y, or with n at their old IN_SET.
    """
    for lens, (_, y) in aligned.items():
        print(f"{lens.attr_name}  IN_SET {before[lens][0]:.4f} -> {y:.4f}")
    if write_in_set is None:
        write_in_set = input("Write these IN_SETs? [y/n] ").strip().lower().startswith("y")
    if write_in_set:
        for lens, (_, y) in aligned.items():
            caput(_in_record(lens) + ":IN_SET", round(y, 4), wait=True)
        _together(lambda lens: _put_back({lens: aligned[lens]}), list(aligned))
        print(f"in: {', '.join(lens.attr_name for lens in aligned)} at their aligned x and y")
    else:
        _together(_insert, list(aligned))
        print(f"in: {', '.join(lens.attr_name for lens in aligned)} at their aligned x and old IN_SET")
        moves = [f"tfs.{lens.attr_name}.y.mv({y:.4f})" for lens, (_, y) in aligned.items()
                 if round(y, 4) != round(before[lens][0], 4)]
        if moves:
            print("to put them at their aligned y without writing IN_SET:\n  " + "\n  ".join(moves))


# -- centroid method ----------------------------------------------------------------------------


def _centroid_steps(motor, axis, camera, spot, step=0.02, iterations=3, max_move=0.2):
    """
    Move `motor` (camera `axis` 0 for x, 1 for y) until the centroid is on `spot`.
    Each iteration measures px per mm with a `step` mm move, then moves at most
    `max_move` mm toward the spot. A correction that leaves the centroid more than
    1 px further from the spot is undone and the steps stop: near the aperture's
    edge the centroid can move the wrong way.
    """
    for _ in range(iterations):
        start = _readback(motor)
        before = _centroid(_fresh_image(camera))[axis]
        moved = _step_by(motor, step)
        after = _centroid(_fresh_image(camera))[axis]
        gain = (after - before) / moved
        correction = (spot[axis] - before) / gain if gain else 0.0
        _move(motor, start + np.clip(correction, -max_move, max_move))
        now = _centroid(_fresh_image(camera))[axis]
        if abs(spot[axis] - now) > abs(spot[axis] - before) + 1.0:  # 1 px: more than noise
            _move(motor, start)
            print(f"{motor.name}: the centroid moved away from the spot, back to {start:.4f}")
            return


def _align_centroid(lens, camera, spot, step=0.02, iterations=3, max_move=0.2, expect=None):
    """Move `lens` until the centroid is on `spot`, with only that lens in. Distances in mm."""
    _centroid_steps(lens.x, 0, camera, spot, step, iterations, max_move)
    _centroid_steps(lens.y, 1, camera, spot, step, iterations, max_move)
    print(f"{lens.attr_name}: x {_readback(lens.x):.4f}, y {_readback(lens.y):.4f}")


# -- ring method --------------------------------------------------------------------------------


def _pick_ring(lens, camera, step, reference, targets, lenses, energy, ask=True, frames=10, size=0.1,
               motion=(0.6, 1.4)):
    """
    The ring to align `lens` on: (ring, px it moves per mm of x and of y, a function that finds it in a frame,
    where it should be), or Nones. It is the aperture ring of one of `targets` ({lens: where its ring should
    be}) with `lenses` in. The candidates are the circles of the size the optics expects (within `size`), dark
    or bright. Each motor steps `step` mm and back: the ring is the candidate that moved as the optics says
    (`motion`: a fraction of that) along the step and little across it. If not exactly one did, the
    operator picks one on the frame (`ask`), or there is none.
    """
    image = _fresh_image(camera, frames)
    expected = {ring_lens: _expected_ring(ring_lens, lens, lenses, energy) for ring_lens in targets}
    found = sorted(((*c, ring_lens) for ring_lens, (radius, _) in expected.items() for c in
                    _candidates(image, reference, np.arange((1 - size) * radius, (1 + size) * radius, 1.0))),
                   key=lambda c: -c[2])
    shifts = [[] for _ in found]
    for axis, motor in enumerate([lens.x, lens.y]):
        start = _readback(motor)
        moved = _step_by(motor, step)
        ridges = _ridges(_fresh_image(camera, frames), reference)
        _move(motor, start)
        for (circle, kind, _, ring_lens), shift in zip(found, shifts):
            distance = abs(expected[ring_lens][1] * moved)
            after = _same_ring(ridges, kind, circle, circle[:2], 1.6 * distance + 5)
            d = after[:2] - circle[:2] if after is not None else np.full(2, np.nan)
            shift.append((d[axis] / moved, motion[0] * distance <= abs(d[axis]) <= motion[1] * distance
                          and abs(d[1 - axis]) <= 0.25 * distance + 1.5))
    passed = [i for i, shift in enumerate(shifts) if all(ok for _, ok in shift)]
    # a circle that touches the ring moves with it, but runs along it only where they touch: much weaker
    if len(passed) > 1 and found[passed[0]][2] >= 2 * found[passed[1]][2]:
        passed = passed[:1]
    print(f"{lens.attr_name}: expect " + "; ".join(f"{ring_lens.attr_name}'s ring, {radius:.0f} px moving {abs(gain):.0f} "
                                                  f"px/mm" for ring_lens, (radius, gain) in expected.items()))
    for i, ((circle, kind, score, ring_lens), shift) in enumerate(zip(found, shifts)):
        print(f"  {i + 1}: ({circle[0]:.1f}, {circle[1]:.1f}) r {circle[2]:.1f} {kind}, {ring_lens.attr_name}'s size, strength "
              f"{score:.0f}, moves {shift[0][0]:.0f}, {shift[1][0]:.0f} px/mm{'  <- as expected' if i in passed else ''}")
    choice = passed[0] if len(passed) == 1 else _ask(image, reference, found, passed, lens.attr_name) \
        if ask and found else None
    if choice is None:
        return None, None, None, None
    circle, kind, _, ring_lens = found[choice]
    # picked by hand though it did not move as expected: the optics' gain (camera x/y along motor x/y)
    gains = [g if choice in passed else expected[ring_lens][1] for g, _ in shifts[choice]]
    last = [circle]

    def find(image):
        """The ring near where it last was, its size and kind."""
        ring = _same_ring(_ridges(image, reference), kind, circle, last[0][:2], 0.3 * max(map(abs, gains)) + 10)
        last[0] = last[0] if ring is None else ring
        return ring

    return circle, gains, find, np.asarray(targets[ring_lens])


def _same_ring(ridges, kind, circle, near, within):
    """The circle of `circle`'s kind and radius (+-2 px) in `ridges` (_ridges) within `within` px of `near`, or None."""
    found = _circles(ridges[0][kind], *ridges[1:], np.arange(circle[2] - 2, circle[2] + 2.5), 1, near, within)
    return np.array(found[0][:3]) if found else None


def _ask(image, reference, found, passed, name):
    """
    Show the frame and the frame / the lenses-out one, the candidates numbered (solid: moved as expected).
    The operator clicks on or inside the ring's circle, or outside them all for none, and confirms in the
    terminal. Returns its index or None. Without a window, the operator types its number.
    """
    import matplotlib.pyplot as plt

    print(f"{name}: {len(passed) or 'no'} candidates moved as expected; pick the ring")
    fig = None
    try:
        if plt.get_backend().lower() == "agg":  # no display: ginput would wait for a click forever
            raise RuntimeError("matplotlib has no window (backend agg)")
        ref = ndimage.gaussian_filter(reference.astype(float), 2)
        ratio = np.where(ref > 0.2 * ref.max(), image / np.maximum(ref, 1e-9), np.nan)
        fig, axes = plt.subplots(1, 2, figsize=(13, 6.5), sharex=True, sharey=True)
        fig.suptitle(f"{name}: click on or inside its ring's circle, or outside them all for none")
        drawn = [[] for _ in found]
        for ax, shown, title in ((axes[0], image, "frame"), (axes[1], ratio, "frame / all lenses out")):
            ax.imshow(shown, vmin=np.nanpercentile(shown, 1), vmax=np.nanpercentile(shown, 99.5))
            ax.set_title(title)
            for i, (circle, *_) in enumerate(found):
                colour = ["white", "red", "magenta", "orange", "cyan", "lime"][i % 6]
                drawn[i] += [ax.add_patch(plt.Circle(circle[:2], circle[2], fill=False, color=colour, lw=2,
                                                     ls="-" if i in passed else "--")),
                             ax.text(*(circle[:2] + 0.75 * circle[2] * np.array([1, -1])), str(i + 1), color=colour,
                                     fontsize=16, fontweight="bold")]
        while True:
            click = plt.ginput(1, timeout=0)
            if not click:
                return None
            distance = [np.hypot(*(np.array(click[0]) - circle[:2])) for circle, *_ in found]
            near = [i for i, (circle, *_) in enumerate(found) if distance[i] < circle[2] + 15]
            chosen = min(near, key=lambda i: abs(distance[i] - found[i][0][2])) if near else None
            for i, artists in enumerate(drawn):  # the chosen one bold, the others faded
                for artist in artists:
                    artist.set_alpha(1 if chosen in (None, i) else 0.3)
                artists[0].set_linewidth(4 if i == chosen else 2)
            plt.pause(0.1)
            circle = found[chosen][0] if near else None
            question = f"ring {chosen + 1} at ({circle[0]:.0f}, {circle[1]:.0f}) r {circle[2]:.0f}" if near else \
                "no ring, keep its IN_SET"
            if input(f"{name}: {question}? [y/n] ").strip().lower().startswith("y"):
                return chosen
    except Exception as error:  # noqa: BLE001  no window here: ask in the terminal
        print(f"no window ({error})")
        answer = input("its ring's number, or Enter for none: ").strip()
        return int(answer) - 1 if answer.isdigit() and 0 < int(answer) <= len(found) else None
    finally:
        if fig is not None:
            plt.close(fig)


def _ring_steps(lens, camera, spot, ring, gains, iterations=6, max_move=0.2, tolerance_px=1.0, find=None):
    """
    Move the lens until the ring is centered on `spot` within `tolerance_px`,
    each move at most `max_move` mm. Returns the last ring, or None if lost.
    """
    if ring is None or None in gains or 0 in gains:
        return ring
    for _ in range(iterations):
        if ring is None:
            break
        error = spot - ring[:2]
        if np.all(np.abs(error) < tolerance_px):
            break
        for axis, motor in enumerate([lens.x, lens.y]):
            _move(motor, _readback(motor) + np.clip(error[axis] / gains[axis], -max_move, max_move))
        ring = find(_fresh_image(camera))
    return ring


def _align_ring(lens, camera, spot, step=0.05, iterations=6, max_move=0.2, tolerance_px=1.0, accept_px=3.0,
                expect=None):
    """
    Move `lens` until its ring (_pick_ring, with `expect`) is where it should be: on `spot` for its own ring,
    where a partner's ring was without it. Distances in mm. Returns True if the ring ends within `accept_px`
    of there. Otherwise (no ring, or one that does not converge) the lens goes back to where it started and
    it returns False.
    """
    start = _readback(lens.x), _readback(lens.y)
    ring, gains, find, spot = _pick_ring(lens, camera, step, **expect)
    if ring is None or 0 in gains:
        print(f"{lens.attr_name}: no ring")
        return False
    ring = _ring_steps(lens, camera, spot, ring, gains, iterations, max_move, tolerance_px, find)
    if ring is None or np.any(np.abs(spot - ring[:2]) > accept_px):
        _move(lens.x, start[0])
        _move(lens.y, start[1])
        print(f"{lens.attr_name}: ring did not converge, back to x {start[0]:.4f}, y {start[1]:.4f}")
        return False
    print(f"{lens.attr_name}: ring at ({ring[0]:.1f}, {ring[1]:.1f}), x {_readback(lens.x):.4f}, "
          f"y {_readback(lens.y):.4f}")
    return True


_METHODS = {"ring": _align_ring, "centroid": _align_centroid}


def align_lens(tfs, lens, camera, method="ring", write_in_set=None, **kwargs):
    """
    Align one TFS lens (e.g. tfs.tfs_06), as align_lenses does, then put the lenses that were in back,
    each at its x and y. Raises before anything moves if the lens alone would fault the interlock:
    align it with align_lenses and a lens legal alone.
    """
    removed = {other: (_readback(other.x), _readback(other.y))
               for other in tfs.tfs_lenses if other is not lens and not other.removed}
    prefocus = [p for p in tfs.xrt_lenses if p.inserted]
    align_lenses(tfs, [lens], camera, method, write_in_set, partners=False, **kwargs)
    _put_back(removed)
    for p in prefocus:
        p.insert(wait=True)
    _beam_back()


# -- a combo ------------------------------------------------------------------------------------


def align_lenses(tfs, lenses, camera, method="ring", write_in_set=None, partners=True, ask=True, **kwargs):
    """
    Align each TFS lens in `lenses` (a combo's lenses) and leave exactly them in, with the combo's
    prefocus lens, if any. `method` "ring": each lens's ring (a lens with no usable ring keeps
    its IN_SET); "centroid": the centroid.

    It prints the plan, checked against the interlock's rules at the beam energy, and stops there if
    a step would fault it. Then the prefocus lenses and every TFS lens come out, IN_DELTA goes to 1 mm,
    and each lens is aligned: on the spot with all lenses out, or, for a lens illegal alone, on the
    spot with its partner in at its aligned position. At the end it shows the aligned y against
    IN_SET and asks before writing it (`write_in_set` True or False skips the question), and the
    lenses go in together. It prints where each lens was, so a run stopped halfway can be put back
    by hand. When it can't tell a lens's ring from the other circles on DG2, it shows them and asks which
    (`ask` False: that lens keeps its IN_SET). Its frames, motor stops and printout go to a zip in ~.
    """
    with _recording():
        _align_lenses(tfs, lenses, camera, method, write_in_set, partners, ask, **kwargs)


def _align_lenses(tfs, lenses, camera, method, write_in_set, partners, ask, **kwargs):
    align = _METHODS[method]
    energy = float(tfs.beam_energy.get())
    prefocus = next((lens for lens in lenses if lens in tfs.xrt_lenses), None)
    lenses = [lens for lens in lenses if lens in tfs.tfs_lenses]
    _check_interlock(tfs)
    plan, helpers = _plan(lenses, energy, prefocus, tfs.tfs_lenses)
    if not partners and (helpers or any(partners for _, partners in plan)):
        raise RuntimeError(f"{lenses[0].attr_name} alone would fault the interlock: align it with "
                           f"align_lenses and a lens legal alone")
    _save_beam()
    for lens in tfs.tfs_lenses + tfs.xrt_lenses:
        if not lens.removed:
            print(f"before: {lens.attr_name} in at x {_readback(lens.x):.4f}, y {_readback(lens.y):.4f}"
                  if lens in tfs.tfs_lenses else f"before: {lens.attr_name} in")
    before = _in_windows(lenses + helpers, ALIGN_DELTA)
    try:
        for lens in tfs.xrt_lenses:
            if not lens.removed:
                lens.remove(wait=True)
        _together(_remove, [lens for lens in tfs.tfs_lenses if not lens.removed])
        reference = _fresh_image(camera, SPOT_FRAMES, timeout=SPOT_FRAMES)  # all lenses out
        _check_bright(reference)
        spot = _centroid(reference)
        print(f"all lenses out; spot ({spot[0]:.1f}, {spot[1]:.1f}) from {SPOT_FRAMES} frames, for every lens")
        aligned = {}
        for lens, partners in plan:
            expect = dict(reference=reference, targets={lens: spot}, lenses=[lens], energy=energy, ask=ask)
            options = {}
            if partners:
                _together(lambda partner: _put_back({partner: aligned[partner]}), list(partners))
                # where each partner's ring is without the lens: they were just aligned on the spot
                image, targets = _fresh_image(camera, SPOT_FRAMES // 5), {}
                for partner in partners:
                    radius, _ = _expected_ring(partner, partner, list(partners), energy)
                    ring = _find_ring(image, reference, (0.9 * radius, 1.1 * radius), spot, within=0.5 * radius)
                    if ring is not None:
                        targets[partner] = ring[:2]
                        print(f"{partner.attr_name}'s ring at ({ring[0]:.1f}, {ring[1]:.1f}) without {lens.attr_name}")
                if not targets:  # not aligned: its x as it is and its old IN_SET
                    print(f"{lens.attr_name}: no partner ring to align on")
                    aligned[lens] = _readback(lens.x), before[lens][0]
                    _together(_remove, list(partners))
                    continue
                # the lens shrinks a partner's ring and moves it about L/f as much as the lens, so a
                # bigger step and a tighter tolerance than a ring of its own
                expect.update(targets=targets, lenses=[*partners, lens])
                if method == "ring":
                    options = dict(step=0.2, tolerance_px=0.5, accept_px=1.5)
            _insert(lens)
            ok = align(lens, camera, spot, expect=expect, **{**options, **kwargs}) is not False
            aligned[lens] = _readback(lens.x), _readback(lens.y) if ok else before[lens][0]  # not aligned: old IN_SET
            _remove(lens)
            _together(_remove, list(partners))
        for helper in helpers:
            x, y = aligned.pop(helper)
            print(f"{helper.attr_name} (a helper) aligned at x {x:.4f}, y {y:.4f}; its IN_SET left at {before[helper][0]:.4f}")
        _finish(aligned, before, write_in_set)
        if prefocus is not None:
            prefocus.insert(wait=True)
            print(f"in: {prefocus.attr_name}")
    finally:
        _restore_windows(before)
    _beam_back()
