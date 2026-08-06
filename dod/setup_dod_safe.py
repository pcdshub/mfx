"""
setup_dod_safe.py — DoD + CoDI + SafeRobot session setup for MFX hutch.

Run at the start of a hutch-python session:

    %run /cds/home/d/dehe/Documents/MFX_Hutch_Python/mfx/dod/setup_dod_safe.py

After running, the following objects are available in your namespace:

    dod       — DoD instance with CoDI loaded (full access, no safety checks)
    codi      — alias for dod.codi (convenience)
    dod_safe  — SafeRobot instance (safe_mode=False by default)

Enable safe mode when ready:

    dod_safe.safe_mode = True

Set _DRYRUN = True (below) for off-hutch development; False on-hutch.
"""

import sys
import importlib
import importlib.util as _ilu

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DOD_DIR = "/cds/home/d/dehe/Documents/MFX_Hutch_Python/mfx/dod"
_CODI_LOCAL = "/sdf/home/d/dehe/Ops_supp/MFX_Hutch_Python/mfx/dod/codi.py"
_ROBOT_CONFIG = (
    "/cds/home/d/dehe/Documents/MFX_Hutch_Python/mfx/dod/safe_motion/RunSetting.rsu.json"
)
_EXCLUSION_ZONES = "/cds/home/d/dehe/Documents/MFX_Hutch_Python/mfx/dod/safe_motion/exclusion_zones.json"
_IP = "172.21.39.172"
_LOG = "/tmp/dod.log"

# Set True for off-hutch development (uses _MockMotor, no EPICS connections).
# Set False on-hutch with live hardware.
_DRYRUN = True

# ---------------------------------------------------------------------------
# sys.path
# ---------------------------------------------------------------------------

for _p in [_DOD_DIR, f"{_DOD_DIR}/Gui"]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Evict safe_motion modules so re-runs always pick up the latest code.
# ---------------------------------------------------------------------------

for _key in list(sys.modules.keys()):
    if _key == "safe_motion" or _key.startswith("safe_motion."):
        del sys.modules[_key]

# ---------------------------------------------------------------------------
# Reload local codi.py and register it as dod.codi before DoD is loaded.
# This ensures DoD.__init__ picks up the local development copy via
# "from dod.codi import CoDI", not the installed package version.
# ---------------------------------------------------------------------------

for _key in list(sys.modules.keys()):
    if _key == "dod.codi":
        del sys.modules[_key]

_codi_spec = _ilu.spec_from_file_location("dod.codi", _CODI_LOCAL)
assert _codi_spec is not None, f"Could not locate codi module at {_CODI_LOCAL}"
_codi_mod = _ilu.module_from_spec(_codi_spec)
sys.modules["dod.codi"] = _codi_mod
assert _codi_spec.loader is not None
_codi_spec.loader.exec_module(_codi_mod)
print(f"[setup] dod.codi  loaded from {_CODI_LOCAL}")

# ---------------------------------------------------------------------------
# Plain DoD (with CoDI)
# ---------------------------------------------------------------------------

import dod as _dod_mod

importlib.reload(_dod_mod)
if "dod.dod" in sys.modules:
    importlib.reload(sys.modules["dod.dod"])

dod = _dod_mod.DoD(ip=_IP, log_file=_LOG, modules="codi", dryrun=_DRYRUN)
codi = dod.codi
print(f"[setup] dod       ready  (ip={_IP})")
print(f"[setup] codi      ready  (dryrun={codi.dryrun})")

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
