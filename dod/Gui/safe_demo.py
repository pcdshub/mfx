import argparse
import sys


def connect_dod(ip):
    from dod.dod import DoD
    return DoD(ip=ip)


def _unwrap(r):
    return r.RESULTS if hasattr(r, "RESULTS") else r


def _readable(r):
    """Turn any robot reply into a short, readable status for the log."""
    v = _unwrap(r)
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        # common shapes: {'Status':...}, {'RESULTS':'Accepted'}, etc.
        for key in ("Status", "Result", "RESULTS", "Dispensing", "Selected"):
            if key in v:
                return str(v[key])
        return "ok"
    return "ok" if v is not None else "no reply"


def _client_do(dod, fn, *args):
    method = getattr(dod.client, fn)
    try:
        dod.client.connect("Test")     # register as an authorized user
    except Exception:
        pass
    try:
        r = method(*args)
    finally:
        try:
            dod.client.disconnect()
        except Exception:
            pass
    return r


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
    """The robot's OWN list of named positions, via client.get_position_names()."""
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

    armed = []
    if isinstance(activated, (list, tuple)):
        armed = [i + 1 for i, on in enumerate(activated) if on is True]

    print("\nArmed channels    : %s" % (armed if armed else "<none>"))
    print("Selected (fires)  : %s" % ("<not present>" if selected is None else selected))
    print("Dispensing        : %s" % ("<not present>" if dispensing is None else dispensing))

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
            idle_markers = ("", "na", "n/a", "none", "idle", "ready", "-")
            if running.lower() not in idle_markers:
                log("*** robot is busy running %r -- wait for it to finish. ***" % running)
                ok = False

            if dialog_is_open(st):
                log("*** an open DIALOG is showing -- the robot silently rejects "
                    "commands until it is closed: %r ***" % st.get("Dialog"))
                log("    (tip: close it at the robot, then retry.)")
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


SELF_POSITIONING_TASKS = {
    "WashFlush_Light_Narrow", "WashFlush_Medium", "WashFlush_Medium_Narrow",
    "WashFlush_Strong", "WashFlush_Strong_Narrow", "Washflush_Well",
}

NO_MOTION_TASKS = {"WashFlush_Piezo_only", "WashFlush_Piezo_Pump_only"}

MOVE_TASKS = {
    "MoveHome", "MoveToCameraStation", "MoveToWasteStation1", "MoveToTray1",
    "MoveToProbe_96WP", "MoveToInteractionPoint", "MoveToEppi1Nozzle1",
}

OPERATOR_TASKS = {"MorningWashProcedure"}


def wash_routine(dod, station=None, task=None, dry_run=True,
                 log=print, confirm=_terminal_confirm):
    if not station and not task:
        log("nothing to do -- give a task, a station, or both.")
        return {"ok": False, "reason": "nothing to do"}

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
        log("   -> %s" % (_readable(dod.set_nozzle_dispensing("Off")),))
        log("moving to '%s' ..." % station)
        log("   -> %s" % (_readable(dod.do_move(station)),))
        try:
            p = read_live_position(dod)
            log("   arrived: X=%.0f Y=%.0f Z=%.0f" % (p["X"], p["Y"], p["Z"]))
        except Exception as e:
            log("   could not verify arrival: %s" % e)

    if task:
        log("running task '%s' (blocks until done) ..." % task)
        log("   -> %s" % (_readable(dod.do_task(task)),))
        try:
            p = read_live_position(dod)
            log("   position after task: X=%.0f Y=%.0f Z=%.0f" % (p["X"], p["Y"], p["Z"]))
        except Exception as e:
            log("   could not read position: %s" % e)
        try:
            st = dod.get_status()
            running = str(st.get("RunningTask", "")).strip() if isinstance(st, dict) else ""
            if running.lower() not in ("", "na", "n/a", "none", "idle", "ready", "-"):
                log("   note: RunningTask is still %r" % running)
            else:
                log("   task finished, robot idle.")
        except Exception as e:
            log("   could not read status: %s" % e)

    log("routine complete.")
    return {"ok": True}


def read_activated_nozzles(dod):
    ns = dod.get_nozzle_status()
    if not isinstance(ns, dict):
        raise RuntimeError("nozzle status is %s, not a dict" % type(ns))
    act = ns.get("Activated Nozzles")
    if act is None:
        raise RuntimeError("no 'Activated Nozzles' field in nozzle status")

    def _is_boolish(v):
        return isinstance(v, bool) or (isinstance(v, str)
                                       and v.strip().lower() in ("true", "false"))

    def _truthy(v):
        return v is True or (isinstance(v, str) and v.strip().lower() == "true")

    if act and all(_is_boolish(v) for v in act):
        return [str(i + 1) for i, v in enumerate(act) if _truthy(v)]

    out = []
    for v in act:
        s = str(v).strip()
        if s and s.lower() not in ("false",):
            out.append(s)
    return out


def set_dispensing(dod, mode, dry_run=True, log=print, confirm=_terminal_confirm):
    mode = str(mode).strip().capitalize()
    if mode not in ("Off", "Free", "Trigger"):
        log("bad dispensing mode %r -- must be Off, Free, or Trigger" % mode)
        return {"ok": False, "reason": "bad mode"}

    log("=== SET DISPENSING: %s ===" % mode)

    if dry_run:
        log("[DRY RUN] would set dispensing to %r" % mode)
        return {"ok": True, "dry_run": True}

    if mode in ("Free", "Trigger"):
        if not confirm("Start dispensing in %r mode?\n\n"
                       "This makes the selected nozzle EJECT LIQUID.\n"
                       "Make sure the nozzle is over a safe target.\n\nProceed?" % mode):
            log("aborted -- dispensing not changed.")
            return {"ok": False, "reason": "not confirmed"}

    if hasattr(dod, "set_nozzle_dispensing"):
        r = dod.set_nozzle_dispensing(mode)
    else:
        r = _client_do(dod, "dispensing", mode)
    log("   dispensing set to %s -> %s" % (mode, _readable(r)))
    return {"ok": True, "result": r}


def select_nozzle(dod, channel, dry_run=True, log=print, confirm=_terminal_confirm):
    channel = str(channel)
    try:
        armed = read_activated_nozzles(dod)
    except Exception as e:
        log("could not read activated nozzles: %s -- refusing to select blind" % e)
        return {"ok": False, "reason": "no activated list"}

    if channel not in armed:
        log("nozzle %s is not activated (armed: %s) -- the robot would reject it."
            % (channel, armed))
        return {"ok": False, "reason": "not activated"}

    log("=== SELECT NOZZLE %s ===" % channel)

    has_dod_method = hasattr(dod, "set_nozzle_selected")
    if dry_run:
        log("[DRY RUN] would select nozzle %s" % channel)
        return {"ok": True, "dry_run": True}

    if not confirm("Select nozzle %s for dispensing/tasks?" % channel):
        log("aborted.")
        return {"ok": False, "reason": "not confirmed"}

    try:
        ch_int = int(channel)
    except ValueError:
        ch_int = channel

    if has_dod_method:
        r = dod.set_nozzle_selected(ch_int)
    else:
        r = _client_do(dod, "select_nozzle", str(ch_int))
    log("   nozzle %s selected -> %s" % (channel, _readable(r)))
    return {"ok": True, "result": r}


def set_nozzle_params(dod, volts=None, pulse=None, frequency=None,
                      select=None, dry_run=True, log=print, confirm=_terminal_confirm):
    ns = dod.get_nozzle_status()
    if not isinstance(ns, dict):
        log("could not read nozzle status (%s) -- refusing to set blind" % type(ns))
        return {"ok": False, "reason": "no nozzle status"}

    activated = ns.get("Activated Nozzles")
    selected = ns.get("Selected Nozzles")
    packed = ns.get("ID,Volt,Pulse,Freq,Volume")

    cur_v = cur_p = cur_f = None
    if isinstance(packed, (list, tuple)) and len(packed) >= 4:
        cur_v, cur_p, cur_f = packed[1], packed[2], packed[3]

    new_v = int(volts) if volts is not None else (int(float(cur_v)) if cur_v is not None else 80)
    new_p = str(pulse) if pulse is not None else (str(cur_p) if cur_p is not None else "20")
    new_f = int(frequency) if frequency is not None else (int(float(cur_f)) if cur_f is not None else 30000)

    def _channels(v, default):
        if v is None:
            return default
        if isinstance(v, (list, tuple)):
            def _boolish(x):
                return isinstance(x, bool) or (isinstance(x, str)
                                               and x.strip().lower() in ("true", "false"))
            def _truthy(x):
                return x is True or (isinstance(x, str) and x.strip().lower() == "true")
            if v and all(_boolish(x) for x in v):
                nums = [str(i + 1) for i, x in enumerate(v) if _truthy(x)]
                return ",".join(nums) if nums else default
            return ",".join(str(x).strip() for x in v
                            if str(x).strip() and str(x).strip().lower() != "false")
        return str(v)

    act_s = _channels(activated, "1")
    sel_s = str(select) if select is not None else _channels(selected, "1")

    log("=== SET NOZZLE PARAMS ===")
    log("   active=%s selected=%s volts=%d pulse=%s freq=%d"
        % (act_s, sel_s, new_v, new_p, new_f))

    if dry_run:
        log("[DRY RUN] would set volts=%d pulse=%s freq=%d on nozzle(s) %s"
            % (new_v, new_p, new_f, sel_s))
        return {"ok": True, "dry_run": True}

    if not confirm("Set nozzle parameters?\n\nvolts=%d  pulse=%s  freq=%d\nselected=%s"
                   % (new_v, new_p, new_f, sel_s)):
        log("aborted.")
        return {"ok": False, "reason": "not confirmed"}

    r = _client_do(dod, "set_nozzle_parameters", act_s, sel_s, new_v, new_p, new_f)
    log("   params set -> %s" % (_readable(r),))
    return {"ok": True, "result": r}


def jog_axis(dod, axis, delta, dry_run=True, log=print, confirm=_terminal_confirm):
    axis = axis.upper()
    if axis not in ("X", "Y", "Z"):
        log("bad axis %r" % axis)
        return {"ok": False, "reason": "bad axis"}

    here = read_live_position(dod)
    target = here[axis] + delta

    try:
        dr = read_drive_range(dod)
        lo, hi = 0.0, dr[axis]
        if target < lo or target > hi:
            clamped_target = min(max(target, lo), hi)
            log("would land at %s=%.0f, outside 0..%.0f -- clamping step"
                % (axis, target, hi))
            delta = clamped_target - here[axis]
            target = clamped_target
    except Exception as e:
        log("could not read drive range to clamp: %s -- refusing jog" % e)
        return {"ok": False, "reason": "no drive range"}

    if delta == 0:
        log("already at the limit on %s -- no move" % axis)
        return {"ok": False, "reason": "at limit"}

    log("JOG %s: %.0f -> %.0f  (%+.0f um)" % (axis, here[axis], target, delta))

    rel_name = "move_%s_rel" % axis.lower()
    abs_name = "move_%s_abs" % axis.lower()
    has_rel = hasattr(dod, rel_name)
    has_abs = hasattr(dod, abs_name)

    if has_rel:
        plan = "move %s by %+.0f um" % (axis, delta)
    elif has_abs:
        plan = "move %s to %.0f um" % (axis, target)
    else:
        log("this DoD has neither %s nor %s -- cannot jog." % (rel_name, abs_name))
        return {"ok": False, "reason": "no move method"}

    if dry_run:
        log("[DRY RUN] would %s" % plan)
        return {"ok": True, "dry_run": True}

    msg = ("RAW JOG -- no safety check.\n\n"
           "move %s by %+.0f um (from %.0f to %.0f)?\n\n"
           "This does NOT lift Z or check for collision. Make sure the\n"
           "nozzle can travel there without hitting anything.\n\nProceed?"
           % (axis, delta, here[axis], target))
    if not confirm(msg):
        log("jog aborted.")
        return {"ok": False, "reason": "not confirmed"}

    if has_rel:
        r = getattr(dod, rel_name)(delta)
    else:
        r = getattr(dod, abs_name)(target)
    log("   moved %s -> %s" % (axis, _readable(r)))
    try:
        p = read_live_position(dod)
        log("   now at: X=%.0f Y=%.0f Z=%.0f" % (p["X"], p["Y"], p["Z"]))
    except Exception as e:
        log("   could not verify: %s" % e)
    return {"ok": True}


def task_risk(task):
    tl = (task or "").lower()
    if task in NO_MOTION_TASKS or tl.startswith("wait"):
        return "none"
    if task in OPERATOR_TASKS:
        return "op"
    if (task in MOVE_TASKS or task in SELF_POSITIONING_TASKS
            or tl.startswith("moveto") or tl == "movehome"
            or tl.startswith("takeprobe") or "take_" in tl or "250725_take" in tl
            or "wash" in tl or "flush" in tl or "spot" in tl or "scan" in tl
            or "dip" in tl or "dry" in tl):
        return "move"
    return "?"


def describe_task(task):
    t = task or ""
    tl = t.lower()

    if task in NO_MOTION_TASKS:
        return "ultrasonic only -- no drive steps, nothing should move."
    if task in MOVE_TASKS or tl.startswith("moveto") or tl == "movehome":
        return "a single move: the robot drives itself to a named position."
    if task in OPERATOR_TASKS:
        return "PAUSES for an operator to click OK at the robot. It will block."
    if task in SELF_POSITIONING_TASKS:
        return "positions itself (WasteStation1 -> WashStation1 -> CameraStation) and washes."

    if tl.startswith("takeprobe") or "take_" in tl or tl.startswith("250725_take"):
        return ("takes a probe: moves to the sample well and pumps liquid into the "
                "nozzle, then parks. Moves the robot itself.")
    if "wash" in tl or "flush" in tl:
        return "a wash/flush task -- moves to wash/waste stations and runs pumps."
    if "dry" in tl:
        return "dries the system -- pumps/air, may move. check before running."
    if "spot" in tl or "scan" in tl:
        return "spotting/scanning routine -- moves across a target and dispenses."
    if "dip" in tl:
        return "dips the nozzle -- moves down into a station. moves the robot."
    if "autodrop" in tl or "dropdetection" in tl:
        return "drop detection -- fires the nozzle and measures the droplet."
    if tl.startswith("wait"):
        return "just waits -- no motion."
    if "resuspend" in tl or "mix" in tl:
        return "mixing/resuspend routine -- pumps liquid, may move."
    return "unknown task -- check what it does before running it."


def run_task(dod, task, dry_run=True, log=print, confirm=_terminal_confirm):
    note = describe_task(task)
    log("=== TASK: %s ===" % task)
    log("   what it does: %s" % note)

    if dry_run:
        log("[DRY RUN] would run task '%s'  (blocks until finished)" % task)
        log("Nothing run.")
        return {"ok": True, "dry_run": True}

    try:
        here = read_live_position(dod)
        where = "X=%.0f Y=%.0f Z=%.0f" % (here["X"], here["Y"], here["Z"])
    except Exception:
        where = "unknown"

    msg = ("Run task '%s'?\n\n%s\n\nRobot is at: %s\n\nProceed?"
           % (task, note, where))
    if not confirm(msg):
        log("aborted -- nothing run.")
        return {"ok": False, "reason": "not confirmed"}

    log("running '%s' (blocks until done) ..." % task)
    log("   -> %s" % (_readable(dod.do_task(task)),))
    try:
        p = read_live_position(dod)
        log("   position after: X=%.0f Y=%.0f Z=%.0f" % (p["X"], p["Y"], p["Z"]))
    except Exception as e:
        log("   could not read position: %s" % e)
    try:
        st = dod.get_status()
        running = str(st.get("RunningTask", "")).strip() if isinstance(st, dict) else ""
        _busy = running.lower() not in ("", "na", "n/a", "none", "idle", "ready", "-")
        log("   note: RunningTask still %r" % running if _busy else "   task finished, robot idle.")
    except Exception as e:
        log("   could not read status: %s" % e)
    log("task complete.")
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