"""
Initialize hardware for blop_scans and xopt_scans
"""
import random
from types import SimpleNamespace

from happi import Client
from ophyd.device import Device
from ophyd.sim import SynAxis, SynSignal
from pcdsdevices.ipm import Wave8

from .devices import FakeLCLSImagePlugin, FakeYagCamera, YagCamera
from .undpoint import UndPointAbs2DMFX, UndPointAbs2DSim

HAPPI_NAMES = (
    "mr1l4_homs",
    "mfx_dg1_ipm",
    "mfx_dg2_ipm",
    "mfx_von_hamos_6crystal",
)
# Default constants so I can re-use them
# Default starting point for searches
MIRROR_NOMINAL = -544
# Used for sim devices and as default goal positions
DG1_WAVE8_XPOS = 8
DG2_WAVE8_XPOS = 41
XCS_YAG_XPOS = 337
DG1_YAG_XPOS = 300
DG2_YAG_XPOS = 300
IP_YAG_XPOS = 344
# Default min/max values for centroid positions
YAG_CENTROID_X_MIN_MAX = (180, 600)
YAG_CENTROID_Y_MIN_MAX = (400, 600)
WAVE8_CENTROID_X_MIN_MAX = (None, None)
WAVE8_CENTROID_Y_MIN_MAX = (None, None)

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

    # Happi PIMs don't work how I want them to, add manually
    for stand in ("dg1", "dg2"):
        name = f"mfx_{stand}_yag"
        devices[name] = YagCamera(f"MFX:GIGE:{stand.upper()}:YAG:", name=name)
        devices[name].kind = "hinted"

    devices["xcs_yag1"] = YagCamera("XCS:GIGE:YAG1:", name="xcs_yag1")
    devices["mfx_ip_yag"] = YagCamera("MFX:GIGE:LBL:01:", name="mfx_ip1_yag")
    devices["mfx_ip_yag"].kind = "hinted"

    devices["undp"] = UndPointAbs2DMFX()

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
    devices["undp"] = UndPointAbs2DSim()
    dg1_wave8_offset = random.uniform(-1, 1)
    dg2_wave8_offset = random.uniform(-1, 1)
    dg1_yag_offset = random.uniform(-30, 30)
    dg2_yag_offset = random.uniform(-50, 50)
    ip_yag_offset = random.uniform(-70, 70)
    undp_x0 = devices["undp"].position[0]
    undp_y0 = devices["undp"].position[1]

    def get_offsets() -> tuple[float, float, float]:
        return (
            devices["mr1l4_homs"].pitch.position - MIRROR_NOMINAL,
            devices["undp"].position[0] - undp_x0,
            devices["undp"].position[1] - undp_y0
        )

    def get_fake_dg1_wave8() -> float:
        mdpitch, undp_dx, _ = get_offsets()
        return mdpitch - undp_dx/200 + DG1_WAVE8_XPOS + dg1_wave8_offset + random.uniform(-0.1, 0.1)

    def get_fake_dg2_wave8() -> float:
        mdpitch, undp_dx, _ = get_offsets()
        return mdpitch - undp_dx/200 + DG2_WAVE8_XPOS + dg2_wave8_offset + random.uniform(-0.1, 0.1)

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
    devices["mfx_dg1_yag"] = FakeYagCamera("", name="mfx_dg1_yag")
    devices["mfx_dg2_yag"] = FakeYagCamera("", name="mfx_dg2_yag")
    devices["xcs_yag1"] = FakeYagCamera("", name="xcs_yag1")
    devices["mfx_ip_yag"] = FakeYagCamera("", name="mfx_ip_yag")

    def update_fake_dg1_yag(cam: FakeLCLSImagePlugin):
        mdpitch, undp_dx, undp_dy = get_offsets()
        cam.sim_set_image(
            size=(512, 512),
            centroid=(
                mdpitch * 60 - undp_dx * 3 + DG1_YAG_XPOS + dg1_yag_offset + random.uniform(-6, 6),
                256 + undp_dy * 3 + random.uniform(-3, 3)
            ),
            fwhm=100,
            peak=255,
        )

    def update_fake_dg2_yag(cam: FakeLCLSImagePlugin):
        mdpitch, undp_dx, undp_dy = get_offsets()
        cam.sim_set_image(
            size=(512, 512),
            centroid=(
                mdpitch * 80 - undp_dx * 4 + DG2_YAG_XPOS + dg2_yag_offset + random.uniform(-8, 8),
                256 + undp_dy * 4 + random.uniform(-5, 5)
            ),
            fwhm=150,
            peak=255,
        )

    def update_fake_xcs_yag1(cam: FakeLCLSImagePlugin):
        mdpitch, undp_dx, undp_dy = get_offsets()
        cam.sim_set_image(
            size=(728, 544),
            centroid=(
                mdpitch * 40 - undp_dx * 2 + XCS_YAG_XPOS + ip_yag_offset + random.uniform(-4, 4),
                274 + undp_dy * 2 + random.uniform(-7, 7)
            ),
            fwhm=200,
            peak=255,
        )

    def update_fake_ip1_yag(cam: FakeLCLSImagePlugin):
        mdpitch, undp_dx, undp_dy = get_offsets()
        cam.sim_set_image(
            size=(688, 538),
            centroid=(
                mdpitch * 70 - undp_dx * 3.5 + IP_YAG_XPOS + ip_yag_offset + random.uniform(-7, 7),
                269 + undp_dy * 3.5 + random.uniform(-7, 7)
            ),
            fwhm=80,
            peak=255,
        )

    devices["mfx_dg1_yag"].image1.sim_install_updater(update_fake_dg1_yag)
    devices["mfx_dg2_yag"].image1.sim_install_updater(update_fake_dg2_yag)
    devices["xcs_yag1"].image1.sim_install_updater(update_fake_xcs_yag1)
    devices["mfx_ip_yag"].image1.sim_install_updater(update_fake_ip1_yag)

    # MFX yags use opposite slit corners as the goal
    for name in ("mfx_dg1_yag", "mfx_dg2_yag", "mfx_ip_yag"):
        devices[name].coords.marker1.xpos.put(150)
        devices[name].coords.marker1.ypos.put(150)
        devices[name].coords.marker2.xpos.put(350)
        devices[name].coords.marker2.ypos.put(350)

    # XCS yag uses the location of marker 2 as the goal
    devices["xcs_yag1"].coords.marker2.xpos.put(360)
    devices["xcs_yag1"].coords.marker2.ypos.put(274)

    devices["mfx_dg1_wave8"].kind = "hinted"
    devices["mfx_dg2_wave8"].kind = "hinted"
    devices["mfx_dg1_yag"].kind = "hinted"
    devices["mfx_dg2_yag"].kind = "hinted"
    devices["xcs_yag1"].kind = "hinted"
    devices["mfx_ip_yag"].kind = "hinted"

    print("Generated fake dg1 and dg2 signals and images")
    print("Expected: 1:1 linear relationship between x and pitch")

    return devices
