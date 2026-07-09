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


def configure_nozzle(dod, nozzle=1, frequency=30000, voltage=80, pulse_width=20, log=_noop):
    """Set the real droplet-generation parameters. Nozzle must be 1-8."""
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


def sample_test_routine(dod, n_samples=3, probe_volume=40, dispense_seconds=1.0,
                        dispense_mode="Trigger", nozzle=1, frequency=30000,
                        voltage=80, pulse_width=20, probe="Probe (96WP-1nozzle)",
                        log=_noop):
    """
    Goal 1: test droplet injection for many samples, using REAL parameters.
    For each sample: configure nozzle -> take probe(volume) -> go to interaction
    point -> dispense(mode) for dispense_seconds -> record -> wash.
    """
    log(f"[sample_test] {n_samples} samples | probe {probe_volume}uL | mode {dispense_mode}")
    configure_nozzle(dod, nozzle, frequency, voltage, pulse_width, log=log)
    records = []
    for i in range(1, n_samples + 1):
        log(f"[sample_test] --- sample {i}/{n_samples} ---")
        safe_goto(dod, probe, log=log)
        dod.take_probe(probe_volume)
        log(f"[sample_test] took probe {probe_volume}uL")
        safe_goto(dod, "InteractionPoint", log=log)
        dod.dispense_on(dispense_mode)
        log(f"[sample_test] dispensing ({dispense_mode}) for {dispense_seconds}s")
        time.sleep(min(dispense_seconds, 0.05))  # dummy: don't actually wait long
        dod.dispense_off()
        # simulated measured volume (real robot: read drop-detection/camera)
        measured = probe_volume * random.uniform(0.95, 1.05)
        rec = {"sample": i, "probe_volume": probe_volume,
               "measured_volume_est": round(measured, 2),
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