"""
Align TFS lenses on the beam, one lens at a time, with a downstream YAG (DG2).

    from tfs.align import *
    cam = gigE_camera_accessor("MFX:GIGE:DG2:YAG")

    align_lens(tfs, tfs.tfs_06, cam)            # one lens

    combo = tfs.find_best_combo()
    align_lenses(tfs, combo.lenses, cam)        # a combo; its prefocus lens, if any, goes in first

Both print what they do, lens by lens. method="centroid" uses the centroid method
for every lens.

Centroid method: an off-center lens bends the beam like a prism, so the beam
centroid on DG2 moves with the lens. Move the lens until the centroid is back on
the spot it hits without the lens.

Ring method: the edge of a lens's aperture casts a thin dark ring on DG2. The
ring moves with the lens, much more than the centroid does (tfs_06 x: about
190 px/mm against 4 px/mm). Move the lens until the ring is centered on the
spot. A lens with no ring (a beam narrower than its aperture), or whose ring does
not converge, goes back to where it was and is aligned with the centroid method.

Both assume camera x/y are along motor x/y.

The lens interlock: a TFS lens reads In only when its y is stopped and within
IN_DELTA of IN_SET, and the interlock puts attenuator blade 11 in whenever a lens
is neither In nor Out, which includes every y move. So before each image the
code waits for the interlock to clear and, if blade 11 is in, re-applies the
attenuator's transmission, as lens_minder does. While a lens is being aligned,
its IN_DELTA is 1 mm; then its IN_SET becomes the aligned y and IN_DELTA goes
back. Each change is printed.
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


# -- image analysis -----------------------------------------------------------------------------


def _centroid(image, threshold=0.1):
    """Beam centroid (col, row) in pixels, background subtracted."""
    image = image - np.median(image)
    image[image < threshold * image.max()] = 0
    if not image.sum() > 0:
        raise RuntimeError("no beam on the camera: check the beam, the pulse picker, the YAG and the attenuator")
    rows, cols = np.indices(image.shape)
    return np.array([(cols * image).sum(), (rows * image).sum()]) / image.sum()


def _find_ring(image, line_width=9, contrast=0.3, min_pixels=40):
    """
    The thin dark ring in the beam, as (col, row, radius) in pixels, or None.
    Filling dark lines thinner than `line_width` (a grey closing) and subtracting
    the image leaves the ring; a circle is fitted to its pixels.
    """
    smooth = ndimage.gaussian_filter(image.astype(float), 1.0)
    filled = ndimage.grey_closing(smooth, size=line_width)
    in_beam = filled > 0.1 * filled.max()
    ring = in_beam & (filled - smooth > contrast * filled)
    rows, cols = np.nonzero(ring)
    if len(rows) < min_pixels:
        return None
    # circle x^2 + y^2 + D x + E y + F = 0, least squares
    A = np.column_stack([cols, rows, np.ones_like(cols)])
    b = -(cols.astype(float) ** 2 + rows.astype(float) ** 2)
    (D, E, F), *_ = np.linalg.lstsq(A, b, rcond=None)
    col, row = -D / 2, -E / 2
    return np.array([col, row, np.sqrt(max(col ** 2 + row ** 2 - F, 0))])


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


def _beam_back():
    """
    Wait for the lens interlock to clear, then take blade 11 out if it is in, by re-applying the
    attenuator's transmission (MFX:ATT:COM:R_DES), as lens_minder does after a lens move.
    """
    from mfx.db import mfx_attenuator as att

    _wait_for(INTERLOCK + ":FAULTED", 0)
    deadline = time.monotonic() + 30.0
    while att.done.get() != att.done_value:  # COM:STATUS: the interlock may still be putting blade 11 in
        if time.monotonic() > deadline:
            raise TimeoutError("attenuator still moving after 30 s")
        time.sleep(0.05)
    if caget(BLADE + ":STATE", as_string=True) == "IN":
        att.mv(caget(att.prefix + ":COM:R_DES"), wait=True)
        while caget(BLADE + ":STATE", as_string=True) != "OUT":
            if time.monotonic() > deadline:
                raise TimeoutError(f"{BLADE} not OUT after 30 s")
            time.sleep(0.05)


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


def _remove_others(tfs, lens):
    """Remove every other TFS lens that is in. Returns {lens: (x, y)}, for _put_back."""
    removed = {other: (_readback(other.x), _readback(other.y))
               for other in tfs.tfs_lenses if other is not lens and not other.removed}
    for other in removed:
        _remove(other)
    return removed


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


def _align_in_window(align, lens, camera, spot, **kwargs):
    """
    align(lens, ...) with the lens's IN_DELTA at ALIGN_DELTA, so it reads In wherever it ends up;
    then IN_SET becomes the aligned y and IN_DELTA goes back to what it was.
    """
    record = _in_record(lens)
    in_set, in_delta = caget(record + ":IN_SET"), caget(record + ":IN_DELTA")
    caput(record + ":IN_DELTA", max(in_delta, ALIGN_DELTA), wait=True)
    try:
        align(lens, camera, spot, **kwargs)
        y = round(_readback(lens.y), 4)
        caput(record + ":IN_SET", y, wait=True)
        print(f"{lens.name}: IN_SET {in_set:.4f} -> {y:.4f}")
    finally:
        caput(record + ":IN_DELTA", in_delta, wait=True)


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


def _align_centroid(lens, camera, spot, step=0.02, iterations=3, max_move=0.2):
    """Move `lens` until the centroid is on `spot`, with only that lens in. Distances in mm."""
    _centroid_steps(lens.x, 0, camera, spot, step, iterations, max_move)
    _centroid_steps(lens.y, 1, camera, spot, step, iterations, max_move)
    print(f"{lens.name}: x {_readback(lens.x):.4f}, y {_readback(lens.y):.4f}")


# -- ring method --------------------------------------------------------------------------------


def _ring_gains(lens, camera, step=0.05, max_resize_px=4.0):
    """
    The ring (col, row, radius), and how many px it moves per mm of x and of y,
    from a `step` mm move of each (moved back after). (None, None) if there is
    no ring. A gain is None if the ring is lost after its step, or if its radius
    changed by more than `max_resize_px`: a lens's ring is the shadow of its
    aperture and keeps its size, while a circle fitted to something else (the
    corners of a beam narrower than the aperture) does not.
    """
    ring = _find_ring(_fresh_image(camera))
    if ring is None:
        return None, None
    gains = []
    for axis, motor in enumerate([lens.x, lens.y]):
        start = _readback(motor)
        moved = _step_by(motor, step)
        shifted = _find_ring(_fresh_image(camera))
        _move(motor, start)
        same = shifted is not None and abs(shifted[2] - ring[2]) <= max_resize_px
        gains.append((shifted[axis] - ring[axis]) / moved if same else None)
    return ring, gains


def _ring_steps(lens, camera, spot, ring, gains, iterations=6, max_move=0.2, tolerance_px=1.0):
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
        ring = _find_ring(_fresh_image(camera))
    return ring


def _align_ring(lens, camera, spot, step=0.05, iterations=6, max_move=0.2, tolerance_px=1.0, accept_px=3.0):
    """
    Move `lens` until its ring is centered on `spot`, with only that lens in. Distances in mm. Returns True
    if the ring ends within `accept_px` of the spot. Otherwise (no ring, or one that does not
    converge) the lens goes back to where it started and it returns False.
    """
    start = _readback(lens.x), _readback(lens.y)
    ring, gains = _ring_gains(lens, camera, step)
    if ring is None or None in gains or 0 in gains:
        print(f"{lens.name}: no ring")
        return False
    ring = _ring_steps(lens, camera, spot, ring, gains, iterations, max_move, tolerance_px)
    if ring is None or np.any(np.abs(spot - ring[:2]) > accept_px):
        _move(lens.x, start[0])
        _move(lens.y, start[1])
        print(f"{lens.name}: ring did not converge, back to x {start[0]:.4f}, y {start[1]:.4f}")
        return False
    print(f"{lens.name}: ring at ({ring[0]:.1f}, {ring[1]:.1f}), spot ({spot[0]:.1f}, {spot[1]:.1f}), "
          f"x {_readback(lens.x):.4f}, y {_readback(lens.y):.4f}")
    return True


def _align_ring_or_centroid(lens, camera, spot, **kwargs):
    """Align `lens` with its ring, or with the centroid if it has no usable ring."""
    if not _align_ring(lens, camera, spot, **kwargs):
        print(f"{lens.name}: centroid method instead")
        _align_centroid(lens, camera, spot)


_METHODS = {"ring": _align_ring_or_centroid, "centroid": _align_centroid}


def align_lens(tfs, lens, camera, method="ring", **kwargs):
    """
    Align one TFS lens (e.g. tfs.tfs_06), the other lenses out meanwhile and back after, each at
    its x and y; its IN_SET becomes the aligned y. `method` "ring": its ring, or the centroid if it
    has no usable ring; "centroid": the centroid.
    """
    _check_interlock(tfs)
    removed = _remove_others(tfs, lens)
    _remove(lens)
    spot = _centroid(_fresh_image(camera))
    _insert(lens)
    _align_in_window(_METHODS[method], lens, camera, spot, **kwargs)
    _put_back(removed)
    _beam_back()


# -- a combo ------------------------------------------------------------------------------------


def align_lenses(tfs, lenses, camera, method="ring", **kwargs):
    """
    Align each TFS lens in `lenses` (a combo's lenses: its prefocus lens, if any, goes in first and
    stays in) and leave exactly them in, each at its aligned x and y, which becomes its IN_SET.
    `method` as for align_lens.
    Every TFS lens comes out first. Then, one at a time, the spot is measured with all lenses out,
    the lens goes in, is aligned and comes out again. At the end they all go in together. This
    takes fewer ladder moves than calling align_lens for each lens. It prints where each lens was
    and where each is aligned, so a run stopped halfway can be put back by hand.
    """
    align = _METHODS[method]
    _check_interlock(tfs)
    for lens in lenses:
        if lens in tfs.xrt_lenses and not lens.inserted:
            lens.insert(wait=True)
    lenses = [lens for lens in lenses if lens in tfs.tfs_lenses]
    for lens in tfs.tfs_lenses:
        if not lens.removed:
            print(f"before: {lens.name} in at x {_readback(lens.x):.4f}, y {_readback(lens.y):.4f}")
    _together(_remove, [lens for lens in tfs.tfs_lenses if not lens.removed])
    aligned = {}
    for lens in lenses:
        spot = _centroid(_fresh_image(camera))
        _insert(lens)
        _align_in_window(align, lens, camera, spot, **kwargs)
        aligned[lens] = _readback(lens.x), _readback(lens.y)
        print(f"aligned: {lens.name} at x {aligned[lens][0]:.4f}, y {aligned[lens][1]:.4f}")
        _remove(lens)
    _together(lambda lens: _put_back({lens: aligned[lens]}), list(aligned))
    _beam_back()
