"""

Reads, using only real DoD methods:
  1. live position   -- get_current_position()
  2. nozzle state    -- get_nozzle_status()   (activated vs selected channels)

"""

import argparse



def connect_dod(ip):
    from dod.dod import DoD
    return DoD(ip=ip)


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


def main():
    ap = argparse.ArgumentParser(description="Read the DoD robot's live state (read-only)")
    ap.add_argument("--ip", default="172.21.72.187")
    args = ap.parse_args()

    print("connecting to %s ..." % args.ip)
    dod = connect_dod(args.ip)

    # 1. live position
    print("\n=== LIVE POSITION (read-only) ===")
    pos = read_live_position(dod, verbose=True)
    print("\nLIVE (PositionReal): X=%.0f  Y=%.0f  Z=%.0f" % (pos["X"], pos["Y"], pos["Z"]))
    if pos["X"] == 0 and pos["Y"] == 0 and pos["Z"] == 0:
        print("*** SUSPECT: exactly (0,0,0) is the classic placeholder value. ***")

    # 2. nozzle state
    try:
        read_nozzle_state(dod)
    except Exception as e:
        print("\n=== NOZZLE STATE ===\nFAILED: %s" % e)

    print("\ndone. (nothing was moved)")


if __name__ == "__main__":
    main()