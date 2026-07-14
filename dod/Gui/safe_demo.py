"""
safe_demo.py -- a SAFE demo to run on the real robot.

Uses the real DoD class directly (no adapter layer), so every value printed is
read live from the robot. Nothing is faked or defaulted.

  PART 1 (READ ONLY -- zero motion):
     - connect + read status
     - read the LIVE position
     - check the saved positions fit the drive range
     - read the robot's forbidden regions and test the saved positions

  PART 2 (ONE guarded move -- only with --move and --execute):
     - prints the straight-line distance and warns the native move does not
       check the path
     - requires typing GO
     - uses the robot's own do_move(name)

Run:
    %run safe_demo.py --ip <IP>
    %run safe_demo.py --ip <IP> --move Home --execute
"""

import argparse
import json
import sys

DRIVE_RANGE = {"X": 254000, "Y": 118000, "Z": 40000}   # config [MaxAxisPos], not a live read


def load_positions(path="named_position_coords.json"):
    with open(path) as f:
        return json.load(f)


def connect_dod(ip):
    from dod.dod import DoD
    return DoD(ip=ip)


def read_live_position(dod, verbose=True):
    """
    Read the robot's position and show EVERYTHING it replied with.

    get_current_position() returns two candidate positions that can disagree:
        'PositionReal' : {'X':..,'Y':..,'Z':..}   -- dict
        'Position'     : ['0','Probe (96WP-1nozzle)','171497','114000','24893',...]
                          -- list; elements [2],[3],[4] are X,Y,Z as strings
    We print the raw reply and both candidates rather than silently picking one.
    Returns the PositionReal dict if present, else the Position list values.
    """
    r = dod.get_current_position()
    if verbose:
        print("   RAW get_current_position() reply:")
        print("     ", r)
    if not isinstance(r, dict):
        raise RuntimeError("get_current_position returned %s, expected dict" % type(r))

    from_real = None
    real = r.get("PositionReal")
    if isinstance(real, dict) and {"X", "Y", "Z"} <= set(real.keys()):
        from_real = {"X": float(real["X"]), "Y": float(real["Y"]), "Z": float(real["Z"])}
    elif isinstance(real, (list, tuple)) and len(real) >= 3:
        from_real = {"X": float(real[0]), "Y": float(real[1]), "Z": float(real[2])}

    from_list = None
    plist = r.get("Position")
    if isinstance(plist, (list, tuple)) and len(plist) >= 5:
        try:
            from_list = {"X": float(plist[2]), "Y": float(plist[3]), "Z": float(plist[4])}
        except (TypeError, ValueError):
            from_list = None

    if verbose:
        if from_real:
            print("     LIVE position (PositionReal) -> X=%.0f Y=%.0f Z=%.0f"
                  % (from_real["X"], from_real["Y"], from_real["Z"]))
        if from_list:
            name = plist[1] if len(plist) > 1 else "?"
            print("     (Position field = table entry '%s': %.0f, %.0f, %.0f"
                  " -- last named position, may be stale)"
                  % (name, from_list["X"], from_list["Y"], from_list["Z"]))

    # PositionReal is the live encoder reading. The Position field is a lookup
    # of the last named position commanded and does not track live motion.
    if from_real:
        return from_real
    if from_list:
        return from_list
    raise RuntimeError("no usable position in reply (keys: %s)" % list(r.keys()))


# ---------------------------------------------------------------------------
# PART 1 -- READ ONLY
# ---------------------------------------------------------------------------
def part1_readonly(dod, positions):
    print("\n" + "=" * 62)
    print("PART 1: READ-ONLY CHECKS (no motion)")
    print("=" * 62)
    problems = []

    print("\n[1/4] connection + status")
    try:
        st = dod.get_status()
        print("   status:", st)
    except Exception as e:
        print("   FAILED to read status:", e)
        print("   -> no connection. Check the IP and that the robot is up.")
        return False

    print("\n[2/4] live position")
    pos = None
    try:
        pos = read_live_position(dod)
        print("   position: X=%.0f Y=%.0f Z=%.0f" % (pos["X"], pos["Y"], pos["Z"]))
        if pos["X"] == 0 and pos["Y"] == 0 and pos["Z"] == 0:
            print("   *** SUSPECT: exactly (0,0,0) is the classic placeholder value.")
            print("       Check against the physical robot before trusting this. ***")
            problems.append("position reads (0,0,0) -- likely not real")
    except Exception as e:
        print("   FAILED to read position:", e)
        problems.append("position unreadable: %s" % e)

    print("\n[3/4] drive range + do the saved positions fit inside it?")
    dr = DRIVE_RANGE
    print("   drive range: X=%d Y=%d Z=%d  (from config, not a live read)"
          % (dr["X"], dr["Y"], dr["Z"]))
    oor = [n for n, c in positions.items()
           if not (0 <= c["X"] <= dr["X"] and 0 <= c["Y"] <= dr["Y"]
                   and 0 <= c["Z"] <= dr["Z"])]
    if oor:
        print("   %d positions OUTSIDE the drive range: %s" % (len(oor), oor))
        problems.append("%d positions outside drive range" % len(oor))
    else:
        print("   all %d saved positions fit inside it." % len(positions))
    if pos and not (0 <= pos["X"] <= dr["X"] and 0 <= pos["Y"] <= dr["Y"]
                    and 0 <= pos["Z"] <= dr["Z"]):
        print("   *** the LIVE position is outside the drive range -- that should")
        print("       be impossible. Frame or units mismatch? ***")
        problems.append("live position outside drive range")

    print("\n[4/4] forbidden regions + which saved positions test inside")
    try:
        regions = dod.get_forbidden_region("both")
        print("   forbidden regions read from the robot:")
        for r in regions:
            print("     ", r)
        flagged, errors = [], 0
        for name, c in positions.items():
            try:
                # real test_forbidden_region(x, y) returns True if SAFE
                if not dod.test_forbidden_region(c["X"], c["Y"]):
                    flagged.append(name)
            except Exception:
                errors += 1
        if errors:
            print("   (%d positions could not be tested)" % errors)
            problems.append("%d forbidden-region tests errored" % errors)
        pct = (100.0 * len(flagged) / len(positions)) if positions else 0
        print("   %d/%d positions (%.0f%%) test as FORBIDDEN"
              % (len(flagged), len(positions), pct))
        if pct > 50:
            print("   *** SUSPECT: most saved positions test as forbidden, but the")
            print("       robot uses them routinely -- so they cannot all be.")
            print("       Likely the saved positions and the forbidden regions are in")
            print("       DIFFERENT FRAMES. Source notes: hutch(x,y,z) = robot(x,-z,y).")
            print("       Confirm the frame before relying on this test. ***")
            problems.append("%.0f%% of positions test forbidden -- likely frame mismatch" % pct)
        elif flagged:
            print("   flagged:", flagged)
    except Exception as e:
        print("   FAILED to read forbidden regions:", e)
        problems.append("forbidden regions unreadable: %s" % e)

    print("\n" + "-" * 62)
    if problems:
        print("PART 1 finished with PROBLEMS -- this is NOT a pass:")
        for p in problems:
            print("   !", p)
        print("-" * 62)
        return False
    print("PART 1 PASSED: every value was read live from the robot and looks sane.")
    print("-" * 62)
    return True


# ---------------------------------------------------------------------------
# PART 2 -- ONE guarded move
# ---------------------------------------------------------------------------
def part2_guarded_move(dod, positions, dest, dry_run):
    print("\n" + "=" * 62)
    print("PART 2: ONE GUARDED MOVE -> '%s'" % dest)
    print("=" * 62)

    if dest not in positions:
        print("   '%s' is not a known position. Aborting." % dest)
        return

    here = read_live_position(dod)
    tgt = positions[dest]
    dx = tgt["X"] - here["X"]
    dy = tgt["Y"] - here["Y"]
    dz = tgt["Z"] - here["Z"]
    dist = (dx * dx + dy * dy + dz * dz) ** 0.5

    print("   current : X=%.0f Y=%.0f Z=%.0f" % (here["X"], here["Y"], here["Z"]))
    print("   target  : X=%s Y=%s Z=%s  (%s)" % (tgt["X"], tgt["Y"], tgt["Z"], dest))
    print("   straight-line distance: %.0f um" % dist)
    print()
    print("   *** WARNING ***")
    print("   do_move uses the robot's native move. It does NOT check the PATH --")
    print("   only that the endpoint is valid. Confirm the straight path from HERE")
    print("   to the target is clear BEFORE proceeding. If unsure, do NOT move.")
    print()

    if dry_run:
        print("   [DRY RUN] would call do_move('%s') -- no motion." % dest)
        return

    resp = input("   Type GO to move to '%s' (anything else aborts): " % dest).strip()
    if resp != "GO":
        print("   aborted -- no motion.")
        return
    r = dod.do_move(dest)
    print("   move result:", r)
    print("   final position:", read_live_position(dod))


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Safe real-robot demo (read-only + one guarded move)")
    ap.add_argument("--ip", default="172.21.72.187")
    ap.add_argument("--move", default=None, help="optional destination for a guarded move")
    ap.add_argument("--execute", action="store_true",
                    help="allow the guarded move to actually move")
    args = ap.parse_args()

    positions = load_positions()
    dry = not args.execute
    print("%s demo on %s" % ("DRY RUN" if dry else "EXECUTE-CAPABLE", args.ip))

    dod = connect_dod(args.ip)

    ok = part1_readonly(dod, positions)
    if not ok:
        sys.exit(1)

    if args.move:
        part2_guarded_move(dod, positions, args.move, dry_run=dry)
    else:
        print("\n(no --move given. Read-only demo done.)")

    print("\ndone.")


if __name__ == "__main__":
    main()