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

# Module-level trackers for vernier calibration
_vernier_pos_tracker = None
_dccm_tracker = None
_alignment_scan_mode = [False]
_calibration_scan_mode = [False]


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

    devices["xcs_wave8"] = Wave8("HXX:DG1:BMMON:", name="mfx_xcs_wave8")
    devices["xcs_wave8"].kind = "hinted"
    devices["xcs_yag1"] = YagCamera("XCS:GIGE:YAG1:", name="mfx_xcs_yag1")
    devices["xcs_yag1"].kind = "hinted"
    
    devices["mfx_dg1_wave8"] = Wave8(f"MFX:DG1:W8:01", name="mfx_dg1_wave8")
    devices["mfx_dg1_wave8"].kind = "hinted"
    devices["mfx_dg1_yag"] = YagCamera(f"MFX:GIGE:DG1:YAG:", name="mfx_dg1_yag")
    devices["mfx_dg1_yag"].kind = "hinted"

    devices["mfx_dg2_wave8"] = Wave8(f"MFX:DG2:BMMON", name="mfx_dg2_wave8")
    devices["mfx_dg2_wave8"].kind = "hinted"
    devices["mfx_dg2_yag"] = YagCamera(f"MFX:GIGE:DG2:YAG:", name="mfx_dg2_yag")
    devices["mfx_dg2_yag"].kind = "hinted"

    # Happi PIMs don't work how I want them to, add manually

    devices["mfx_ip_yag"] = YagCamera("MFX:GIGE:LBL:01:", name="mfx_ip1_yag")
    devices["mfx_ip_yag"].kind = "hinted"

    und_abs = UndPointAbs2DMFX()
    devices["und_abs"] = und_abs
    devices["und_del"] = und_abs.delta_xy

    # Add vernier calibration devices

    devices["vernier_energy"] = OnePVMotor("MFX:USER:MCC:EPHOT:SET1", name="vernier_energy")
    devices["vernier_intensity1"] = EpicsSignalRO("MFX:DG1:W8:01:SUM", name="vernier_intensity1")
    devices["vernier_intensity2"] = EpicsSignalRO("MFX:DG2:BMMON:SUM", name="vernier_intensity2")
    devices["vernier_intensity3"] = EpicsSignalRO("HXX:DG1:BMMON:SUM", name="vernier_intensity3")

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
    dg1_wave8_x_offset = random.uniform(-1, 1)
    dg2_wave8_x_offset = random.uniform(-1, 1)
    dg1_wave8_y_offset = random.uniform(-1, 1)
    dg2_wave8_y_offset = random.uniform(-1, 1)
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

    def get_fake_dg1_wave8_x() -> float:
        mdpitch, undp_dx, _ = get_offsets()
        return mdpitch - undp_dx/200 + DG1_WAVE8_XPOS + dg1_wave8_x_offset + random.uniform(-0.1, 0.1)

    def get_fake_dg2_wave8_x() -> float:
        mdpitch, undp_dx, _ = get_offsets()
        return mdpitch - undp_dx/200 + DG2_WAVE8_XPOS + dg2_wave8_x_offset + random.uniform(-0.1, 0.1)

    def get_fake_dg1_wave8_y() -> float:
        _, _, undp_dy = get_offsets()
        return - undp_dy/200 + dg1_wave8_y_offset + random.uniform(-0.1, 0.1)

    def get_fake_dg2_wave8_y() -> float:
        _, _, undp_dy = get_offsets()
        return - undp_dy/200 + dg2_wave8_y_offset + random.uniform(-0.1, 0.1)

    devices["mfx_dg1_wave8"] = SimpleNamespace(
        xpos=SynSignal(
            func=get_fake_dg1_wave8_x,
            name="mfx_dg1_wave8_xpos"
        ),
        ypos=SynSignal(
            func=get_fake_dg1_wave8_y,
            name="mfx_dg1_wave8_ypos"
        ),
        sum=SynSignal(
            func=lambda: random.uniform(0, 1000),
            name="mfx_dg1_wave8_sum",
        ),
    )
    devices["mfx_dg2_wave8"] = SimpleNamespace(
        xpos=SynSignal(
            func=get_fake_dg2_wave8_x,
            name="mfx_dg2_wave8_xpos"
        ),
        ypos=SynSignal(
            func=get_fake_dg2_wave8_y,
            name="mfx_dg2_wave8_ypos"
        ),
        sum=SynSignal(
            func=lambda: random.uniform(0, 1000),
            name="mfx_dg2_wave8_sum",
        ),
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
    
    # Initialize trackers at module level if not already done
    global _vernier_pos_tracker, _dccm_tracker, _alignment_scan_mode, _calibration_scan_mode
    if _vernier_pos_tracker is None:
        _vernier_pos_tracker = PosTracker(7000.0)
    if _dccm_tracker is None:
        _dccm_tracker = PosTracker(7000.0)
    pos_tracker = _vernier_pos_tracker
    
    class TrackingSynAxis(SynAxis):
        """SynAxis that tracks its position for use in derived signals."""
        def __init__(self, name, value, pos_tracker):
            super().__init__(name=name, value=value)
            self.pos_tracker = pos_tracker
            # Store initial value
            self._value = value
            # Store commanded position (what we're trying to reach)
            self._commanded = value
            
        def move(self, position, **kwargs):
            # When moving vernier manually, check if we should apply systematic offset
            import random
            target_energy = float(position)
            
            # Check if we're in alignment mode (no offset)
            if _alignment_scan_mode[0]:
                # Alignment mode: move to exact position (no offset)
                actual_position = target_energy
                actual_position += random.uniform(-1, 1)
            else:
                # Normal mode: apply systematic offset
                a0, a1 = -100, 0.02
                systematic_offset = a0 + a1 * target_energy
                actual_position = target_energy + systematic_offset
                actual_position += random.uniform(-1, 1)
            
            self._commanded = target_energy
            self._value = actual_position
            self.pos_tracker.value = actual_position
            # SynAxis doesn't have move(), use set() instead
            result = super().set(actual_position, **kwargs)
            return result
            
        def set(self, value, **kwargs):
            # During scans, bluesky calls set() (not put() in some cases)
            target_energy = float(value)
            
            # Check if we're in alignment mode (no offset)
            if _alignment_scan_mode[0]:
                # Alignment mode: vernier lands exactly at commanded position (no offset)
                vernier_actual = target_energy
                # Add small noise
                import random
                vernier_actual += random.uniform(-1, 1)
                # DON'T update dccm_tracker - DCCM should be set separately
            elif _calibration_scan_mode[0]:
                # Calibration mode: BOTH DCCM and vernier move to target together
                # This simulates the real hardware where both are commanded to the same energy
                _dccm_tracker.value = target_energy
                
                # Vernier lands with systematic offset
                # offset = vernier - DCCM (positive when vernier > DCCM)
                a0, a1 = -100, 0.02
                systematic_offset = a0 + a1 * target_energy
                # If offset = vernier - DCCM and we want offset = systematic_offset
                # Then: vernier = DCCM + systematic_offset = target + systematic_offset
                vernier_actual = target_energy + systematic_offset
                
                # Add small noise
                import random
                vernier_actual += random.uniform(-1, 1)
            else:
                # Normal mode (manual moves): DON'T update DCCM tracker
                # DCCM tracker should only be updated when explicitly setting DCCM energy
                
                # Vernier lands with systematic offset
                # offset = vernier - DCCM (positive when vernier > DCCM)
                a0, a1 = -100, 0.02
                systematic_offset = a0 + a1 * target_energy
                # If offset = vernier - DCCM and we want offset = systematic_offset
                # Then: vernier = DCCM + systematic_offset = target + systematic_offset
                vernier_actual = target_energy + systematic_offset
                
                # Add small noise
                import random
                vernier_actual += random.uniform(-1, 1)
            
            self._commanded = target_energy
            self._value = vernier_actual
            self.pos_tracker.value = vernier_actual
            result = super().set(vernier_actual, **kwargs)
            return result
            
        def put(self, value, **kwargs):
            """Override put to also update tracker when bluesky uses it."""
            # During scans, bluesky moves to target energy
            # In REAL hardware: both DCCM and vernier move together to this target energy
            # But vernier has systematic offset that depends on the target energy
            # Higher target energy → higher offset
            
            target_energy = float(value)
            
            # Check mode to decide whether to update DCCM
            if _alignment_scan_mode[0]:
                # Alignment mode: vernier lands exactly at commanded position (no offset)
                vernier_actual = target_energy
                # Add small noise
                import random
                vernier_actual += random.uniform(-1, 1)
                # DON'T update dccm_tracker - DCCM should be set separately
            elif _calibration_scan_mode[0]:
                # Calibration mode: BOTH DCCM and vernier move to target together
                _dccm_tracker.value = target_energy
                
                # Simulate systematic vernier offset: offset = a0 + a1 * target_energy
                a0 = -100  # eV baseline offset
                a1 = 0.02  # offset increases with energy (2% of target)
                systematic_offset = a0 + a1 * target_energy
                
                # Vernier lands at target + offset
                vernier_actual = target_energy + systematic_offset
                
                # Add random noise
                import random
                vernier_actual += random.uniform(-1, 1)
            else:
                # Normal mode (manual moves): DON'T update DCCM tracker
                # Simulate systematic vernier offset: offset = a0 + a1 * target_energy
                a0 = -100  # eV baseline offset
                a1 = 0.02  # offset increases with energy (2% of target)
                systematic_offset = a0 + a1 * target_energy
                
                # Vernier lands at target + offset
                vernier_actual = target_energy + systematic_offset
                
                # Add random noise
                import random
                vernier_actual += random.uniform(-1, 1)
            
            self._commanded = target_energy
            self._value = vernier_actual
            self.pos_tracker.value = vernier_actual
            
            # Call SynAxis with the actual vernier position
            return super().put(vernier_actual, **kwargs)
            
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
    # Use global keyword to ensure we access the global tracker, not a closure
    def get_fake_dccm_energy():
        """Calculate DCCM energy - changes with target energy."""
        # Force access to the global tracker, not a closure copy
        import mfx.optimize.beamline_hw as bl_hw
        tracker = bl_hw._dccm_tracker
        
        # In REAL hardware: when you move both DCCM and vernier together to a target energy,
        # DCCM lands at the target, but vernier lands with an offset
        # The offset depends on the target energy: higher target → higher offset
        
        # Get the current DCCM tracker value (always read from module-level tracker)
        if tracker is not None:
            target_energy = float(tracker.value)
        else:
            target_energy = 7000.0
        
        # DCCM lands close to target (small measurement noise)
        noise = random.uniform(-0.5, 0.5)
        dccm_val = target_energy + noise
        
        return dccm_val
    
    def get_fake_intensity():
        """Calculate intensity that peaks when vernier and DCCM are well-aligned."""
        import math
        # Force access to the global tracker, not a closure copy
        import mfx.optimize.beamline_hw as bl_hw
        vernier_tracker = bl_hw._vernier_pos_tracker
        
        # Read the actual vernier position from tracker
        # This is the position bluesky reports from the scan
        vernier_measured = float(vernier_tracker.value)
        
        # Read the DCCM energy (what it actually is)
        current_dccm = get_fake_dccm_energy()
        
        # Calculate offset: how far is vernier from DCCM?
        # Offset = Vernier - DCCM  
        offset_from_dccm = vernier_measured - current_dccm
        
        # Intensity peaks when offset is close to zero (vernier ≈ DCCM)
        # Use absolute offset so both positive and negative offsets reduce intensity
        abs_offset = abs(offset_from_dccm)
        
        # Gaussian profile: intensity = 1000 * exp(-offset^2 / (2*sigma^2))
        # Use sigma = 5 eV for good sensitivity: 
        # - At offset=0: intensity = 1000
        # - At offset=5 eV: intensity ≈ 600
        # - At offset=10 eV: intensity ≈ 135
        # - At offset=15 eV: intensity ≈ 11
        sigma = 5.0  # eV - controls sensitivity (lower = more sensitive)
        intensity_base = 1000.0 * math.exp(-(abs_offset ** 2) / (2 * sigma ** 2))
        
        # Debug: print offset and intensity calculation
        print(f"[INTENSITY] vernier={vernier_measured:.1f}, dccm={current_dccm:.1f}, offset={offset_from_dccm:.1f}, intensity_calc={intensity_base:.1f}")
        
        # Add measurement noise
        noise = random.uniform(-5, 5)
        final_intensity = max(50, min(1000, intensity_base + noise))
        
        return final_intensity
    
    # Wrap in another function layer to ensure fresh eval
    # Use lambda with global to ensure fresh reference
    def wrapper_dccm():
        return get_fake_dccm_energy()
    
    def wrapper_intensity():
        return get_fake_intensity()
    
    # For simulation, prefer using read_dccm_energy() helper rather than a fake PV.
    # Keep intensity as a SynSignal for scans.
    devices["vernier_intensity"] = SynSignal(func=wrapper_intensity, name="vernier_intensity")
    devices["vernier_intensity"].kind = "hinted"

    print("Generated fake dg1 and dg2 signals and images")
    print("Expected: 1:1 linear relationship between x and pitch")

    return devices


# Expose trackers for external use
def get_vernier_pos_tracker():
    """Get the vernier position tracker."""
    return _vernier_pos_tracker


def get_dccm_tracker():
    """Get the DCCM tracker."""
    return _dccm_tracker


def get_alignment_scan_mode():
    """Get the alignment scan mode flag."""
    return _alignment_scan_mode


def get_calibration_scan_mode():
    """Get the calibration scan mode flag."""
    return _calibration_scan_mode


# Helper API: preferred way to read DCCM energy in both real and simulation
def read_dccm_energy() -> float:
    """
    Read the current DCCM energy in eV.

    - In simulation (sim_devices() initialized): returns the simulated tracker value
    - In real hardware: instantiates DCCM and reads the pseudo motor energy (keV),
      then converts to eV.
    """
    # If simulation tracker exists, use it
    global _dccm_tracker
    try:
        if _dccm_tracker is not None:
            return float(_dccm_tracker.value)
    except Exception:
        ...

    # Real hardware path: use DCCM device
    try:
        from mfx.dccm import DCCM
        dccm = DCCM(name="DCCM")
        # dccm.energy is in keV; convert to eV
        keV = float(dccm.energy())
        return keV * 1000.0
    except Exception:
        print(f"[read_dccm_energy] WARNING: Could not import DCCM device: {e}")
        return 0.0
    # If all else fails, return a reasonable default
    return 0.0