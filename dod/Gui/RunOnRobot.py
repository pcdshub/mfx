"""
run_on_robot.py -- run ANY of your existing routines on the REAL robot.

Uses your unchanged dod_routines.py; only swaps DoDDummy -> RealDoDAdapter.

DRY RUN (default -- prints the real calls, moves nothing):
    python run_on_robot.py wash
    python run_on_robot.py all          # dry-run every routine in sequence

EXECUTE (real motion -- asks you to type GO):
    python run_on_robot.py wash --execute --ip 172.21.72.187

Routines: wash scan sample stability sweep nozzle startup shutdown
          health region verify status all
"""
import argparse, sys
from real_dod_adapter import RealDoDAdapter
import dod_routines as R


def run_one(dod, which):
    if which == "wash":       return R.wash_cycle(dod, log=print)
    if which == "scan":       return R.scan_slide(dod, log=print)
    if which == "sample":     return R.sample_test_routine(dod, n_samples=2, log=print)
    if which == "stability":  return R.stability_check(dod, shots=5, log=print)
    if which == "sweep":      return R.parameter_sweep(dod, param="voltage", log=print)
    if which == "nozzle":     return R.configure_nozzle(dod, nozzle=1, frequency=30000,
                                                        voltage=80, pulse_width=20, log=print)
    if which == "startup":    return R.startup_routine(dod, log=print)
    if which == "shutdown":   return R.shutdown_routine(dod, log=print)
    if which == "health":     return R.nozzle_health_check(dod, log=print)
    if which == "region":     return R.region_exclusion_check(dod, log=print)
    if which == "verify":     return R.verify_positions(dod, log=print)
    if which == "status":
        print("status:", dod.get_status()); print("position:", dod.get_position())
        return
    raise ValueError(which)


ALL = ["startup", "verify", "region", "health", "nozzle", "wash",
       "scan", "sample", "stability", "sweep", "shutdown"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("routine", choices=ALL + ["status", "all"])
    ap.add_argument("--ip", default="172.21.72.187")
    ap.add_argument("--port", type=int, default=9999)
    ap.add_argument("--execute", action="store_true", help="ACTUALLY move the robot")
    args = ap.parse_args()

    dry = not args.execute
    banner = "DRY RUN (no motion)" if dry else "*** EXECUTE (REAL MOTION) ***"
    print(f"{banner} -- '{args.routine}' on {args.ip}:{args.port}\n")

    if args.execute:
        if input("Type GO to move the REAL robot: ").strip() != "GO":
            print("aborted."); sys.exit(0)

    dod = RealDoDAdapter(ip=args.ip, port=args.port, dry_run=dry, log=print)
    dod.connect(); print()

    todo = ALL if args.routine == "all" else [args.routine]
    for which in todo:
        print("=" * 60); print(f"ROUTINE: {which}"); print("=" * 60)
        try:
            run_one(dod, which)
        except Exception as e:
            print(f"  !!! {which} FAILED: {e}")
        print()

    dod.disconnect(); print("done.")


if __name__ == "__main__":
    main()