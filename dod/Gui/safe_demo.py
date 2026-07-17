"""

Used two ways:
  - terminal:  %run safe_demo.py --ip 172.21.39.172 --station WashStation1
  - GUI:       dod_gui.py imports these functions and calls them

"""

import argparse
import sys


def connect_dod(ip):
    from dod.dod import DoD
    return DoD(ip=ip)


def _unwrap(r):
    return r.RESULTS if hasattr(r, "RESULTS") else r


# ---------------------------------------------------------------------------
# READS -- never move anything, never invent a value
# ---------------------------------------------------------------------------
def read_live_position(dod, verbose=False):
 
    r = dod.get_current_position()
    if verbose:
        print("RAW get_current_position():")
        print("   ", r)
    if not isinstance(r, dict):
        raise RuntimeError("get_current_position returned %s, expected dict" % type(r))

    real = r.get("PositionReal")
    if isinstance(real, dict) and {"X", "Y", "Z"} <= set(real.keys()):
        return {"X": float(real["X"]), "Y": float(real["Y"]), "Z": float(real["Z"])}
    if isinstance(real, (list, tuple)) and len(real) >= 3:
        return {"X": float(real[0]), "Y": float(real[1]), "Z": float(real[2])}
    raise RuntimeError("no usable PositionReal in reply (keys: %s)" % list(r.keys()))


def read_drive_range(dod):
    r = _unwrap(dod.client.get_drive_range())
    if isinstance(r, dict):
        if {"Xmax", "Ymax", "Zmax"} <= set(r.keys()):
            return {"X": float(r["Xmax"]), "Y": float(r["Ymax"]), "Z": float(r["Zmax"])}
        if {"X", "Y", "Z"} <= set(r.keys()):
            return {"X": float(r["X"]), "Y": float(r["Y"]), "Z": float(r["Z"])}
    if isinstance(r, (list, tuple)) and len(r) >= 3:
        return {"X": float(r[0]), "Y": float(r[1]), "Z": float(r[2])}
    raise RuntimeError("could not read drive range from %r" % (r,))


def read_station_names(dod):
    names = _unwrap(dod.client.get_position_names())
    if isinstance(names, dict):
        names = list(names.values())[0] if len(names) == 1 else list(names)
    return [str(n) for n in list(names)]


def read_task_names(dod):
    return [str(t) for t in list(_unwrap(dod.get_task_names()))]


def read_nozzle_state(dod):
    print("\n=== NOZZLE STATE (read-only) ===")
    r = dod.get_nozzle_status()
    print("RAW get_nozzle_status():")
    print("   ", r)
    if not isinstance(r, dict):
        print("reply is %s, not a dict -- cannot parse" % type(r))
        return

    activated = r.get("Activated Nozzles")
    selected = r.get("Selected Nozzles")
    dispensing = r.get("Dispensing")
    packed = r.get("ID,Volt,Pulse,Freq,Volume")

    # booleans -> channel numbers (index 0 == channel 1)
    armed = []
    if isinstance(activated, (list, tuple)):
        armed = [i + 1 for i, on in enumerate(activated) if on is True]

    print("\nArmed channels    : %s" % (armed if armed else "<none>"))
    print("Selected (fires)  : %s" % ("<not present>" if selected is None else selected))
    print("Dispensing        : %s" % ("<not present>" if dispensing is None else dispensing))

    # params: list of rows, one per nozzle
    if isinstance(packed, (list, tuple)) and packed and isinstance(packed[0], (list, tuple)):
        print("Nozzle parameters :")
        for row in packed:
            if len(row) >= 5:
                print("   ch %s: Volt=%s Pulse=%s Freq=%s Volume=%s"
                      % (row[0], row[1], row[2], row[3], row[4]))
            else:
                print("   unexpected row: %r" % (row,))
    elif isinstance(packed, (list, tuple)) and len(packed) >= 5:
        print("Nozzle parameters : ID=%s Volt=%s Pulse=%s Freq=%s Volume=%s"
              % (packed[0], packed[1], packed[2], packed[3], packed[4]))
    else:
        print("Nozzle parameters : <unexpected shape: %r>" % (packed,))

    # is the selected channel actually armed?
    try:
        sel = [int(s) for s in selected] if selected else []
        not_armed = [s for s in sel if s not in armed]
        if not_armed:
            print("\n*** selected nozzle(s) %s are NOT armed %s -- the robot rejects"
                  " select_nozzle() for unarmed channels. ***" % (not_armed, armed))
        elif sel:
            print("\nselected nozzle(s) %s are armed -- consistent." % sel)
    except (TypeError, ValueError):
        pass


def dialog_is_open(status):
    dlg = status.get("Dialog") if isinstance(status, dict) else None
    if not isinstance(dlg, dict):
        return bool(dlg) and str(dlg).strip() not in ("", "None", "NA")
    ref = dlg.get("Reference", 0)
    msg = str(dlg.get("Message", "")).strip()
    return (ref not in (0, "0", None)) or bool(msg)


# ---------------------------------------------------------------------------
# ROUTINE -- shared by the terminal and the GUI
# ---------------------------------------------------------------------------
def preflight(dod, station, task=None, log=print):
    """Checks before motion. True only if everything genuinely passed."""
    log("=== PREFLIGHT (read-only) ===")
    ok = True

    try:
        st = dod.get_status()
        log("status: %s" % (st,))
        if isinstance(st, dict):
            running = str(st.get("RunningTask", "")).strip()
            if running:
                log("*** robot is busy running %r -- wait for it. ***" % running)
                ok = False
            if dialog_is_open(st):
                log("*** an open DIALOG is showing -- the robot silently rejects "
                    "commands until it is closed: %r ***" % st.get("Dialog"))
                ok = False
    except Exception as e:
        log("FAILED to read status: %s" % e)
        return False

    if task:
        try:
            tasks = read_task_names(dod)
            if task in tasks:
                log("task '%s' exists on the robot." % task)
            else:
                log("*** task '%s' is NOT in the robot's task list. ***" % task)
                near = [t for t in tasks if task.lower()[:4] in t.lower()]
                if near:
                    log("similar names: %s" % near)
                else:
                    log("robot has %d tasks: %s" % (len(tasks), sorted(tasks)))
                ok = False
        except Exception as e:
            log("FAILED to read task names: %s" % e)
            ok = False

    log("PREFLIGHT: %s" % ("PASS" if ok else "PROBLEMS -- not proceeding"))
    return ok


def _terminal_confirm(message):
    print("\n" + message)
    return input("\nType GO to run: ").strip() == "GO"


# wash task conmfirmed from the .tsk files.
# e.g. WashFlush_Medium is: MoveToWasteStation1 -> pump ON -> syringe 250uL ->
# wait 7s -> move WashStation1 -> ultrasonic 10s -> syringe back ->
# move CameraStation -> pump OFF.  So a do_move() beforehand is REDUNDANT.
SELF_POSITIONING_TASKS = {
    "WashFlush_Light_Narrow", "WashFlush_Medium", "WashFlush_Medium_Narrow",
    "WashFlush_Strong", "WashFlush_Strong_Narrow", "Washflush_Well",
}

# Tasks with NO drive steps at all -- ultrasonic only. Zero motion, no liquid.
# The safest possible way to prove do_task() works on hardware.
NO_MOTION_TASKS = {"WashFlush_Piezo_only", "WashFlush_Piezo_Pump_only"}


def wash_routine(dod, station=None, task=None, dry_run=True,
                 log=print, confirm=_terminal_confirm):
    """
    Run a task, and optionally move to a station first.


    log(msg)         -- where progress goes (print, or the GUI's log box)
    confirm(message) -- must return True to proceed (input, or a GUI dialog)

    do_task() BLOCKS until the task finishes, it polls get_status() every 0.5 s
    while Status == "Busy". No manual wait is needed, and stop_task() afterwards
    would stop nothing. stop_task() also has a documented bug: it leaves the robot
    stuck in "Busy". The real abort hook is dod.safety_abort = True, which do_task
    checks each poll.
    """
    if not station and not task:
        log("nothing to do -- give a task, a station, or both.")
        return {"ok": False, "reason": "nothing to do"}

    # warn about a pointless move
    if station and task in SELF_POSITIONING_TASKS:
        log("NOTE: '%s' moves itself (WasteStation1 -> WashStation1 -> CameraStation)."
            % task)
        log("      The move to '%s' first is redundant -- consider dropping it."
            % station)

    moves = bool(station) or (task not in NO_MOTION_TASKS)
    if task in NO_MOTION_TASKS and not station:
        log("NOTE: '%s' has no drive steps -- ultrasonic only, nothing moves." % task)

    log("=== ROUTINE ===")
    if station:
        log("   move to  : %s" % station)
    if task:
        log("   run task : %s" % task)

    if dry_run:
        log("[DRY RUN] would do, in order:")
        n = 1
        if station:
            log("   %d. dod.set_nozzle_dispensing('Off')" % n); n += 1
            log("   %d. dod.do_move('%s')" % (n, station)); n += 1
            log("   %d. read live position  # verify arrival" % n); n += 1
        if task:
            log("   %d. dod.do_task('%s')   # blocks until finished" % (n, task)); n += 1
            log("   %d. read position + status  # verify it ended clean" % n)
        log("Nothing moved.")
        return {"ok": True, "dry_run": True}

    try:
        here = read_live_position(dod)
        where = "X=%.0f Y=%.0f Z=%.0f" % (here["X"], here["Y"], here["Z"])
    except Exception:
        where = "unknown"

    if moves:
        what = []
        if station:
            what.append("move to '%s'" % station)
        if task:
            what.append("run '%s'" % task)
            if task in SELF_POSITIONING_TASKS:
                what.append("(that task moves the robot itself)")
        msg = ("This will MOVE the real robot.\n\n    %s\n\n"
               "Currently at: %s\n\nProceed?" % ("\n    ".join(what), where))
    else:
        msg = ("Run '%s'?\n\nThis task has no drive steps -- ultrasonic only,\n"
               "nothing should move.\n\nCurrently at: %s\n\nProceed?" % (task, where))

    if not confirm(msg):
        log("aborted -- nothing run.")
        return {"ok": False, "reason": "not confirmed"}

    if station:
        log("dispensing off")
        log("   -> %s" % (dod.set_nozzle_dispensing("Off"),))
        log("moving to '%s' ..." % station)
        log("   -> %s" % (dod.do_move(station),))
        try:
            p = read_live_position(dod)
            log("   arrived: X=%.0f Y=%.0f Z=%.0f" % (p["X"], p["Y"], p["Z"]))
        except Exception as e:
            log("   could not verify arrival: %s" % e)

    if task:
        log("running task '%s' (blocks until done) ..." % task)
        log("   -> %s" % (dod.do_task(task),))
        try:
            p = read_live_position(dod)
            log("   position after task: X=%.0f Y=%.0f Z=%.0f" % (p["X"], p["Y"], p["Z"]))
        except Exception as e:
            log("   could not read position: %s" % e)
        try:
            st = dod.get_status()
            running = str(st.get("RunningTask", "")).strip() if isinstance(st, dict) else ""
            if running:
                log("   note: RunningTask is still %r" % running)
            else:
                log("   task finished, robot idle.")
        except Exception as e:
            log("   could not read status: %s" % e)

    log("routine complete.")
    return {"ok": True}


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="DoD live state + station/task routine")
    ap.add_argument("--ip", default="172.21.39.172")
    ap.add_argument("--station", default=None, help="named position to move to")
    ap.add_argument("--task", default=None, help="optional: task to run at the station")
    ap.add_argument("--tasks", action="store_true", help="list the robot's real tasks, then exit")
    ap.add_argument("--execute", action="store_true", help="actually move and run")
    args = ap.parse_args()

    print("connecting to %s ..." % args.ip)
    dod = connect_dod(args.ip)

    if args.tasks:
        print("\n=== REAL TASK LIST (what execute_task can call) ===")
        for t in sorted(read_task_names(dod)):
            print("   ", t)
        return

    print("\n=== LIVE POSITION (read-only) ===")
    pos = read_live_position(dod, verbose=True)
    print("\nLIVE (PositionReal): X=%.0f  Y=%.0f  Z=%.0f" % (pos["X"], pos["Y"], pos["Z"]))
    if pos["X"] == 0 and pos["Y"] == 0 and pos["Z"] == 0:
        print("*** SUSPECT: exactly (0,0,0) is the classic placeholder value. ***")

    print("\n=== DRIVE RANGE (read-only, live) ===")
    try:
        dr = read_drive_range(dod)
        print("X=%.0f  Y=%.0f  Z=%.0f" % (dr["X"], dr["Y"], dr["Z"]))
        if not (0 <= pos["X"] <= dr["X"] and 0 <= pos["Y"] <= dr["Y"]
                and 0 <= pos["Z"] <= dr["Z"]):
            print("*** the live position is OUTSIDE the live drive range. ***")
        else:
            print("the live position is inside the drive range.")
    except Exception as e:
        print("FAILED to read drive range: %s" % e)

    try:
        read_nozzle_state(dod)
    except Exception as e:
        print("\n=== NOZZLE STATE ===\nFAILED: %s" % e)

    if not args.station and not args.task:
        print("\ndone. (nothing was moved)")
        return

    print()
    if not preflight(dod, args.station, args.task):
        print("\npreflight did not pass -- stopping.")
        sys.exit(1)

    print()
    wash_routine(dod, args.station, args.task, dry_run=not args.execute)


if __name__ == "__main__":
    main()