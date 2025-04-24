"""
Load devices and functions for interactive use.
This is intended to be run in an ipython shell.

Normal ways to run:
- via mfxopr shortcut (mfx3 optimize)
- via script (real_interactive.sh, sim_iteractive.sh)
- via ipython run magic (%run mfx/optimize/interactive.py)

Suggested interactive testing dev workflows:
- Enter ipython via your favorite method above
- Use get_xopt_obj, get_blop_agent as desired and try them out.
- After making changes, restart for a clean session, rerun, or try the autoreload magic

Autoreload magics can be set up automatically via the --autoreload cli arg. E.g.:
- mfx3 optimize --autoreload
Under the hood, this does something like:
- %load_ext autoreload
- %autoreload explicit
- %aimport align, blop_scans, devices, mirror_hw, xopt_scans

See https://ipython.readthedocs.io/en/stable/config/extensions/autoreload.html
"""

def get_parser():
    """
    Separate parser logic so the rest can be tested without cli.

    This exists so we can
    - choose between simulated vs real devices
    - automatically set up autoreload for key modules

    This wraps the argparse module and parser object to avoid polluting the global namespace.
    """
    import argparse

    parser = argparse.ArgumentParser("mfx.optimize.interactive")
    parser.add_argument("--sim", action="store_true", help="Launch with simulated devices.")
    parser.add_argument("--autoreload", action="store_true", help="Launch with autoreload configured.")
    return parser


def get_objects(sim: bool = False):
    """
    Returns the objects we want to include as a dictionary of str keys.

    This wraps imports, etc. to avoid polluting the global namespace.
    """
    print("Importing support modules...")
    from mfx.optimize.beam import Beam
    from mfx.optimize.beamline_hw import init_devices, sim_devices
    from mfx.optimize.blop_scans import get_blop_agent
    from mfx.optimize.xopt_scans import get_xopt_obj

    if sim:
        print("Creating sim device objects...")
        devices = sim_devices()
    else:
        print("Creating real device objects...")
        devices = init_devices()

    print(f"Available devices are {list(devices)}")

    optimizers = {
        "beam": Beam(),
        "get_blop_agent": get_blop_agent,
        "get_xopt_obj": get_xopt_obj,
    }
    print(f"Available optimizers are {list(optimizers)}")

    devices.update(optimizers)
    return devices


def misc_setup(autoreload: bool = False):
    """
    Other setup actions that don't create objects
    """
    if autoreload:
        print("Enabling autoreload...")
        from IPython import get_ipython
        ip = get_ipython()
        if ip is None:
            raise RuntimeError("Not in an IPython shell, can't setup autoreload!")
        ip.run_line_magic("load_ext", "autoreload")
        ip.run_line_magic("autoreload", "1")
        line = [f"mfx.optimize.{imp}" for imp in ("beam", "beamline_hw", "blop_scans", "devices", "xopt_scans")]
        ip.run_line_magic("aimport", ",".join(line))


if __name__ == "__main__":
    args = get_parser().parse_args()
    globals().update(get_objects(args.sim))
    misc_setup(args.autoreload)
    # Remove helper functions and args to prevent pollution
    del get_objects
    del get_parser
    del misc_setup
    del args
