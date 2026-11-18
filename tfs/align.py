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

Ring method: the edge of a lens's aperture casts a thin dark ring on DG2. The
ring moves with the lens, much more than the centroid does (tfs_06 x: about
190 px/mm against 4 px/mm). Move the lens until the ring is centered on the
spot. A lens with no ring (a beam narrower than its aperture), or whose ring does
not converge, goes back to where it was and its IN_SET is left as it is: the centroid moves
about 4 px per mm of lens against 10 px of frame-to-frame jitter at the hutch, too little to
align on.
The ring is found in the image divided by one with all lenses out, which leaves only what the
lens changed, as the circle through the most thin dark pixels (RANSAC): the lens body's texture
and the holder's edge don't pull it. The spot is measured once, from many frames (the centroid
jumps 10 px from frame to frame), and every lens is centred on it.

A lens illegal alone is aligned with a partner in: its own edge doesn't show behind the
partner's, but it focuses the light through the partner's aperture, which shrinks the partner's
ring and moves it with the lens (about L/f of the lens's offset). It is moved until the
partner's shrunk ring is centred where the partner's ring is without it.

Both assume camera x/y are along motor x/y.

The lens interlock faults when a lens is neither In nor Out, which includes every y move, and when
the lenses in are an illegal configuration at the beam energy; while faulted it puts attenuator
blade 11 in. Lenses are aligned with the prefocus lenses out. Before anything moves, align_lenses
checks each configuration it will use against the interlock's rules and prints the plan: a lens
that is illegal alone is aligned with a lens that is legal alone already in at its aligned
position. Before each image the code waits for the interlock to clear and puts the transmission
and pulse picker back. A lens reads In only within IN_DELTA of IN_SET, so IN_DELTA is 1 mm while
aligning; at the end it asks before writing the aligned y to IN_SET.
"""
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from epics import caget, caput
from scipy import ndimage

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


def _ring_pixels(image, line_width=9, contrast=0.3):
    """
    The pixels of thin dark rings in the beam: filling dark lines thinner than `line_width` (a grey
    closing) and subtracting the image leaves them.
    """
    smooth = ndimage.gaussian_filter(image.astype(float), 1.0)
    filled = ndimage.grey_closing(smooth, size=line_width)
    return (filled > 0.1 * filled.max()) & (filled - smooth > contrast * filled)


def _circle(cols, rows):
    """Least-squares circle (col, row, radius) through points: x^2 + y^2 + D x + E y + F = 0."""
    A = np.column_stack([cols, rows, np.ones_like(cols)])
    (D, E, F), *_ = np.linalg.lstsq(A, -(cols ** 2 + rows ** 2), rcond=None)
    col, row = -D / 2, -E / 2
    return np.array([col, row, np.sqrt(max(col ** 2 + row ** 2 - F, 0.0))])


def _find_ring(image, reference, centre=None, radii=(15, 300), tolerance_px=2.0, tries=400, min_pixels=100,
               min_arc=0.25):
    """
    A lens aperture's ring in image / reference, as (col, row, radius) px, or None: the circle through
    the most thin dark pixels within `tolerance_px` (RANSAC), refined by least squares on them, with a
    radius in `radii` and, given a `centre` (col, row), within 80 px of it. It needs `min_pixels` of
    them, spread over at least `min_arc` of the circle.
    """
    image = ndimage.gaussian_filter(image.astype(float), 1)
    reference = ndimage.gaussian_filter(reference.astype(float), 1)
    lit = reference > 0.2 * reference.max()  # the ratio is noise where the reference is dark
    ratio = np.where(lit, image / np.maximum(reference, 1e-9), 0.0)
    rows, cols = np.nonzero(_ring_pixels(ratio) & ndimage.binary_erosion(lit, iterations=4))
    if len(rows) < min_pixels:
        return None
    cols, rows = cols.astype(float), rows.astype(float)
    rng, best = np.random.default_rng(0), None
    for _ in range(tries):
        pick = rng.choice(len(cols), 3, replace=False)
        circle = _circle(cols[pick], rows[pick])
        if not radii[0] < circle[2] < radii[1] or (centre is not None and np.hypot(*(circle[:2] - centre)) > 80):
            continue
        on = np.abs(np.hypot(cols - circle[0], rows - circle[1]) - circle[2]) < tolerance_px
        if best is None or on.sum() > best.sum():
            best = on
    if best is None or best.sum() < min_pixels:
        return None
    for _ in range(2):  # refit on the pixels near the circle
        circle = _circle(cols[best], rows[best])
        best = np.abs(np.hypot(cols - circle[0], rows - circle[1]) - circle[2]) < tolerance_px
    angles = np.arctan2(rows[best] - circle[1], cols[best] - circle[0])
    arc = len(np.unique(np.floor((angles + np.pi) / (2 * np.pi) * 36))) / 36
    if best.sum() < min_pixels or arc < min_arc or not radii[0] < circle[2] < radii[1]:
        return None
    return circle


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
    return np.mean(frames, axis=0)


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


def _plan(lenses, energy, prefocus=None):
    """
    [(lens, partner)]: the lenses legal alone first, each aligned alone (partner None), then each of the
    others with a lens legal alone in (partner). Prints it. Raises before anything moves if a step
    would fault the interlock, or the lenses with `prefocus` at the end would.
    """
    if _trips([], energy):
        raise RuntimeError(f"all lenses out would fault the interlock: {_trips([], energy)}")
    alone = [lens for lens in lenses if not _trips([lens], energy)]
    plan = [(lens, None) for lens in alone]
    for lens in lenses:
        if lens not in alone:
            partner = next((p for p in alone if not _trips([p, lens], energy)), None)
            if partner is None:
                raise RuntimeError(f"{lens.attr_name} alone would fault the interlock "
                                   f"({_trips([lens], energy)}), and so would it with each lens legal alone")
            plan.append((lens, partner))
    end = _trips(lenses, energy, prefocus)
    if end:
        raise RuntimeError(f"the lenses in together would fault the interlock: {end}")
    low, high = _trip_range(None, energy) or (0, 0)
    print(f"plan at {energy:.0f} eV, no prefocus lens, trip range {low:.1f}-{high:.1f} um:")
    for lens, partner in plan:
        with_ = f"with {partner.attr_name} in ({_radius([lens, partner]):.1f} um)" if partner else \
            f"alone ({_radius([lens]):.0f} um)"
        print(f"  {lens.attr_name} {with_}")
    if prefocus is not None:
        print(f"  then {prefocus.attr_name} in with them")
    return plan


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


def _align_centroid(lens, camera, spot, step=0.02, iterations=3, max_move=0.2, find=None):
    """Move `lens` until the centroid is on `spot`, with only that lens in. Distances in mm."""
    _centroid_steps(lens.x, 0, camera, spot, step, iterations, max_move)
    _centroid_steps(lens.y, 1, camera, spot, step, iterations, max_move)
    print(f"{lens.attr_name}: x {_readback(lens.x):.4f}, y {_readback(lens.y):.4f}")


# -- ring method --------------------------------------------------------------------------------


def _ring_gains(lens, camera, step=0.05, max_resize_px=4.0, find=None):
    """
    The ring (col, row, radius), and how many px it moves per mm of x and of y,
    from a `step` mm move of each (moved back after). (None, None) if there is
    no ring. A gain is None if the ring is lost after its step, or if its radius
    changed by more than `max_resize_px`: a lens's ring is the shadow of its
    aperture and keeps its size, while a circle fitted to something else (the
    corners of a beam narrower than the aperture) does not.
    """
    ring = find(_fresh_image(camera))
    if ring is None:
        return None, None
    gains = []
    for axis, motor in enumerate([lens.x, lens.y]):
        start = _readback(motor)
        moved = _step_by(motor, step)
        shifted = find(_fresh_image(camera))
        _move(motor, start)
        same = shifted is not None and abs(shifted[2] - ring[2]) <= max_resize_px
        gains.append((shifted[axis] - ring[axis]) / moved if same else None)
    return ring, gains


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
                find=None):
    """
    Move `lens` until its ring is centered on `spot`, with only that lens in. Distances in mm. Returns True
    if the ring ends within `accept_px` of the spot. Otherwise (no ring, or one that does not
    converge) the lens goes back to where it started and it returns False.
    """
    start = _readback(lens.x), _readback(lens.y)
    ring, gains = _ring_gains(lens, camera, step, find=find)
    if ring is None or None in gains or 0 in gains:
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


def align_lenses(tfs, lenses, camera, method="ring", write_in_set=None, partners=True, **kwargs):
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
    by hand.
    """
    align = _METHODS[method]
    energy = float(tfs.beam_energy.get())
    prefocus = next((lens for lens in lenses if lens in tfs.xrt_lenses), None)
    lenses = [lens for lens in lenses if lens in tfs.tfs_lenses]
    _check_interlock(tfs)
    plan = _plan(lenses, energy, prefocus)
    if not partners and any(partner for _, partner in plan):
        raise RuntimeError(f"{lenses[0].attr_name} alone would fault the interlock: align it with "
                           f"align_lenses and a lens legal alone")
    _save_beam()
    for lens in tfs.tfs_lenses + tfs.xrt_lenses:
        if not lens.removed:
            print(f"before: {lens.attr_name} in at x {_readback(lens.x):.4f}, y {_readback(lens.y):.4f}"
                  if lens in tfs.tfs_lenses else f"before: {lens.attr_name} in")
    before = _in_windows(lenses, ALIGN_DELTA)
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
        for lens, partner in plan:
            find, target, options = (lambda image: _find_ring(image, reference)), spot, {}
            if partner is not None:
                _put_back({partner: aligned[partner]})
                ring = _find_ring(_fresh_image(camera, SPOT_FRAMES // 5), reference)
                if ring is None:  # not aligned: its x as it is and its old IN_SET
                    print(f"{lens.attr_name}: no {partner.attr_name} ring to align on")
                    aligned[lens] = _readback(lens.x), before[lens][0]
                    _remove(partner)
                    continue
                print(f"{partner.attr_name} in for {lens.attr_name}; its ring at ({ring[0]:.1f}, {ring[1]:.1f})")
                # the lens shrinks the partner's ring and moves it about L/f as much as the lens, so a
                # bigger step and a tighter tolerance than a ring of its own
                def find(image, ring=ring):
                    return _find_ring(image, reference, ring[:2], (0.4 * ring[2], 1.02 * ring[2]))
                target = ring[:2]
                if method == "ring":
                    options = dict(step=0.2, tolerance_px=0.5, accept_px=1.5)
            _insert(lens)
            ok = align(lens, camera, target, find=find, **{**options, **kwargs}) is not False
            aligned[lens] = _readback(lens.x), _readback(lens.y) if ok else before[lens][0]  # not aligned: old IN_SET
            _remove(lens)
            if partner is not None:
                _remove(partner)
        _finish(aligned, before, write_in_set)
        if prefocus is not None:
            prefocus.insert(wait=True)
            print(f"in: {prefocus.attr_name}")
    finally:
        _restore_windows(before)
    _beam_back()
