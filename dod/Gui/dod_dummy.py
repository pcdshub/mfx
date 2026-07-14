"""
dod_dummy.py -- an offline dummy that mirrors the REAL DoD class interface.

The real DoD class (from the robot codebase) exposes methods like move_absolute,
move_to_position, take_probe(volume), set_nozzle_frequency/voltage/pulse_width,
select_nozzle, dispense_on(mode)/dispense_off, run_task, set_humidity, etc.

This dummy implements the SAME method names and parameters, tracks state, and
enforces collision-avoidance on moves via pathplan -- so routines written against
this dummy will work against the real DoD class with minimal change (swap the
object). Every real parameter (frequency, voltage, pulse width, probe volume,
dispense mode, nozzle) is a real attribute you can set and read.

Values on the dummy are simulated; on the real robot they come from hardware.
"""

import json
import time
from pathplan import Point, Zone, is_move_safe, plan_detour
from gridplan import GridPlanner, MotionVector, braking_distance


class DoDDummy:
    def __init__(self, zone=None, positions_file="named_position_coords.json",
                 fast=True):
        # fast=True  -> tasks return almost immediately (good for iterating/testing)
        # fast=False -> tasks actually take their modeled duration, so routines
        #               pace the way they would on the real robot.
        self.fast = fast
        # --- motion state (um) ---
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0
        # --- nozzle / droplet parameters (the REAL knobs) ---
        # A nozzle must be ACTIVATED before it can be SELECTED. The real client
        # rejects select_nozzle() for any channel not in 'Activated Nozzles'.
        self.activated_nozzles = [1]    # armed channels (subset of 1-8)
        self.nozzle = 1                 # selected nozzle (must be in activated_nozzles)
        self.nozzle_frequency = 30000   # Hz
        self.nozzle_voltage = 80        # V
        self.nozzle_pulse_width = 20    # us
        # --- dispensing state ---
        self.dispensing_state = "Off"   # Off / Trigger / Free  (real client: no 'Auto')
        # --- probe / sample ---
        self.probe_volume = 0.0         # uL currently held
        self.probe_well = None          # last well aspirated from, e.g. 'A1'
        self._measured_volume = 0.0     # last measured droplet volume (from volume task)
        # --- camera / alignment (Goal 5) ---
        # The droplet appears at some (px, py) offset in microns from the camera
        # crosshair. Nonzero by default so an alignment routine has work to do.
        # On the real robot this comes from the drop-detection camera; here it's
        # simulated and shrinks as the nozzle moves toward alignment.
        self._cam_dx = 320.0   # um offset of droplet from crosshair, X
        self._cam_dy = -210.0  # um offset of droplet from crosshair, Y
        # Tasks the robot knows about. take_probe silently does NOTHING on the real
        # robot if 'ProbeUptake' is absent -- so we model its presence explicitly.
        self.available_tasks = [
            "ProbeUptake", "AutoDropDetection", "AutoDropDetectionDropVolume",
            "WashFlush_Medium", "WashFlush_Light_Narrow", "WashFlush_Strong_Narrow",
            "MorningWashProcedure", "DrySystem", "SpotProbeRun", "ScanSpotArea",
        ]
        # --- environment ---
        self.humidity = 40              # %
        self.temperature = 20           # C
        # --- misc ---
        self.last_task = None
        self.last_position = None
        self.connected = False
        self.zone = zone
        # --- grid-based collision avoidance (Sebastian's grid approach) ---
        # The grid classifies the whole workspace into SAFE/UNSAFE cells and
        # plans waypoint routes through safe cells. speed/decel are PLACEHOLDERS
        # until we get real axis values -- they set the velocity-dependent
        # braking margin added around the zone.
        self.grid = GridPlanner(
            workspace={"X": (0, 254000), "Y": (0, 118000), "Z": (0, 40000)},
            zone=zone, cell_size=5000, speed=10000, decel=10000,
        ) if zone is not None else None
        self.use_grid = True   # False = fall back to the old plan_detour path
        # --- forbidden region (the robot's OWN exclusion system) ---
        # These are the REAL values the DoD class uses, in HUTCH coordinates (um):
        #   y_min=10000, y_safety=50000, y_max=50000
        # The robot forbids the region y_min < y < y_max (with y_safety as the
        # height the nozzle must clear to). NOTE the coordinate frames differ:
        #   hutch (x, y, z) = robot (x, -z, y)
        # so a robot-frame move must be converted to hutch to test it.
        self.forbidden_region = {"y_min": 10000, "y_safety": 50000, "y_max": 50000}
        self.log = []
        try:
            with open(positions_file) as f:
                self.positions = json.load(f)
        except FileNotFoundError:
            self.positions = {}

    # ---------------------------------------------------------------- logging
    def _rec(self, msg):
        self.log.append(msg)

    # ------------------------------------------------------------- lifecycle
    def connect(self, client="dummy"):
        self.connected = True
        self._rec(f"connect({client})")
        return True

    def disconnect(self):
        self.connected = False
        self._rec("disconnect()")
        return True

    # -------------------------------------------------------------- getters
    def get_position(self):
        return {"X": self.x, "Y": self.y, "Z": self.z}

    def get_nozzle_status(self, verbose=False):
        """
        Return current nozzle parameters and state.
        Matches the REAL DoD.get_nozzle_status() structure (per Sebastian):
        keys 'Activated Nozzles', 'Selected Nozzles', 'ID,Volt,Pulse,Freq,Volume',
        and 'Dispensing'. The measured droplet Volume is the last field of the
        'ID,Volt,Pulse,Freq,Volume' entry.
        On the dummy the Volume is simulated; on the real robot it's the measured
        value (Sebastian noted: don't fully rely on it -- sanity-check it).
        """
        # NOTE: the real endpoint returns these as an ARRAY OF STRINGS (JSON),
        # so callers must cast. read_measured_volume() does float(...) on the last field.
        results = {
            "Activated Nozzles": list(self.activated_nozzles),
            "Selected Nozzles": [self.nozzle],
            # packed as [ID, Volt, Pulse, Freq, Volume] -- strings, like the real robot
            "ID,Volt,Pulse,Freq,Volume": [
                str(self.nozzle), str(self.nozzle_voltage), str(self.nozzle_pulse_width),
                str(self.nozzle_frequency), str(self._measured_volume),
            ],
            "Dispensing": self.dispensing_state,
        }
        return results

    def get_drive_range(self):
        """Max range of each axis in um. Real robot reads this live; we know the values."""
        return {"X": 254000, "Y": 118000, "Z": 40000}

    def get_status(self):
        return {"Position": self.get_position(),
                "dispensing": self.dispensing_state,
                "probe_volume": self.probe_volume,
                "humidity": self.humidity, "temperature": self.temperature,
                "nozzle": self.nozzle}

    # ------------------------------------------------ forbidden region (real API)
    @staticmethod
    def robot_to_hutch(x, y, z):
        """Convert robot-frame (x, y, z) to hutch-frame. hutch = (x, -z, y)."""
        return (x, -z, y)

    @staticmethod
    def hutch_to_robot(x, y, z):
        """Convert hutch-frame (x, y, z) to robot-frame. robot = (x, z, -y)."""
        return (x, z, -y)

    def get_forbidden_region(self):
        """Return the robot's exclusion region (hutch coords, um). Mirrors DoD."""
        return dict(self.forbidden_region)

    def set_forbidden_region(self, y_min=None, y_safety=None, y_max=None):
        """Update the exclusion region (hutch coords). Mirrors DoD.set_forbidden_region."""
        if y_min is not None:
            self.forbidden_region["y_min"] = float(y_min)
        if y_safety is not None:
            self.forbidden_region["y_safety"] = float(y_safety)
        if y_max is not None:
            self.forbidden_region["y_max"] = float(y_max)
        self._rec(f"set_forbidden_region({self.forbidden_region})")
        return {"ok": True, "region": dict(self.forbidden_region)}

    def test_forbidden_region(self, x, y, frame="robot"):
        """
        Test whether a point is inside the forbidden region.
        Mirrors DoD.test_forbidden_region(x, y). Coordinates default to ROBOT frame
        (what move commands use); we convert to hutch to test, since the region is
        defined in hutch Y. Returns True if the point is FORBIDDEN.
        """
        if frame == "robot":
            # robot (x, y, z=current) -> hutch; hutch_y = -robot_z. We test in the
            # X-Y plane the real endpoint uses, so use the current Z for the convert.
            _, hutch_y, _ = self.robot_to_hutch(x, y, self.z)
        else:
            hutch_y = y
        fr = self.forbidden_region
        forbidden = fr["y_min"] < hutch_y < fr["y_max"]
        self._rec(f"test_forbidden_region(x={x}, y={y}, frame={frame}) -> {forbidden}")
        return forbidden

    # ---------------------------------------------------------------- motion
    def _raw_to(self, x, y, z):
        self.z = float(z); self.x = float(x); self.y = float(y)

    def move_absolute(self, x, y, z):
        """
        Move to absolute X/Y/Z (um), collision-checked.

        Grid mode (use_grid=True, the default):
          1. is the straight line safe? (every crossed grid cell is SAFE)
          2. if not: which cells does it cross / violate? (recorded in the log)
          3. plan a route through SAFE cells and FOLLOW those grid waypoints.
        Legacy mode (use_grid=False): the original pathplan lift/traverse/descend.
        Both modes refuse a target that sits inside the zone itself.
        """
        target = Point(float(x), float(y), float(z))
        if self.zone is not None and self.zone.contains(target):
            self._rec(f"move_absolute REFUSED (in zone): {target.as_tuple()}")
            return {"ok": False, "reason": "target in keep-out zone"}
        start = Point(self.x, self.y, self.z)

        # ---------- grid-based path (new) ----------
        if self.use_grid and self.grid is not None:
            report = self.grid.report_move(start, target)
            if report["safe_straight"]:
                self._raw_to(x, y, z)
                self._rec(f"move_absolute -> {target.as_tuple()} "
                          f"(grid: straight, {len(report['cells_crossed'])} cells)")
                return {"ok": True, "detour": False, "grid": report}
            self._rec(f"move_absolute: straight path crosses "
                      f"{len(report['unsafe_cells'])} UNSAFE cells "
                      f"{report['unsafe_cells'][:5]}...")
            if report["grid_path"] is None:
                self._rec(f"move_absolute REFUSED (no grid path): {target.as_tuple()}")
                return {"ok": False, "reason": "no safe path through grid"}
            # follow the grid: step through the waypoints one by one
            for wp in report["grid_path"][1:]:
                self._raw_to(*wp)
            self._rec(f"move_absolute -> {target.as_tuple()} via grid "
                      f"({report['n_waypoints']} waypoints)")
            return {"ok": True, "detour": True, "grid": report,
                    "path": report["grid_path"]}

        # ---------- legacy pathplan detour (unchanged) ----------
        if self.zone is None or is_move_safe(start, target, self.zone):
            self._raw_to(x, y, z)
            self._rec(f"move_absolute -> {target.as_tuple()}")
            return {"ok": True, "detour": False}
        path = plan_detour(start, target, self.zone)
        if path is None:
            self._rec(f"move_absolute REFUSED (no path): {target.as_tuple()}")
            return {"ok": False, "reason": "no safe path"}
        for wp in path[1:]:
            self._raw_to(wp.x, wp.y, wp.z)
        self._rec(f"move_absolute -> {target.as_tuple()} via detour ({len(path)-1} legs)")
        return {"ok": True, "detour": True}

    def move_relative(self, dx, dy, dz):
        r = self.move_absolute(self.x + dx, self.y + dy, self.z + dz)
        # Simulated camera: moving the nozzle by (dx, dy) shifts the droplet on
        # the camera by the SAME sign, so a correction toward the crosshair (moving
        # by -offset) reduces the offset. Real cameras have a calibration factor
        # (um per pixel) and possibly a sign flip -- confirm on hardware.
        if r.get("ok"):
            self._cam_dx += dx
            self._cam_dy += dy
        return r

    def get_droplet_camera_offset(self):
        """
        Return the droplet's offset (dx, dy) in um from the camera crosshair.
        On the real robot this comes from the drop-detection camera; here it is
        simulated. (0, 0) means the droplet is centered on the crosshair.
        """
        return {"dx": self._cam_dx, "dy": self._cam_dy}

    def move_to_position(self, name):
        """Move to a named position (looked up in the coordinate table)."""
        if name not in self.positions:
            self._rec(f"move_to_position unknown: {name}")
            return {"ok": False, "reason": "unknown position"}
        c = self.positions[name]
        r = self.move_absolute(c["X"], c["Y"], c["Z"])
        if r.get("ok"):
            self.last_position = name
        return r

    # ---------------------------------------------------------- nozzle params
    def set_nozzle_active(self, channels):
        """
        Arm a set of nozzle channels. Only ACTIVATED nozzles can be selected.
        Mirrors the real DoD.set_nozzle_active([1, 2, 3]).
        """
        chans = sorted({int(c) for c in channels})
        bad = [c for c in chans if not (1 <= c <= 8)]
        if bad:
            self._rec(f"set_nozzle_active REJECTED: {bad} out of range (1-8)")
            return {"ok": False, "reason": f"channels {bad} out of range (1-8)"}
        self.activated_nozzles = chans
        # if the currently selected nozzle is no longer armed, fall back to the first
        if self.nozzle not in chans and chans:
            self.nozzle = chans[0]
        self._rec(f"set_nozzle_active({chans})")
        return {"ok": True}

    def select_nozzle(self, n):
        """
        Select the nozzle that fires when dispensing is triggered.
        The real client REJECTS any channel not in 'Activated Nozzles' -- being in
        1-8 is not sufficient. Arm it first with set_nozzle_active().
        """
        n = int(n)
        if not (1 <= n <= 8):
            self._rec(f"select_nozzle REJECTED: {n} (valid range is 1-8)")
            return {"ok": False, "reason": f"nozzle {n} out of range (1-8)"}
        if n not in self.activated_nozzles:
            self._rec(f"select_nozzle REJECTED: {n} not in activated {self.activated_nozzles}")
            return {"ok": False,
                    "reason": f"nozzle {n} is not activated (armed: {self.activated_nozzles}); "
                              f"call set_nozzle_active() first"}
        self.nozzle = n; self._rec(f"select_nozzle({n})"); return {"ok": True}

    def set_nozzle_frequency(self, freq):
        self.nozzle_frequency = float(freq); self._rec(f"set_nozzle_frequency({freq})"); return True

    def set_nozzle_voltage(self, voltage):
        self.nozzle_voltage = float(voltage); self._rec(f"set_nozzle_voltage({voltage})"); return True

    def set_nozzle_pulse_width(self, width):
        self.nozzle_pulse_width = float(width); self._rec(f"set_nozzle_pulse_width({width})"); return True

    # ------------------------------------------------------------ dispensing
    def dispense_on(self, mode="Trigger"):
        # Real client accepts only 'Trigger', 'Free', 'Off'. There is no 'Auto'.
        if mode not in ("Trigger", "Free"):
            self._rec(f"dispense_on REJECTED: invalid mode {mode!r} (use 'Trigger' or 'Free')")
            return {"ok": False, "reason": f"invalid mode {mode!r}; valid: Trigger, Free"}
        self.dispensing_state = mode
        self._rec(f"dispense_on({mode})")
        return {"ok": True}

    def dispense_off(self):
        self.dispensing_state = "Off"
        self._rec("dispense_off()")
        return {"ok": True}

    # ------------------------------------------------------------ probe/sample
    MAX_PROBE_VOLUME_UL = 250

    def take_probe(self, channel, probe_well, volume, check_task=True):
        """
        Aspirate `volume` uL from `probe_well` (e.g. 'A1') using nozzle `channel`.
        Mirrors the real signature: take_probe(channel, probe_well, volume).

        Real-robot behaviour modeled here:
          - rejects if volume > 250 uL
          - rejects if channel is not among the ACTIVATED nozzles
          - if the 'ProbeUptake' task is missing, the real robot SILENTLY DOES
            NOTHING (no reject, no error). We make that failure explicit.
          - selects `channel` as a side effect (as the real endpoint does)
        """
        volume = float(volume)
        if volume > self.MAX_PROBE_VOLUME_UL:
            self._rec(f"take_probe REJECTED: {volume} uL > {self.MAX_PROBE_VOLUME_UL} uL max")
            return {"ok": False, "reason": f"volume {volume} exceeds {self.MAX_PROBE_VOLUME_UL} uL max"}
        channel = int(channel)
        if channel not in self.activated_nozzles:
            self._rec(f"take_probe REJECTED: channel {channel} not activated {self.activated_nozzles}")
            return {"ok": False, "reason": f"channel {channel} is not activated"}
        if check_task and "ProbeUptake" not in self.available_tasks:
            self._rec("take_probe FAILED: task 'ProbeUptake' missing (real robot would do nothing silently)")
            return {"ok": False, "reason": "task 'ProbeUptake' not present on robot"}

        # side effect: TakeProbe also selects the channel
        self.nozzle = channel
        self.probe_volume = volume
        self.probe_well = probe_well
        self._rec(f"take_probe(ch={channel}, well={probe_well}, {volume} uL)")
        # real robot: uptake takes time -- ~1 s per uL, 30 s floor
        self.busy_wait(max(30, int(volume)))
        return {"ok": True, "channel": channel, "well": probe_well, "volume": volume}

    def give_probe(self):
        self._rec(f"give_probe() (was {self.probe_volume} uL)")
        self.probe_volume = 0.0
        return {"ok": True}

    # ------------------------------------------------------------- environment
    def set_humidity(self, value):
        self.humidity = float(value); self._rec(f"set_humidity({value})"); return True

    def set_temperature(self, value):
        self.temperature = float(value); self._rec(f"set_temperature({value})"); return True

    # ------------------------------------------------------------------ tasks
    # Approximate real durations (seconds) for tasks, so timing is modeled even
    # on the dummy. On the real robot, busy_wait polls get_status until done;
    # here we just sleep the modeled duration. Adjust with real values later.
    TASK_DURATIONS = {
        "WashFlush_Medium": 8.0, "WashFlush_Light_Narrow": 5.0,
        "WashFlush_Strong_Narrow": 10.0, "MorningWashProcedure": 30.0,
        "ProbeUptake": 15.0, "DrySystem": 20.0,
    }

    def run_task(self, name, wait=True):
        """
        Start a task. On the real robot this returns quickly but the task keeps
        running -- so we busy_wait for completion when wait=True (the safe default).
        On the dummy we sleep the modeled duration so timing behaves realistically.
        """
        self.last_task = name
        self._rec(f"run_task({name})")
        duration = self.TASK_DURATIONS.get(name, 2.0)
        if wait:
            self.busy_wait(duration)
        return {"ok": True, "task": name, "duration": duration}

    def busy_wait(self, timeout, poll_interval=0.5):
        """
        Model waiting for the robot to finish being busy. On the real robot this
        polls get_status until Status != 'Busy'. Same signature, so routines
        written against this dummy work unchanged on real hardware.

        fast=True  -> sleep only a token amount (keeps testing snappy)
        fast=False -> sleep the full modeled duration, so a routine paces the way
                      it would on the robot (e.g. an 8 s wash really takes 8 s)
        """
        import time as _t
        self._rec(f"busy_wait({timeout}s, fast={self.fast})")
        _t.sleep(0.05 if self.fast else timeout)
        return False  # False = finished within timeout (real: True if timed out)

    def auto_drop(self):
        """
        Run the drop-detection task. The published client docs name this task
        'AutoDropDetection' and note that execute_task('AutoDropDetection') is
        equivalent. Populates the Volume field read back via get_nozzle_status().
        """
        return self.run_task("AutoDropDetection")

    def measure_volume(self):
        """
        Simulate running the droplet-volume measurement task.
        On the REAL robot: run_task('AutoDropDetection') (or a variant such as
        AutoDropDetectionDropVolume -- confirm which populates Volume), then read
        get_nozzle_status()['ID,Volt,Pulse,Freq,Volume'][-1].
        Sebastian's caveat: don't fully rely on this readback; sanity-check it
        against the drop-detection camera.

        On the dummy the volume is SIMULATED, but responds to voltage and pulse
        width (higher voltage / wider pulse -> larger droplet) so parameter sweeps
        produce a realistic trend instead of flat noise. This is a toy model, NOT
        real physics -- real values come from drop detection on hardware.
        """
        import random
        # baseline ~100, scaled by how far voltage/pulse are from nominal (80 V, 20 us)
        v_factor = self.nozzle_voltage / 80.0
        p_factor = self.nozzle_pulse_width / 20.0
        base = 100.0 * (0.6 * v_factor + 0.4 * p_factor)
        self._measured_volume = round(base + random.gauss(0, 3.0), 2)
        self._rec(f"measure_volume() -> {self._measured_volume}")
        return self._measured_volume

    def stop_task(self):
        self.dispensing_state = "Off"; self._rec("stop_task()"); return {"ok": True}

    # convenience used by the GUI/monitors
    def where(self):
        return Point(self.x, self.y, self.z)

    def start(self):
        self.connect()

    def stop(self):
        self.disconnect()


if __name__ == "__main__":
    from pathplan import Zone
    zone = Zone(100000, 40000, 0, 140000, 70000, 20000, margin=2000)
    d = DoDDummy(zone=zone)
    d.connect()
    print("status:", d.get_status())
    d.select_nozzle(4)
    d.set_nozzle_frequency(33000)
    d.set_nozzle_voltage(90)
    d.take_probe(40)
    print("nozzle:", d.get_nozzle_status())
    print("move to IP:", d.move_to_position("InteractionPoint"))
    d.dispense_on("Trigger")
    print("status after dispense:", d.get_status())
    d.dispense_off()