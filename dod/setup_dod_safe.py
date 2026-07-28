"""
setup_dod_safe.py — DoD + SafeRobot session setup for MFX hutch.

Run at the start of a hutch-python session:

    %run /cds/home/d/dehe/MFX_Hutch_Python/mfx/dod/setup_dod_safe.py

After running, two objects are available in your namespace:

    dod       — plain DoD instance (full access, no safety checks)
    dod_safe  — SafeRobot instance (safe_mode=False by default)

Enable safe mode when ready:

    dod_safe.safe_mode = True
"""

import sys
import importlib

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DOD_DIR = "/cds/home/d/dehe/MFX_Hutch_Python/mfx/dod"
_ROBOT_CONFIG = "/cds/home/d/dehe/Documents/MFX_Hutch_Python/mfx/dod/safe_motion/RunSetting.rsu.json"
_EXCLUSION_ZONES = "/cds/home/d/dehe/Documents/MFX_Hutch_Python/mfx/dod/safe_motion/exclusion_zones.json"
_IP = "172.21.39.172"
_LOG = "/tmp/dod.log"

# ---------------------------------------------------------------------------
# sys.path
# ---------------------------------------------------------------------------

for _p in [_DOD_DIR, f"{_DOD_DIR}/Gui"]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Evict cached modules so re-runs always pick up the latest code
# ---------------------------------------------------------------------------

for _key in list(sys.modules.keys()):
    if (
        _key == "safe_motion"
        or _key.startswith("safe_motion.")
        or _key in ("dod",)
        or _key.startswith("dod.")
    ):
        del sys.modules[_key]

# ---------------------------------------------------------------------------
# Plain DoD
# ---------------------------------------------------------------------------

import dod as _dod_mod

dod = _dod_mod.DoD(ip=_IP, log_file=_LOG)
print(f"[setup] dod       ready  (ip={_IP})")

# ---------------------------------------------------------------------------
# SafeRobot
# ---------------------------------------------------------------------------

from safe_motion import SafeRobot

dod_safe = SafeRobot(
    robot_config_path=_ROBOT_CONFIG,
    exclusion_zone_config=_EXCLUSION_ZONES,
    ip=_IP,
    log_file=_LOG,
)

print(f"[setup] dod_safe  ready  (safe_mode={dod_safe.safe_mode})")
print(f"[setup] sentinel  {dod_safe._sentinel_str}")
print()
print("  Enable safe mode when ready:  dod_safe.safe_mode = True")
