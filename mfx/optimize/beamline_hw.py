"""
Initialize hardware for blop_scans and xopt_scans
"""
import random
from types import SimpleNamespace

from happi import Client
from ophyd.device import Device
from ophyd.sim import SynAxis, SynSignal
from ophyd import EpicsSignalRO
from pcdsdevices.pv_positioner import OnePVMotor
from pcdsdevices.ipm import Wave8

from .constraints import constraint_data
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
MIRROR_NOMINAL = constraint_data.mirr.range_center
# Used for sim devices and as default goal positions
DG1_WAVE8_XPOS = 8
DG2_WAVE8_XPOS = 41
IP_YAG_XPOS = 344

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

    und_abs = UndPointAbs2DMFX()
    devices["und_abs"] = und_abs
    devices["und_del"] = und_abs.delta_xy

    # Add vernier calibration devices
    devices["vernier_dccm_energy"] = EpicsSignalRO("MFX:DCCM:ENERGY", name="vernier_dccm_energy")
    devices["vernier_energy"] = OnePVMotor("MFX:USER:MCC:EPHOT:SET1", name="vernier_energy")
    devices["vernier_intensity"] = EpicsSignalRO("MFX:DG1:W8:01:SUM", name="vernier_intensity")

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
    und_abs = UndPointAbs2DSim()
    devices["und_abs"] = und_abs
    devices["und_del"] = und_abs.delta_xy
    dg1_wave8_offset = random.uniform(-1, 1)
    dg2_wave8_offset = random.uniform(-1, 1)
    xcs_yag_offset = random.uniform(-5, 5)
    dg1_yag_offset = random.uniform(-10, 10)
    dg2_yag_offset = random.uniform(-20, 20)
    ip_yag_offset = random.uniform(-30, 30)
    undp_x0 = devices["und_abs"].position[0]
    undp_y0 = devices["und_abs"].position[1]

    def get_offsets() -> tuple[float, float, float]:
        return (
            devices["mr1l4_homs"].pitch.position - MIRROR_NOMINAL,
            devices["und_abs"].position[0] - undp_x0,
            devices["und_abs"].position[1] - undp_y0
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
        xpos, ypos = constraint_data.yag["dg1"].roi_center
        cam.sim_set_image(
            size=(512, 512),
            centroid=(
                xpos + mdpitch * 60 + undp_dx * 3 + dg1_yag_offset + random.uniform(-6, 6),
                ypos + undp_dy * 3 + random.uniform(-3, 3)
            ),
            fwhm=100,
            peak=255,
        )

    def update_fake_dg2_yag(cam: FakeLCLSImagePlugin):
        mdpitch, undp_dx, undp_dy = get_offsets()
        xpos, ypos = constraint_data.yag["dg2"].roi_center
        cam.sim_set_image(
            size=(512, 512),
            centroid=(
                xpos + mdpitch * 80 + undp_dx * 4 + dg2_yag_offset + random.uniform(-8, 8),
                ypos + undp_dy * 4 + random.uniform(-5, 5)
            ),
            fwhm=150,
            peak=255,
        )

    def update_fake_xcs_yag1(cam: FakeLCLSImagePlugin):
        mdpitch, undp_dx, undp_dy = get_offsets()
        xpos, ypos = constraint_data.yag["xcs1"].roi_center
        cam.sim_set_image(
            size=(728, 544),
            centroid=(
                xpos + mdpitch * 40 + undp_dx * 2 + xcs_yag_offset + random.uniform(-4, 4),
                ypos + undp_dy * 2 + random.uniform(-7, 7)
            ),
            fwhm=200,
            peak=255,
        )

    def update_fake_ip1_yag(cam: FakeLCLSImagePlugin):
        mdpitch, undp_dx, undp_dy = get_offsets()
        cam.sim_set_image(
            size=(688, 538),
            centroid=(
                mdpitch * 70 + undp_dx * 3.5 + IP_YAG_XPOS + ip_yag_offset + random.uniform(-7, 7),
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
    for name in ("mfx_dg1_yag", "mfx_dg2_yag"):
        center = constraint_data.yag[name.split("_")[1]].roi_center
        devices[name].coords.marker1.xpos.put(center[0] - 100)
        devices[name].coords.marker1.ypos.put(center[0] - 100)
        devices[name].coords.marker2.xpos.put(center[1] + 100)
        devices[name].coords.marker2.ypos.put(center[1] + 100)

    # XCS yag uses the location of marker 2 as the goal
    devices["xcs_yag1"].coords.marker2.xpos.put(constraint_data.yag["xcs1"].roi_center[0])
    devices["xcs_yag1"].coords.marker2.ypos.put(constraint_data.yag["xcs1"].roi_center[1])

    devices["mfx_dg1_wave8"].kind = "hinted"
    devices["mfx_dg2_wave8"].kind = "hinted"
    devices["mfx_dg1_yag"].kind = "hinted"
    devices["mfx_dg2_yag"].kind = "hinted"
    devices["xcs_yag1"].kind = "hinted"
    devices["mfx_ip_yag"].kind = "hinted"

    # Add simulated vernier devices
    # Create a mutable container to track current position
    class PosTracker:
        def __init__(self, value):
            self.value = value
    
    pos_tracker = PosTracker(7000.0)
    
    class TrackingSynAxis(SynAxis):
        """SynAxis that tracks its position for use in derived signals."""
        def __init__(self, name, value, pos_tracker):
            super().__init__(name=name, value=value)
            self.pos_tracker = pos_tracker
            # Store initial value
            self._value = value
            
        def move(self, position, **kwargs):
            self._value = float(position)
            self.pos_tracker.value = float(position)
            # SynAxis doesn't have move(), use set() instead
            result = super().set(position, **kwargs)
            return result
            
        def set(self, value, **kwargs):
            self._value = float(value)
            self.pos_tracker.value = float(value)
            result = super().set(value, **kwargs)
            return result
            
        def put(self, value, **kwargs):
            """Override put to also update tracker when bluesky uses it."""
            self._value = float(value)
            self.pos_tracker.value = float(value)
            return super().put(value, **kwargs)
            
        @property
        def position(self):
            """Make position property return current value."""
            return self._value if hasattr(self, '_value') else self.pos_tracker.value
        
        def get(self):
            """Override get to return current tracked position."""
            return self.pos_tracker.value
    
    vernier_axis = TrackingSynAxis(name="vernier_energy", value=7000.0, pos_tracker=pos_tracker)
    devices["vernier_energy"] = vernier_axis
    
    # Create signals that dynamically calculate DCCM and intensity based on current vernier position
    # Use lambda to force fresh reading each time
    def get_fake_dccm_energy():
        """Calculate DCCM energy from vernier position with realistic offset."""
        # Read fresh value from tracker each time (closure captures the mutable object)
        vernier_pos = float(pos_tracker.value)
        
        # In REAL hardware, DCCM energy is a FIXED value set by the double crystal monochromator
        # The offset = DCCM - Vernier is what changes as we move the vernier
        # So: DCCM = vernier + offset
        
        # Simulate offset that varies with energy: offset = a0 + a1 * energy
        # Use realistic calibration coefficients
        a0 = -20.0  # eV baseline offset
        a1 = 0.02   # eV per eV (2% variation)
        offset = a0 + a1 * vernier_pos
        
        # DCCM energy = vernier + offset (this changes as vernier moves)
        dccm_energy = float(vernier_pos) + offset
        
        # Add small random noise to simulate measurement uncertainty
        noise = random.uniform(-0.5, 0.5)
        
        return dccm_energy + noise
    
    def get_fake_intensity():
        """Calculate intensity that peaks when vernier and DCCM are well-aligned."""
        # Read fresh value from tracker each time (closure captures the mutable object)
        vernier_pos = float(pos_tracker.value)
        
        # Simulate a vernier scan where intensity peaks when offset is smallest
        # The actual DCCM changes as we scan, so calculate what DCCM would be
        a0, a1 = -20.0, 0.02
        offset = a0 + a1 * vernier_pos
        
        # Intensity should be HIGHEST when offset is CLOSEST TO ZERO (vernier and DCCM aligned)
        # Calculate the absolute offset magnitude
        abs_offset = abs(offset)
        
        # When offset ≈ 0, intensity should be at peak (1000)
        # When |offset| is large, intensity should be low (~100)
        # Inverse relationship: intensity decreases with larger offset
        intensity_base = 1000.0 / (1 + abs_offset / 5.0)
        
        # Clamp to reasonable range
        intensity = max(100, min(1000, intensity_base))
        
        # Add small noise
        noise = random.uniform(-10, 10)
        
        final_intensity = max(50, intensity + noise)
        return final_intensity
    
    # Wrap in another function layer to ensure fresh eval
    def wrapper_dccm():
        return get_fake_dccm_energy()
    
    def wrapper_intensity():
        return get_fake_intensity()
    
    # Create the signal devices
    devices["vernier_dccm_energy"] = SynSignal(func=get_fake_dccm_energy, name="vernier_dccm_energy")
    devices["vernier_intensity"] = SynSignal(func=get_fake_intensity, name="vernier_intensity")
    
    # Mark these as hinted so they're included in scans
    devices["vernier_dccm_energy"].kind = "hinted"
    devices["vernier_intensity"].kind = "hinted"

    print("Generated fake dg1 and dg2 signals and images")
    print("Expected: 1:1 linear relationship between x and pitch")

    return devices
