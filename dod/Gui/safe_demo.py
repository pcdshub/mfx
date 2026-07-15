"""

Reads, using only real DoD methods:
  1. live position : get_current_position()
  2. live drive range : client.get_drive_range()
  3. nozzle state  : get_nozzle_status()   (activated vs selected channels)

Routine (only with --station/--task, and only moves with --execute):
  go to a station, then run a task.

  The robot must be parked in a SAFE position BY HAND first. do_move() drives a
  straight line and does NOT check the path -- test_forbidden_region tests only
  the endpoint: "No testing of the path of a motion included!".


"""

import argparse
import sys


def connect_dod(ip):
    from dod.dod import DoD
    return DoD(ip=ip)


def _unwrap(r):
    return r.RESULTS if hasattr(r, "RESULTS") else r


def read_live_position(dod, verbose=False):
    """
    Read the robot's LIVE position from get_current_position().

    """
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
    """
    LIVE max range of each axis in um, via client.get_drive_range().
    This is a real endpoint on myClient, not a value from the config file.
    """
    r = _unwrap(dod.client.get_drive_range())
    if isinstance(r, dict) and {"X", "Y", "Z"} <= set(r.keys()):
        return {"X": float(r["X"]), "Y": float(r["Y"]), "Z": float(r["Z"])}
    if isinstance(r, (list, tuple)) and len(r) >= 3:
        return {"X": float(r[0]), "Y": float(r[1]), "Z": float(r[2])}
    raise RuntimeError("could not read drive range from %r" % (r,))


def read_nozzle_state(dod):
    """

    A nozzle must be ACTIVATED before it can be SELECTED -- the robot rejects
    select_nozzle() for any channel not in 'Activated Nozzles'.

    Prints the raw reply and reports only fields that are actually present.
    """
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

    print("\nActivated (armed) : %s" % ("<field not present>" if activated is None else activated))
    print("Selected (fires)  : %s" % ("<field not present>" if selected is None else selected))
    print("Dispensing        : %s" % ("<field not present>" if dispensing is None else dispensing))

    if isinstance(packed, (list, tuple)) and len(packed) >= 5:
        print("Params            : ID=%s Volt=%s Pulse=%s Freq=%s Volume=%s"
              % (packed[0], packed[1], packed[2], packed[3], packed[4]))
    elif packed is not None:
        print("Params            : unexpected shape -> %r" % (packed,))
    else:
        print("Params            : <'ID,Volt,Pulse,Freq,Volume' not present>")

    # consistency check: is the selected channel actually armed?
    try:
        act = [str(a) for a in activated] if activated is not None else []
        sel = [str(s) for s in selected] if selected is not None else []
        not_armed = [s for s in sel if s not in act]
        if not_armed:
            print("\n*** the selected nozzle(s) %s are NOT in the activated list %s."
                  % (not_armed, act))
            print("    The robot rejects select_nozzle() for unarmed channels. ***")
        elif sel:
            print("\nselected nozzle(s) %s are armed -- consistent." % sel)
    except TypeError:
        pass


def preflight(dod, station, task=None):
    """
    Checks before any motion. Returns True only if everything genuinely passed.
    Never reports OK on something we could not read.
    """
    print("\n=== PREFLIGHT (read-only) ===")
    ok = True

    try:
        st = dod.get_status()
        print("status:", st)
        if isinstance(st, dict):
            if st.get("RunningTask"):
                print("*** robot is busy running %r -- wait for it. ***" % st["RunningTask"])
                ok = False
            dlg = st.get("Dialog")
            if dlg and str(dlg).strip() not in ("", "None", "NA"):
                print("*** open DIALOG %r -- the robot silently rejects commands" % dlg)
                print("    until it is closed. ***")
                ok = False
    except Exception as e:
        print("FAILED to read status:", e)
        return False

    # only checks if it is actually given a task to run
    if task:
        try:
            tasks = [str(t) for t in list(_unwrap(dod.get_task_names()))]
            if task in tasks:
                print("task '%s' exists on the robot." % task)
            else:
                print("*** task '%s' is NOT on the robot. ***" % task)
                near = [t for t in tasks if task.lower()[:4] in t.lower()]
                if near:
                    print("similar names:", near)
                else:
                    print("robot has %d tasks: %s" % (len(tasks), sorted(tasks)))
                ok = False
        except Exception as e:
            print("FAILED to read task names:", e)
            ok = False

    print("\nPREFLIGHT: %s" % ("PASS" if ok else "PROBLEMS -- not proceeding"))
    return ok


def wash_routine(dod, station, task, dry_run):
    if task:
        print("\n=== ROUTINE: go to '%s', run '%s' ===" % (station, task))
    else:
        print("\n=== ROUTINE: go to '%s' (no task) ===" % station)

    if dry_run:
        print("\n[DRY RUN] would do, in order:")
        print("   1. dod.set_nozzle_dispensing('Off')")
        print("   2. dod.do_move('%s')      # straight line, no path check" % station)
        print("   3. read live position     # verify arrival")
        if task:
            print("   4. dod.do_task('%s')      # blocks until finished" % task)
            print("   5. dod.get_status()       # verify it ended clean")
        print("\nNothing moved. Add --execute to run it.")
        return

    print("\n*** The robot will move in a STRAIGHT LINE to '%s'." % station)
    print("    do_move does NOT check the path. Confirm it is clear first. ***")
    if input("\nType GO to run: ").strip() != "GO":
        print("aborted -- no motion.")
        return

    print("\n1. dispensing off")
    print("   ->", dod.set_nozzle_dispensing("Off"))

    print("\n2. moving to '%s' ..." % station)
    print("   ->", dod.do_move(station))

    print("\n3. verifying arrival")
    try:
        p = read_live_position(dod)
        print("   now at: X=%.0f Y=%.0f Z=%.0f" % (p["X"], p["Y"], p["Z"]))
    except Exception as e:
        print("   could not verify:", e)

    if task:
        print("\n4. running task '%s' (blocks until done) ..." % task)
        print("   ->", dod.do_task(task))

        print("\n5. final status")
        try:
            st = dod.get_status()
            print("   ", st)
            if isinstance(st, dict) and st.get("RunningTask"):
                print("   note: RunningTask is still %r" % st["RunningTask"])
        except Exception as e:
            print("   could not read status:", e)

    print("\nroutine complete.")


def main():
    ap = argparse.ArgumentParser(description="Read the DoD robot's live state, and run a routine")
    ap.add_argument("--ip", default="172.21.72.187")
    ap.add_argument("--station", default=None, help="named position to move to")
    ap.add_argument("--task", default=None,
                    help="optional: task to run once at the station")
    ap.add_argument("--execute", action="store_true", help="actually move and run")
    args = ap.parse_args()

    print("connecting to %s ..." % args.ip)
    dod = connect_dod(args.ip)

    # 1. live position
    print("\n=== LIVE POSITION (read-only) ===")
    pos = read_live_position(dod, verbose=True)
    print("\nLIVE (PositionReal): X=%.0f  Y=%.0f  Z=%.0f" % (pos["X"], pos["Y"], pos["Z"]))
    if pos["X"] == 0 and pos["Y"] == 0 and pos["Z"] == 0:
        print("*** SUSPECT: exactly (0,0,0) is the classic placeholder value. ***")

    # 2. live drive range
    print("\n=== DRIVE RANGE (read-only, live) ===")
    try:
        dr = read_drive_range(dod)
        print("X=%.0f  Y=%.0f  Z=%.0f" % (dr["X"], dr["Y"], dr["Z"]))
        if not (0 <= pos["X"] <= dr["X"] and 0 <= pos["Y"] <= dr["Y"]
                and 0 <= pos["Z"] <= dr["Z"]):
            print("*** the live position is OUTSIDE the live drive range --")
            print("    that should be impossible. Frame or units mismatch? ***")
        else:
            print("the live position is inside the drive range.")
    except Exception as e:
        print("FAILED to read drive range: %s" % e)

    # 3. nozzle state
    try:
        read_nozzle_state(dod)
    except Exception as e:
        print("\n=== NOZZLE STATE ===\nFAILED: %s" % e)

    # 4. routine (only if asked)
    if not args.station:
        print("\ndone. (nothing was moved)")
        return

    if not preflight(dod, args.station, args.task):
        print("\npreflight did not pass -- stopping.")
        sys.exit(1)

    wash_routine(dod, args.station, args.task, dry_run=not args.execute)


if __name__ == "__main__":
    main()