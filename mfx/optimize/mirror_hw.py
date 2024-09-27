"""
Initialize hardware for blop_scans and xopt_scans
"""
import random
from types import SimpleNamespace

from happi import Client
from ophyd.device import Device
from ophyd.sim import SynAxis, SynSignal
from pcdsdevices.ipm import Wave8

HAPPI_NAMES = (
    "mr1l4_homs",
    "mfx_dg1_ipm",
    "mfx_dg2_ipm",
)
# Default constants so I can re-use them
MIRROR_NOMINAL = -544
DG1_WAVE8_XPOS = 8
DG2_WAVE8_XPOS = 41

devices: dict[str, Device] = {}


def init_devices(force: bool = False) -> dict[str, Device]:
    """
    Collect all the devices needed for mfx mirror scanning into the "devices" dictionary.

    Returns the fully-loaded device dictionary.
    This can be simulated devices if sim_devices was called first.
    """
    if devices and not force:
        return devices

    client = Client.from_config("/cds/group/pcds/pyps/apps/hutch-python/device_config/happi.cfg")

    for name in HAPPI_NAMES:
        devices[name] = client.load_device(name=name)

    # Happi IPMs do not currently have wave8s, add manually
    for stand in ("dg1", "dg2"):
        name = f"mfx_{stand}_wave8"
        devices[name] = Wave8(f"MFX:{stand.upper()}:BMMON", name=name)
        devices[name].kind = "hinted"
    
    return devices


def sim_devices() -> dict[str, Device]:
    """
    Collect simulated stand-ins for all devices we might use in mfx mirror optimization into the "devices" dictionary.

    Returns the fully-loaded device dictionary.
    This is guaranteed to always be simulated devices.
    """
    if devices:
        if isinstance(devices["mr1l4_homs"], SimpleNamespace):
            return devices
    
    devices["mr1l4_homs"] = SimpleNamespace(pitch=SynAxis(name="mr1l4_homs_pitch", value=MIRROR_NOMINAL))
    devices["mfx_dg1_ipm"] = SimpleNamespace(inserted=True)
    devices["mfx_dg2_ipm"] = SimpleNamespace(inserted=False)
    dg1_offset = random.uniform(-1, 1)
    dg2_offset = random.uniform(-1, 1)

    print("Generated fake dg1 and dg2 signals")
    print("Expected: 1:1 linear relationship between x and pitch")
    print(f"Expected: dg1 reads {DG1_WAVE8_XPOS + dg1_offset} + noise when pitch is {MIRROR_NOMINAL}")
    print(f"Expected: dg2 reads {DG2_WAVE8_XPOS + dg2_offset} + noise when pitch is {MIRROR_NOMINAL}")
    print(f"default alignment on dg1 should pick {MIRROR_NOMINAL - dg1_offset}")
    print(f"default alignment on dg2 should pick {MIRROR_NOMINAL - dg2_offset}")

    def get_fake_dg1_wave8():
        pitch = devices["mr1l4_homs"].pitch.position
        return pitch - MIRROR_NOMINAL + DG1_WAVE8_XPOS + dg1_offset + random.uniform(-0.1, 0.1)
    
    def get_fake_dg2_wave8():
        pitch = devices["mr1l4_homs"].pitch.position
        return pitch - MIRROR_NOMINAL + DG2_WAVE8_XPOS + dg2_offset + random.uniform(-0.1, 0.1)

    devices["mfx_dg1_wave8"] = SimpleNamespace(
        xpos=SynSignal(
            func=get_fake_dg1_wave8,
            name="mfx_dg1_wave8_xpos"
        )
    )
    devices["mfx_dg2_wave8"] = SimpleNamespace(
        xpos=SynSignal(
            func=get_fake_dg2_wave8,
            name="mfx_dg2_wave8_xpos"
        )
    )
    devices["mfx_dg1_wave8"].kind = "hinted"
    devices["mfx_dg2_wave8"].kind = "hinted"
    
    return devices
