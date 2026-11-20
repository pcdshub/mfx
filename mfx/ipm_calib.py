"""
IPM diode position-calibration scans for MFX DG1 and DG2.

Moves the IPM diode stage (x and/or y) a few mm either side of its
current position while recording with the DAQ, one run per axis. Each
step is a DAQ calib cycle with the motor position stored, so offline you
can fit the wave8 XPOS/YPOS against the known diode displacement to get
the scale (and offset) needed to turn the feature-extracted positions
into real-space beam positions.
"""

import logging
from time import sleep
from typing import Iterable, List, Union

import numpy as np

logger = logging.getLogger(__name__)

_IPMS = {
    'dg1': 'mfx_dg1_ipm',
    'dg2': 'mfx_dg2_ipm',
}


def _get_ipm(name: str):
    """Return the happi IPM device for 'dg1' or 'dg2'."""
    import mfx.db as db

    key = name.lower()
    if key not in _IPMS:
        raise ValueError(f"ipm must be one of {list(_IPMS)} (got {name!r})")
    return getattr(db, _IPMS[key])


def _positions(center: float, span: float, steps: int,
               back_and_forth: bool) -> List[float]:
    """center-span -> center+span (-> back to center-span if requested)."""
    pts = list(center + np.linspace(-span, span, steps))
    if back_and_forth:
        pts += pts[-2::-1]
    return [float(p) for p in pts]


def ipm_diode_scan(
        ipm: Union[str, Iterable[str]] = 'both',
        axes: str = 'xy',
        span: float = 2.0,
        steps: int = 9,
        events_per_step: int = 120,
        back_and_forth: bool = False,
        record: bool = False,
        picker: str = None,
        insert: bool = True,
        sample: str = 'ipm_calib',
        tag: str = None,
        post_elog: bool = True,
        daq_delay: float = 2.0):
    """
    Scan the DG1/DG2 IPM diodes in x and y while recording with the DAQ.

    For every requested IPM and axis this takes one DAQ run that steps the
    diode motor from ``current - span`` to ``current + span`` in ``steps``
    points (optionally coming back again), then returns the motor to where
    it started -- also on Ctrl-C or error.

    Parameters
    ----------
    ipm : str or iterable of str, optional
        'dg1', 'dg2', 'both' (default), or e.g. ['dg2'].
    axes : str, optional
        Which diode axes to scan: 'x', 'y' or 'xy' (default).
    span : float, optional
        Half-range in mm about the current position (default: 2.0).
    steps : int, optional
        Points from -span to +span (default: 9, i.e. 0.5 mm steps at 2 mm).
    events_per_step : int, optional
        Events per calib cycle (default: 120).
    back_and_forth : bool, optional
        If True, also scan back from +span to -span in the same run
        (useful for checking backlash). Default False.
    record : bool, optional
        Record the runs (default: False -- set True for real calibration).
    picker : str or None, optional
        'open' or 'flip' to set the pulse picker first; it is closed at the
        end only if this function opened it. None leaves it alone.
    insert : bool, optional
        Insert the diode first if it is not already in (default: True).
    sample, tag : str, optional
        Names used for the elog post.
    post_elog : bool, optional
        Post a note per run to the elog when recording (default: True).
    daq_delay : float, optional
        Seconds to wait between runs (default: 2).

    Returns
    -------
    list of dict
        One entry per run: ipm, axis, motor name, run number, center and
        the list of positions scanned.

    Examples
    --------
    Dry run (no recording) of both IPMs, both axes, +/-2 mm:

    >>> ipm_diode_scan()

    Record a DG2-only calibration, +/-3 mm in 13 steps, 240 shots/step:

    >>> ipm_diode_scan('dg2', span=3, steps=13, events_per_step=240,
    ...                record=True)

    Only x on DG1, out and back:

    >>> ipm_diode_scan('dg1', axes='x', back_and_forth=True, record=True)
    """
    import bluesky.plans as bp
    from mfx.db import RE, daq, mfx_pulsepicker
    from mfx.macros import get_run

    if isinstance(ipm, str):
        names = list(_IPMS) if ipm.lower() == 'both' else [ipm]
    else:
        names = list(ipm)

    axes = axes.lower()
    if not axes or any(a not in 'xy' for a in axes):
        raise ValueError("axes must be 'x', 'y' or 'xy'")
    if steps < 2:
        raise ValueError("steps must be >= 2")

    if tag is None:
        tag = sample

    devs = {name.lower(): _get_ipm(name) for name in names}

    # The y scan is about the diode's IN position, so insert first.
    for name, dev in devs.items():
        if insert and not dev.diode.inserted:
            logger.info(f"Inserting {name} diode")
            dev.diode.insert(wait=True, timeout=30)
        try:
            tgt = dev.target.position
        except Exception:
            tgt = '?'
        logger.info(f"{name}: diode inserted={dev.diode.inserted}, "
                    f"target={tgt}")
    # Build the plan and check every point against the soft limits before
    # any scan motion.
    jobs = []
    for name, dev in devs.items():
        for axis in axes:
            motor = getattr(dev.diode, f"{axis}_motor")
            center = motor.position
            pts = _positions(center, span, steps, back_and_forth)
            for p in (min(pts), max(pts)):
                motor.check_value(p)
            jobs.append(dict(ipm=name, axis=axis, motor=motor,
                             center=center, positions=pts))

    opened_picker = False
    if picker == 'open':
        mfx_pulsepicker.open()
        opened_picker = True
    elif picker == 'flip':
        mfx_pulsepicker.flipflop()
        opened_picker = True

    results = []
    try:
        for i, job in enumerate(jobs):
            motor, pts = job['motor'], job['positions']
            run_number = get_run(station=0) + 1
            logger.warning(
                f"[{i + 1}/{len(jobs)}] run {run_number}: {job['ipm']} diode "
                f"{job['axis']} ({motor.name}) {pts[0]:.3f} -> {max(pts):.3f}"
                f" mm, {len(pts)} steps x {events_per_step} events "
                f"(center {job['center']:.3f})")
            try:
                daq.configure(motors=[motor], group_mask=0x1,
                              events=events_per_step, record=record)
                RE(bp.list_scan([daq], motor, pts))
            finally:
                logger.info(f"Returning {motor.name} to {job['center']:.3f}")
                motor.move(job['center'], wait=True, timeout=60)

            results.append(dict(ipm=job['ipm'], axis=job['axis'],
                                motor=motor.name, run=run_number,
                                center=job['center'], positions=pts))

            if record and post_elog:
                from mfx.autorun import post
                post(sample=f"{sample}_{job['ipm']}_{job['axis']}", tag=tag,
                     run_number=run_number, post=True, daq_num=2,
                     add_note=(f"IPM diode calib: {job['ipm']} "
                               f"{job['axis']} ({motor.name}) center "
                               f"{job['center']:.3f} mm, +/-{span} mm, "
                               f"{len(pts)} steps @ {events_per_step} "
                               f"events/step"))

            if i < len(jobs) - 1:
                sleep(daq_delay)

    except KeyboardInterrupt:
        logger.warning("IPM diode scan interrupted; motors restored")
    finally:
        if opened_picker:
            mfx_pulsepicker.close()
        daq.control.setState("configured")
        while daq.control.getState() != "configured":
            sleep(0.01)
        daq.control.setRecord(False)
        daq.control.setState("running")

    for r in results:
        logger.warning(f"  run {r['run']}: {r['ipm']} {r['axis']} "
                       f"center {r['center']:.3f} mm")
    return results
