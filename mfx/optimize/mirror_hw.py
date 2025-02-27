"""
Initialize hardware for blop_scans and xopt_scans
"""
import random
from types import SimpleNamespace

import numpy as np
from happi import Client
from ophyd.areadetector.plugins import ImagePlugin
from ophyd.device import Component as Cpt
from ophyd.device import Device
from ophyd.signal import AttributeSignal
from ophyd.sim import SynAxis, SynSignal
from pcdsdevices.ipm import Wave8

HAPPI_NAMES = (
    "mr1l4_homs",
    "mfx_dg1_ipm",
    "mfx_dg2_ipm",
)
# Default constants so I can re-use them
# Default starting point for searches
MIRROR_NOMINAL = -548
# Used for sim devices and as default goal positions
DG1_WAVE8_XPOS = 8
DG2_WAVE8_XPOS = 41
XCS_YAG_XPOS = 337
DG1_YAG_XPOS = 191
DG2_YAG_XPOS = 191
IP_YAG_XPOS = 344


devices: dict[str, Device] = {}


class LCLSImagePlugin(ImagePlugin):
    shaped_image = Cpt(AttributeSignal, "image", add_prefix=(), kind="omitted")


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

    # Happi PIMs don't work how I want them to, add manually
    for stand in ("dg1", "dg2"):
        name = f"mfx_{stand}_yag"
        devices[name] = LCLSImagePlugin(f"MFX:{stand.upper()}:P6740:IMAGE1:", name=name)
        devices[name].kind = "hinted"
    name = "xcs_yag1"
    devices[name] = LCLSImagePlugin(f"XCS:GIGE:YAG1:IMAGE1:", name=name)

    devices["mfx_ip_yag"] = LCLSImagePlugin("MFX:GIGE:LBL:01:IMAGE1:", name="mfx_ip1_yag")
    devices["mfx_ip_yag"].kind = "hinted"

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
    dg1_wave8_offset = random.uniform(-1, 1)
    dg2_wave8_offset = random.uniform(-1, 1)
    dg1_yag_offset = random.uniform(-30, 30)
    dg2_yag_offset = random.uniform(-50, 50)
    ip_yag_offset = random.uniform(-70, 70)

    def get_fake_dg1_wave8() -> float:
        pitch = devices["mr1l4_homs"].pitch.position
        return pitch - MIRROR_NOMINAL + DG1_WAVE8_XPOS + dg1_wave8_offset + random.uniform(-0.1, 0.1)

    def get_fake_dg2_wave8() -> float:
        pitch = devices["mr1l4_homs"].pitch.position
        return pitch - MIRROR_NOMINAL + DG2_WAVE8_XPOS + dg2_wave8_offset + random.uniform(-0.1, 0.1)

    def get_fake_dg1_yag() -> np.ndarray:
        pitch = devices["mr1l4_homs"].pitch.position
        return fake_yag_image(
            size=(640, 480),
            centroid=((pitch - MIRROR_NOMINAL) * 30 + DG1_YAG_XPOS + dg1_yag_offset + random.uniform(-3, 3), 240 + random.uniform(-3, 3)),
            fwhm=30,
            peak=255,
        )

    def get_fake_dg2_yag() -> np.ndarray:
        pitch = devices["mr1l4_homs"].pitch.position
        return fake_yag_image(
            size=(640, 480),
            centroid=((pitch - MIRROR_NOMINAL) * 50 + DG2_YAG_XPOS + dg2_yag_offset + random.uniform(-5, 5), 240 + random.uniform(-5, 5)),
            fwhm=50,
            peak=255,
        )

    def get_fake_ip_yag() -> np.ndarray:
        pitch = devices["mr1l4_homs"].pitch.position
        return fake_yag_image(
            size=(688, 538),
            centroid=((pitch - MIRROR_NOMINAL) * 70 + IP_YAG_XPOS + ip_yag_offset + random.uniform(-7, 7), 269 + random.uniform(-7, 7)),
            fwhm=70,
            peak=255,
        )


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
    devices["mfx_dg1_yag"] = SimpleNamespace(
        shaped_image=SynSignal(
            func=get_fake_dg1_yag,
            name="mfx_dg1_yag_shaped_image",
        )
    )
    devices["mfx_dg2_yag"] = SimpleNamespace(
        shaped_image=SynSignal(
            func=get_fake_dg2_yag,
            name="mfx_dg2_yag_shaped_image",
        )
    )
    devices["mfx_ip_yag"] = SimpleNamespace(
        shaped_image=SynSignal(
            func=get_fake_ip_yag,
            name="mfx_ip_yag_shaped_image",
        )
    )
    devices["mfx_dg1_wave8"].kind = "hinted"
    devices["mfx_dg2_wave8"].kind = "hinted"
    devices["mfx_dg1_yag"].kind = "hinted"
    devices["mfx_dg2_yag"].kind = "hinted"
    devices["mfx_ip_yag"].kind = "hinted"

    print("Generated fake dg1 and dg2 signals and images")
    print("Expected: 1:1 linear relationship between x and pitch")
    print(f"Expected: dg1 wave8 reads {DG1_WAVE8_XPOS + dg1_wave8_offset} + noise when pitch is {MIRROR_NOMINAL}")
    print(f"Expected: dg2 wave8 reads {DG2_WAVE8_XPOS + dg2_wave8_offset} + noise when pitch is {MIRROR_NOMINAL}")
    print(f"Expected: dg1 yag reads {DG1_YAG_XPOS + dg1_yag_offset} + noise when pitch is {MIRROR_NOMINAL}")
    print(f"Expected: dg2 yag reads {DG2_YAG_XPOS + dg2_yag_offset} + noise when pitch is {MIRROR_NOMINAL}")
    print(f"Expected: dg2 yag reads {IP_YAG_XPOS + ip_yag_offset} + noise when pitch is {MIRROR_NOMINAL}")
    print(f"default alignment on dg1 wave8 should pick {MIRROR_NOMINAL - dg1_wave8_offset}")
    print(f"default alignment on dg2 wave8 should pick {MIRROR_NOMINAL - dg2_wave8_offset}")
    print(f"default alignment on dg1 yag should pick {MIRROR_NOMINAL - dg1_yag_offset}")
    print(f"default alignment on dg2 yag should pick {MIRROR_NOMINAL - dg2_yag_offset}")
    print(f"detault alignment on ip yag should pick {MIRROR_NOMINAL - ip_yag_offset}")

    return devices


def fake_yag_image(
    size: tuple[int, int],
    centroid: tuple[int, int],
    fwhm: int,
    peak: int,
) -> np.ndarray:
    # Adapted from https://stackoverflow.com/questions/7687679/how-to-generate-2d-gaussian-with-python
    x = np.arange(0, size[0], 1, float)
    y = np.arange(0, size[1], 1, float)[:, np.newaxis]
    x0 = centroid[0]
    y0 = centroid[1]
    arr = np.exp(-4*np.log(2) * ((x-x0)**2 + (y-y0)**2) / fwhm**2)
    return arr * peak
