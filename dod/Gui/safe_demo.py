"""
safe_demo.py -- a SAFE demo to run on the real robot today.


  PART 1 (READ ONLY -- zero motion, zero risk):
     - connect + read status/position
     - read the real drive range and check all named positions fit
     - read the robot's REAL forbidden regions and flag any positions inside
     These prove your code talks to the real DoD/hutch-python API correctly,
     WITHOUT moving anything.

  PART 2 (ONE guarded move -- only if you choose):
     - you pick a start you KNOW the robot is at, and a destination Sebastian
       confirms is a clear path
     - the script shows the straight-line distance and WARNS that the native
       move does not check the path
     - it requires you to type GO
     - it uses the robot's own do_move(name) for the destination

Run:
    python safe_demo.py --ip <IP>                 # PART 1 only (read-only)
    python safe_demo.py --ip <IP> --move Home     # PART 1 + guarded move to Home
"""

import argparse
import json
import sys


def load_positions(path="named_position_coords.json"):
    with open(path) as f:
        return json.load(f)


def make_dod(ip, port, dry_run):
    from real_dod_adapter import RealDoDAdapter
    dod = RealDoDAdapter(ip=ip, port=port, dry_run=dry_run, log=print)
    dod.connect()
    return dod


# ---------------------------------------------------------------------------
# PART 1 -- READ ONLY
# ---------------------------------------------------------------------------
def part1_readonly(dod, positions):
    print("\n" + "=" * 62)
    print("PART 1: READ-ONLY CHECKS (no motion)")
    print("=" * 62)

    print("\n[1/4] connection + status")
    try:
        st = dod.get_status()
        print("   status OK:", st)
    except Exception as e:
        print("   FAILED to read status:", e)
        print("   -> connection/IP problem. Stop here and check IP again maybe?.")
        return False

    print("\n[2/4] current position")
    try:
        print("   position:", dod.get_position())
    except Exception as e:
        print("   could not read position:", e)

    print("\n[3/4] drive range + do all 55 saved positions fit inside it?")
    try:
        dr = dod.get_drive_range()
        print("   drive range:", dr)
        oor = [n for n, c in positions.items()
               if not (0 <= c["X"] <= dr["X"] and 0 <= c["Y"] <= dr["Y"]
                       and 0 <= c["Z"] <= dr["Z"])]
        if oor:
            print(f"   {len(oor)} positions OUTSIDE drive range:", oor)
        else:
            print(f"   all {len(positions)} positions fit inside the drive range.")
    except Exception as e:
        print("   could not read drive range:", e)

    print("\n[4/4] robot's REAL forbidden regions + which positions fall inside")
    try:
        regions = dod.get_forbidden_region()
        print("   forbidden regions (from the robot):")
        for r in regions:
            print("     ", r)
        flagged = []
        for name, c in positions.items():
            try:
                if dod.test_forbidden_region(c["X"], c["Y"], frame="robot"):
                    flagged.append(name)
            except Exception:
                pass
        if flagged:
            print(f"   {len(flagged)} positions test as inside a forbidden region:")
            print("    ", flagged)
            print("   (this may reflect the coordinate-FRAME question -- see notes)")
        else:
            print("   no saved positions fall inside a forbidden region.")
    except Exception as e:
        print("   could not read forbidden regions:", e)

    print("\nPART 1 complete. the code reads real robot state with NO motion.")
    return True


# ---------------------------------------------------------------------------
# PART 2 -- ONE guarded move
# ---------------------------------------------------------------------------
def part2_guarded_move(dod, positions, dest, dry_run):
    print("\n" + "=" * 62)
    print(f"PART 2: ONE GUARDED MOVE -> '{dest}'")
    print("=" * 62)

    if dest not in positions:
        print(f"   '{dest}' is not a known position. Aborting.")
        return

    here = dod.get_position()
    tgt = positions[dest]
    dx = tgt["X"] - here["X"]
    dy = tgt["Y"] - here["Y"]
    dz = tgt["Z"] - here["Z"]
    dist = (dx * dx + dy * dy + dz * dz) ** 0.5

    print(f"   current : X={here['X']:.0f} Y={here['Y']:.0f} Z={here['Z']:.0f}")
    print(f"   target  : X={tgt['X']} Y={tgt['Y']} Z={tgt['Z']}  ({dest})")
    print(f"   straight-line distance: {dist:.0f} um")
    print()
    print("   *** WARNING ***")
    print("   do_move uses the robot's native move., it does")
    print("   NOT check the PATH -- only that the endpoint is valid.")
    print("   confirm that the straight path from HERE to the target is clear")
    print("   BEFORE proceeding. If you are not sure, do NOT move.")
    print()

    if dry_run:
        print("   [DRY RUN] would call do_move('%s') -- no motion." % dest)
        return

    resp = input(f"   Type GO to move to '{dest}' (anything else aborts): ").strip()
    if resp != "GO":
        print("   aborted -- no motion.")
        return
    r = dod.move_to_position(dest)
    print("   move result:", r)
    print("   final position:", dod.get_position())


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Safe real-robot demo (read-only + one guarded move)")
    ap.add_argument("--ip", default="172.21.72.187")
    ap.add_argument("--port", type=int, default=9999)
    ap.add_argument("--move", default=None,
                    help="optional: one destination position name for a guarded move")
    ap.add_argument("--execute", action="store_true",
                    help="allow the guarded move to actually move (still asks for GO)")
    args = ap.parse_args()

    positions = load_positions()
    dry = not args.execute
    print(f"{'DRY RUN' if dry else 'EXECUTE-CAPABLE'} demo on {args.ip}:{args.port}")

    dod = make_dod(args.ip, args.port, dry_run=dry)

    ok = part1_readonly(dod, positions)
    if not ok:
        dod.disconnect()
        sys.exit(1)

    if args.move:
        part2_guarded_move(dod, positions, args.move, dry_run=dry)
    else:
        print("\n(no --move given. Read-only demo done.)")

    dod.disconnect()
    print("\ndone.")


if __name__ == "__main__":
    main()
    