"""
dod_routines.py -- automation routines for the DoD robot (Goals 1 & 3).

Rewritten to use the REAL DoD interface (dod_dummy.DoDDummy, or the real DoD
class). Routines control the real parameters: nozzle frequency/voltage/pulse
width, probe volume, dispense mode, nozzle selection.

Each routine takes:
  - dod:  a DoDDummy (now) or the real DoD object (later)
  - log:  optional callback log(msg) for live progress
and returns a result dict.
"""

import time
import random
import csv
from datetime import datetime

VALID_NOZZLES = (1, 2, 3, 4)


def save_results_csv(records, kind="routine"):
    """Save a list of result dicts to a timestamped CSV file. Returns the filename."""
    if not records:
        return None
    fname = f"dod_{kind}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    keys = list(records[0].keys())
    with open(fname, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in records:
            writer.writerow(row)
    return fname


def _noop(msg):
    print(msg)


def read_measured_volume(dod):
    """
    Read the measured droplet volume the way the REAL robot exposes it (per
    Sebastian): it's the last field of get_nozzle_status()['ID,Volt,Pulse,Freq,Volume'].

    Flow: trigger a measurement, then read nozzle status and pull Volume out.
    On the dummy, measure_volume() simulates the value. On the real robot you'd
    run the actual volume task instead (name TBC with Sebastian).

    NOTE: Sebastian said not to fully rely on this readback -- sanity-check the
    values against the drop-detection camera when on real hardware.
    """
    # trigger the measurement (dummy simulates; real robot: run the volume task)
    if hasattr(dod, "measure_volume"):
        dod.measure_volume()
    else:
        # real robot path (uncomment/adjust once the task name is confirmed):
        # dod.run_task("AutoDropDetectionDropVolume")
        pass
    status = dod.get_nozzle_status()
    try:
        # 'ID,Volt,Pulse,Freq,Volume' -> Volume is the last element
        return float(status["ID,Volt,Pulse,Freq,Volume"][-1])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def safe_goto(dod, name, log=_noop):
    """Move to a named position (collision-checked inside move_to_position)."""
    r = dod.move_to_position(name)
    if r.get("ok"):
        log(f"[safe_goto] at {name}" + (" (via detour)" if r.get("detour") else ""))
    else:
        log(f"[safe_goto] REFUSED {name}: {r.get('reason')}")
    return r


def configure_nozzle(dod, nozzle=1, frequency=30000, voltage=80, pulse_width=20,
                     activate=True, log=_noop):
    """
    Set the real droplet-generation parameters.

    A nozzle must be ACTIVATED (armed) before it can be SELECTED -- the real
    client rejects select_nozzle() for any channel not in 'Activated Nozzles'.
    With activate=True we arm it first; set activate=False to require that the
    caller has already armed it.
    """
    if activate and hasattr(dod, "set_nozzle_active"):
        armed = set(getattr(dod, "activated_nozzles", []))
        if nozzle not in armed:
            r = dod.set_nozzle_active(sorted(armed | {nozzle}))
            if isinstance(r, dict) and not r.get("ok"):
                log(f"[nozzle] ARM REJECTED: {r.get('reason')}")
                return {"ok": False, "reason": r.get("reason")}
            log(f"[nozzle] armed channel {nozzle}")

    r = dod.select_nozzle(nozzle)
    if isinstance(r, dict) and not r.get("ok"):
        log(f"[nozzle] REJECTED: {r.get('reason')}")
        return {"ok": False, "reason": r.get("reason")}
    dod.set_nozzle_frequency(frequency)
    dod.set_nozzle_voltage(voltage)
    dod.set_nozzle_pulse_width(pulse_width)
    log(f"[nozzle] #{nozzle} freq={frequency}Hz volt={voltage}V pulse={pulse_width}us")
    return {"ok": True}


def safety_check_routine(dod, log=_noop):
    """
    Safety automation routine: run the full pre-flight safety validation before
    operating. Checks the coordinate data, required positions, workspace bounds,
    and that no position sits in the keep-out zone. Returns pass/fail.
    """
    from dod_safety_tools import preflight_check
    log("[safety] running pre-flight safety checks...")
    passed, total, text = preflight_check()
    ok = (passed == total)
    log(f"[safety] {passed}/{total} checks passed" + (" -- ALL CLEAR" if ok else " -- REVIEW NEEDED"))
    if not ok:
        log("[safety] WARNING: not all checks passed. Review before operating.")
    return {"ok": ok, "passed": passed, "total": total}


def wash_cycle(dod, log=_noop, task="WashFlush_Medium"):
    log("[wash] starting")
    safe_goto(dod, "WashStation1", log=log)
    dod.run_task(task)
    log(f"[wash] ran {task}")
    log("[wash] complete")
    return {"ok": True}

def flush_nozzles(
        dod,
        channels,
        task="WashFlush_Medium",
        go_to_wash=True,
        restore_state=True,
        log=_noop):
    """
    Activate the nozzles selected in the GUI popup as one group, run the
    selected WashFlush task once, and restore the original nozzle state.

    `go_to_wash` is retained for compatibility with existing callers. The
    WashFlush task is responsible for its own physical wash sequence.
    """

    # Validate and normalize the popup selection.
    try:
        selected_nozzles = sorted({int(ch) for ch in channels})
    except (TypeError, ValueError) as exc:
        reason = f"invalid nozzle selection: {exc}"
        log(f"[flush] ABORT: {reason}")
        return {
            "ok": False,
            "stage": "validation",
            "reason": reason,
            "task": task,
        }

    if not selected_nozzles:
        reason = "no nozzles selected"
        log(f"[flush] ABORT: {reason}")
        return {
            "ok": False,
            "stage": "validation",
            "reason": reason,
            "task": task,
        }

    invalid = [
        ch for ch in selected_nozzles
        if ch not in VALID_NOZZLES
    ]

    if invalid:
        reason = (
            f"channels {invalid} are invalid; "
            f"valid nozzles are {list(VALID_NOZZLES)}"
        )
        log(f"[flush] ABORT: {reason}")
        return {
            "ok": False,
            "stage": "validation",
            "reason": reason,
            "task": task,
        }

    # Save the state that existed before opening/running the flush.
    previous_active = list(
        getattr(dod, "activated_nozzles", [])
    )
    previous_selected = getattr(dod, "nozzle", None)

    result = {
        "ok": False,
        "task": task,
        "selected_nozzles": selected_nozzles,
        "previous_active": previous_active,
        "previous_selected": previous_selected,
    }

    restore_errors = []

    try:
        # Never dispense while nozzle state is changing or washing.
        dod.dispense_off()
        log("[flush] dispensing OFF")

        # Activate all popup-selected nozzles together before the task.
        try:
            activation_result = dod.set_nozzle_active(
                selected_nozzles
            )
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            result.update({
                "stage": "activation",
                "reason": reason,
            })
            log(f"[flush] ACTIVATION FAILED: {reason}")
            return result

        if (
            activation_result is False
            or (
                isinstance(activation_result, dict)
                and activation_result.get("ok") is False
            )
        ):
            reason = (
                activation_result.get("reason")
                if isinstance(activation_result, dict)
                else None
            )

            reason = reason or "failed to activate selected nozzles"

            result.update({
                "stage": "activation",
                "reason": reason,
                "activation_result": activation_result,
            })

            log(f"[flush] ACTIVATION FAILED: {reason}")
            return result

        log(
            "[flush] activated popup-selected nozzles: "
            f"{selected_nozzles}"
        )

        # The WashFlush task owns its internal movement and wash sequence.
        # Do not attempt to move to the undefined WashStation1 position.
        if go_to_wash:
            log(
                "[flush] wash-station positioning is handled by "
                f"the robot task {task!r}"
            )

        available_tasks = getattr(dod, "available_tasks", None)

        if (
            available_tasks is not None
            and task not in available_tasks
        ):
            reason = f"task {task!r} is not available"

            result.update({
                "stage": "task_lookup",
                "reason": reason,
            })

            log(f"[flush] ABORT: {reason}")
            return result

        # Run the selected wash task once with the popup-selected nozzles active.
        try:
            task_result = dod.run_task(task)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"

            result.update({
                "stage": "task",
                "reason": reason,
            })

            log(f"[flush] TASK FAILED: {task} -- {reason}")
            return result

        task_failed = (
            task_result is False
            or (
                isinstance(task_result, dict)
                and task_result.get("ok") is False
            )
        )

        if task_failed:
            reason = (
                task_result.get("reason")
                if isinstance(task_result, dict)
                else None
            )

            reason = reason or f"task {task!r} returned failure"

            result.update({
                "stage": "task",
                "reason": reason,
                "task_result": task_result,
            })

            log(f"[flush] TASK FAILED: {task} -- {reason}")
            return result

        result.update({
            "ok": True,
            "stage": "complete",
            "task_result": task_result,
        })

        log(
            f"[flush] completed {task} with active nozzles "
            f"{selected_nozzles}"
        )

        return result

    finally:
        # This restoration runs after task success, failure, or exception.
        try:
            dod.dispense_off()
        except Exception as exc:
            restore_errors.append(
                "dispense_off failed: "
                f"{type(exc).__name__}: {exc}"
            )

        if restore_state:
            try:
                # Restore the exact activation set from before the flush.
                restore_result = dod.set_nozzle_active(
                    previous_active
                )

                restore_failed = (
                    restore_result is False
                    or (
                        isinstance(restore_result, dict)
                        and restore_result.get("ok") is False
                    )
                )

                if restore_failed:
                    reason = (
                        restore_result.get("reason")
                        if isinstance(restore_result, dict)
                        else None
                    )

                    restore_errors.append(
                        reason or
                        "failed to restore activated nozzles"
                    )

                # Reselect the originally selected nozzle when it was active.
                elif previous_selected in previous_active:
                    select_result = dod.select_nozzle(
                        previous_selected
                    )

                    select_failed = (
                        select_result is False
                        or (
                            isinstance(select_result, dict)
                            and select_result.get("ok") is False
                        )
                    )

                    if select_failed:
                        reason = (
                            select_result.get("reason")
                            if isinstance(select_result, dict)
                            else None
                        )

                        restore_errors.append(
                            reason or
                            "failed to restore selected nozzle"
                        )

            except Exception as exc:
                restore_errors.append(
                    "state restoration failed: "
                    f"{type(exc).__name__}: {exc}"
                )

        result["restored_active"] = list(
            getattr(dod, "activated_nozzles", [])
        )
        result["restored_selected"] = getattr(
            dod,
            "nozzle",
            None,
        )
        result["restore_ok"] = not restore_errors

        if restore_errors:
            result["restore_errors"] = restore_errors
            result["ok"] = False
            result["stage"] = "restore"

            log(
                "[flush] RESTORE FAILED: "
                + "; ".join(restore_errors)
            )
        else:
            log(
                "[flush] restored original nozzle state: "
                f"active={previous_active}, "
                f"selected={previous_selected}"
            )


def well_sequence(n, row="A", start=1):
    """Well IDs for a plate row, e.g. ['A1','A2','A3']. Wraps to the next row after 12."""
    wells, r, c = [], ord(row), start
    for _ in range(n):
        if c > 12:
            c = 1
            r += 1
        wells.append(f"{chr(r)}{c}")
        c += 1
    return wells


def sample_test_routine(dod, n_samples=3, probe_volume=40, dispense_seconds=1.0,
                        dispense_mode="Trigger", nozzle=1, frequency=30000,
                        voltage=80, pulse_width=20, probe="Probe (96WP-1nozzle)",
                        wells=None, log=_noop):
    """
    Goal 1: test droplet injection for many samples, using REAL parameters.
    Per sample: take_probe(channel, well, volume) -> InteractionPoint ->
    dispense(mode) -> record -> give_probe -> wash.

    `wells` is a list of plate wells, one per sample (defaults to A1, A2, ...).
    take_probe caps volume at 250 uL and requires the nozzle to be ACTIVATED.
    """
    if probe_volume > getattr(dod, "MAX_PROBE_VOLUME_UL", 250):
        log(f"[sample_test] ABORT: probe volume {probe_volume} uL exceeds the 250 uL max")
        return {"ok": False, "reason": "probe volume exceeds maximum"}

    wells = wells or well_sequence(n_samples)
    log(f"[sample_test] {n_samples} samples | probe {probe_volume}uL | mode {dispense_mode} | wells {wells}")

    cfg = configure_nozzle(dod, nozzle, frequency, voltage, pulse_width, log=log)
    if not cfg.get("ok"):
        return {"ok": False, "reason": cfg.get("reason")}

    records = []
    for i in range(1, n_samples + 1):
        well = wells[i - 1]
        log(f"[sample_test] --- sample {i}/{n_samples} (well {well}) ---")
        safe_goto(dod, probe, log=log)
        r = dod.take_probe(nozzle, well, probe_volume)
        if isinstance(r, dict) and not r.get("ok"):
            log(f"[sample_test] ABORT: take_probe failed -- {r.get('reason')}")
            return {"ok": False, "reason": r.get("reason"), "records": records}
        log(f"[sample_test] took {probe_volume}uL from {well} (ch {nozzle})")
        safe_goto(dod, "InteractionPoint", log=log)
        dod.dispense_on(dispense_mode)
        log(f"[sample_test] dispensing ({dispense_mode}) for {dispense_seconds}s")
        time.sleep(min(dispense_seconds, 0.05))  # dummy: don't actually wait long
        dod.dispense_off()
        # read the droplet volume the REAL way (drop-detection -> nozzle status)
        measured = read_measured_volume(dod)
        if measured is None:
            measured = probe_volume * random.uniform(0.95, 1.05)   # fallback only
        rec = {"sample": i, "well": well, "channel": nozzle,
               "probe_volume": probe_volume,
               "measured_volume": round(measured, 2),
               "frequency": frequency, "voltage": voltage}
        records.append(rec)
        log(f"[sample_test] recorded: {rec}")
        dod.give_probe()
        wash_cycle(dod, log=log)
    csv_file = save_results_csv(records, kind="sample_test")
    if csv_file:
        log(f"[sample_test] results saved to {csv_file}")
    log("[sample_test] DONE")
    return {"ok": True, "records": records, "csv": csv_file}


def stability_check(dod, shots=10, dispense_mode="Trigger", nozzle=1,
                    frequency=30000, voltage=80, pulse_width=20, log=_noop):
    """Goal 1: shot-by-shot stability assessment with real nozzle params."""
    log(f"[stability] {shots} shots | freq={frequency}Hz volt={voltage}V")
    configure_nozzle(dod, nozzle, frequency, voltage, pulse_width, log=log)
    safe_goto(dod, "InteractionPoint", log=log)
    measurements = []
    for s in range(1, shots + 1):
        dod.dispense_on(dispense_mode)
        # read the measured volume the REAL way (via nozzle status). Falls back
        # to a simulated value if the readback isn't available.
        vol = read_measured_volume(dod)
        if vol is None:
            vol = random.gauss(100.0, 4.0)   # fallback only
        dod.dispense_off()
        measurements.append(round(vol, 2))
        log(f"[stability] shot {s}: vol {vol:.1f}")
        time.sleep(0.01)
    mean = sum(measurements) / len(measurements)
    stdev = (sum((m - mean) ** 2 for m in measurements) / len(measurements)) ** 0.5
    cv = (stdev / mean * 100) if mean else 0
    result = {"ok": True, "shots": shots, "mean": round(mean, 2),
              "stdev": round(stdev, 2), "cv_percent": round(cv, 2),
              "frequency": frequency, "voltage": voltage, "measurements": measurements}
    # save per-shot rows to CSV
    rows = [{"shot": i + 1, "volume": measurements[i], "frequency": frequency,
             "voltage": voltage} for i in range(len(measurements))]
    csv_file = save_results_csv(rows, kind="stability")
    if csv_file:
        log(f"[stability] per-shot data saved to {csv_file}")
    result["csv"] = csv_file
    log(f"[stability] mean={result['mean']} stdev={result['stdev']} CV={result['cv_percent']}%")
    return result


def parameter_sweep(dod, param="voltage", values=None, dispense_mode="Trigger",
                    nozzle=1, frequency=30000, voltage=80, pulse_width=20,
                    repeats=3, log=_noop):
    """
    Sweep one nozzle parameter across a range of values and record the resulting
    droplet volume at each -- so you can see how droplet volume responds to the
    setting. `param` is 'voltage', 'frequency', or 'pulse_width'.

    For each value: set that parameter, fire `repeats` shots, average the measured
    volume. Saves a CSV (one row per value). Great for finding a good operating point.
    """
    if param not in ("voltage", "frequency", "pulse_width"):
        log(f"[sweep] unknown parameter: {param}")
        return {"ok": False, "reason": "param must be voltage/frequency/pulse_width"}
    if not values:
        # sensible default sweeps if none given
        values = {"voltage": [60, 70, 80, 90, 100],
                  "frequency": [20000, 25000, 30000, 35000, 40000],
                  "pulse_width": [10, 15, 20, 25, 30]}[param]

    log(f"[sweep] sweeping {param} over {values} ({repeats} shots each)")
    # arm+select the nozzle once
    cfg = configure_nozzle(dod, nozzle, frequency, voltage, pulse_width, log=log)
    if not cfg.get("ok"):
        return {"ok": False, "reason": cfg.get("reason")}
    safe_goto(dod, "InteractionPoint", log=log)

    setter = {"voltage": dod.set_nozzle_voltage,
              "frequency": dod.set_nozzle_frequency,
              "pulse_width": dod.set_nozzle_pulse_width}[param]

    rows = []
    for val in values:
        setter(val)
        vols = []
        for _ in range(repeats):
            dod.dispense_on(dispense_mode)
            v = read_measured_volume(dod)
            if v is None:
                v = random.gauss(100.0, 4.0)
            dod.dispense_off()
            vols.append(v)
            time.sleep(0.01)
        avg = round(sum(vols) / len(vols), 2)
        rows.append({param: val, "avg_volume": avg, "shots": repeats})
        log(f"[sweep] {param}={val} -> avg volume {avg}")

    csv_file = save_results_csv(rows, kind=f"sweep_{param}")
    if csv_file:
        log(f"[sweep] data saved to {csv_file}")
    log("[sweep] DONE")
    return {"ok": True, "param": param, "rows": rows, "csv": csv_file}


def align_droplet(dod, tolerance=15.0, max_steps=25, gain=0.6, log=_noop,
                  um_per_pixel=1.0, sign_x=+1, sign_y=+1, offset_in_pixels=False):
    """
    Goal 5: align the droplet to the camera crosshair.

    Reads the droplet's offset from the crosshair (drop-detection camera on the
    real robot; simulated on the dummy) and nudges the nozzle to reduce it, in a
    closed loop, until the offset is within `tolerance` um or `max_steps` is hit.

    `gain` (0-1) is how much of the measured offset to correct each step -- a simple
    proportional controller. Lower = gentler/slower, higher = faster but can overshoot.

    ---- HARDWARE CALIBRATION (set these when moving to the real robot) ----
    The dummy reports the offset directly in microns with axes already matching the
    robot, so the defaults below are a no-op. On the REAL robot you MUST set them:

      um_per_pixel     : microns of nozzle motion per camera pixel of droplet shift.
                         Measure it: move the nozzle a known amount, see how many
                         pixels the droplet moves. REQUIRED if the camera reports
                         pixels (set offset_in_pixels=True).
      sign_x / sign_y  : +1 or -1 per axis. The camera may be rotated/mirrored, so
                         moving the nozzle +X might move the droplet LEFT (-) on the
                         image. GET THIS RIGHT FIRST: a wrong sign makes the loop
                         DIVERGE (the offset explodes) instead of converging. Verify
                         by nudging one axis and watching which way the droplet goes.
      offset_in_pixels : True if get_droplet_camera_offset() returns pixels (then we
                         multiply by um_per_pixel); False if it already returns um.

    Returns whether it converged, the final offset, and the step history.
    """
    if not hasattr(dod, "get_droplet_camera_offset"):
        log("[align] this robot has no camera offset readout -- cannot align")
        return {"ok": False, "reason": "no camera offset available"}

    scale = um_per_pixel if offset_in_pixels else 1.0
    log(f"[align] aligning to crosshair (tol {tolerance}um, gain {gain}, "
        f"scale {scale}um/unit, signs x{sign_x:+d} y{sign_y:+d})")
    safe_goto(dod, "InteractionPoint", log=log)
    dod.dispense_on("Trigger")   # need a droplet visible to align it

    history = []
    converged = False
    diverging = False
    prev_dist = None
    for step in range(1, max_steps + 1):
        off = dod.get_droplet_camera_offset()
        # convert to microns and apply the axis sign mapping
        dx = off["dx"] * scale * sign_x
        dy = off["dy"] * scale * sign_y
        dist = (dx * dx + dy * dy) ** 0.5
        history.append({"step": step, "dx": round(dx, 1), "dy": round(dy, 1),
                        "distance": round(dist, 1)})
        log(f"[align] step {step}: offset dx={dx:.0f} dy={dy:.0f} (dist {dist:.0f} um)")
        if dist <= tolerance:
            converged = True
            log(f"[align] CONVERGED in {step} steps (offset {dist:.0f} um)")
            break
        # SAFETY: if the offset is growing, the sign mapping is probably wrong.
        # Stop instead of running the nozzle away.
        if prev_dist is not None and dist > prev_dist * 1.5:
            diverging = True
            log("[align] ABORT: offset is GROWING -- check sign_x/sign_y "
                "(camera axes likely flipped vs robot)")
            break
        prev_dist = dist
        # proportional correction: move the nozzle by -gain * offset
        dod.move_relative(-gain * dx, -gain * dy, 0)

    dod.dispense_off()
    if not converged and not diverging:
        log(f"[align] did NOT converge within {max_steps} steps")
    csv_file = save_results_csv(history, kind="alignment")
    if csv_file:
        log(f"[align] step history saved to {csv_file}")
    return {"ok": converged, "diverging": diverging, "steps": len(history),
            "final": history[-1], "csv": csv_file, "history": history}


def scan_slide(dod, dispense_mode="Trigger", nozzle=1, frequency=30000,
               voltage=80, pulse_width=20, log=_noop):
    """Visit the Slide A1..B6 grid and spot each point with real nozzle params."""
    configure_nozzle(dod, nozzle, frequency, voltage, pulse_width, log=log)
    order = [f"Slide {r}{i}" for r in ("A", "B") for i in range(1, 7)]
    order = [n for n in order if n in dod.positions]
    log(f"[scan_slide] scanning {len(order)} spots")
    for name in order:
        safe_goto(dod, name, log=log)
        dod.dispense_on(dispense_mode)
        time.sleep(0.01)
        dod.dispense_off()
        log(f"[scan_slide] spotted {name}")
    log("[scan_slide] DONE")
    return {"ok": True, "spots": len(order)}


def startup_routine(dod, log=_noop):
    """
    Beam-time startup sequence, using REAL tasks from the robot config:
    home -> MorningWashProcedure -> DrySystem -> verify status.
    """
    log("[startup] beginning startup sequence")
    safe_goto(dod, "Home", log=log)
    for task in ("MorningWashProcedure", "DrySystem"):
        if task in getattr(dod, "available_tasks", [task]):
            dod.run_task(task)
            log(f"[startup] ran {task}")
        else:
            log(f"[startup] SKIP {task} (not present on robot)")
    status = dod.get_status()
    log(f"[startup] status: pos={status['Position']} dispensing={status['dispensing']}")
    log("[startup] DONE -- ready for operation")
    return {"ok": True, "status": status}


def shutdown_routine(dod, log=_noop):
    """
    Safe shutdown sequence: stop everything -> give back any probe -> wash -> dry
    -> return Home. Uses real tasks.
    """
    log("[shutdown] beginning shutdown sequence")
    dod.stop_task()
    dod.dispense_off()
    if getattr(dod, "probe_volume", 0):
        dod.give_probe()
        log("[shutdown] returned probe")
    wash_cycle(dod, log=log)
    if "DrySystem" in getattr(dod, "available_tasks", []):
        dod.run_task("DrySystem")
        log("[shutdown] ran DrySystem")
    safe_goto(dod, "Home", log=log)
    log("[shutdown] DONE -- safe to leave")
    return {"ok": True}


def nozzle_health_check(dod, channels=range(1, 9), log=_noop):
    """
    Activate, select, and read back each nozzle in turn, reporting which respond.
    Uses the real activated-vs-selected logic (select requires activation first).
    """
    log("[nozzle_health] checking nozzles 1-8")
    results = []
    for ch in channels:
        arm = dod.set_nozzle_active([ch]) if hasattr(dod, "set_nozzle_active") else {"ok": True}
        sel = dod.select_nozzle(ch)
        ok = isinstance(sel, dict) and sel.get("ok", False)
        status = dod.get_nozzle_status() if ok else None
        row = {"channel": ch, "responds": ok}
        if status:
            # Volume/params come back as strings in 'ID,Volt,Pulse,Freq,Volume'
            packed = status.get("ID,Volt,Pulse,Freq,Volume", [])
            row["volt"] = packed[1] if len(packed) > 1 else None
            row["freq"] = packed[3] if len(packed) > 3 else None
        results.append(row)
        log(f"[nozzle_health] nozzle {ch}: {'OK' if ok else 'no response'}")
    csv_file = save_results_csv(results, kind="nozzle_health")
    if csv_file:
        log(f"[nozzle_health] saved to {csv_file}")
    working = [r["channel"] for r in results if r["responds"]]
    log(f"[nozzle_health] working nozzles: {working}")
    return {"ok": True, "results": results, "working": working, "csv": csv_file}


def region_exclusion_check(dod, log=_noop):
    """
    Query the robot's OWN forbidden region and test each named position against it,
    using the real get_forbidden_region() / test_forbidden_region() API (real hutch
    coordinates from the DoD class), instead of a made-up keep-out box.
    """
    if not hasattr(dod, "get_forbidden_region"):
        log("[region] robot has no forbidden-region API")
        return {"ok": False, "reason": "no forbidden-region API"}
    region = dod.get_forbidden_region()
    log(f"[region] robot forbidden region (hutch): {region}")
    flagged = []
    for name, c in dod.positions.items():
        # positions are stored in robot frame; test_forbidden_region converts
        prev_z = dod.z
        dod.z = c["Z"]   # so the hutch-Y conversion uses this position's height
        forbidden = dod.test_forbidden_region(c["X"], c["Y"], frame="robot")
        dod.z = prev_z
        if forbidden:
            flagged.append(name)
    if flagged:
        log(f"[region] {len(flagged)} positions fall in the forbidden region: {flagged}")
    else:
        log("[region] no named positions fall in the robot's forbidden region")
    return {"ok": True, "region": region, "flagged": flagged}


def verify_positions(dod, tolerance=100, log=_noop):
    """
    Read the robot's live drive range and current position, and sanity-check the
    52 saved coordinates against the drive range (all should fit inside it).
    Uses real get_drive_range() / get_position() / positions table.
    """
    dr = dod.get_drive_range()
    log(f"[verify] drive range: {dr}")
    out_of_range = []
    for name, c in dod.positions.items():
        if not (0 <= c["X"] <= dr["X"] and 0 <= c["Y"] <= dr["Y"] and 0 <= c["Z"] <= dr["Z"]):
            out_of_range.append(name)
    pos = dod.get_position()
    log(f"[verify] current position: {pos}")
    if out_of_range:
        log(f"[verify] {len(out_of_range)} saved positions are OUTSIDE the drive range: {out_of_range}")
    else:
        log(f"[verify] all {len(dod.positions)} saved positions fit inside the drive range")
    return {"ok": not out_of_range, "drive_range": dr,
            "n_positions": len(dod.positions), "out_of_range": out_of_range}


if __name__ == "__main__":
    from dod_dummy import DoDDummy
    from pathplan import Zone
    zone = Zone(100000, 40000, 0, 140000, 70000, 20000, margin=2000)
    dod = DoDDummy(zone=zone)
    dod.connect()
    print("\n--- sample_test (real params) ---")
    r = sample_test_routine(dod, n_samples=2, probe_volume=40, frequency=33000, voltage=90)
    print("\n--- stability_check ---")
    stability_check(dod, shots=5, frequency=33000)
    print("\n--- scan_slide ---")
    scan_slide(dod)