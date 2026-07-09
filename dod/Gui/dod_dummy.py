"""
dod_dummy.py -- an offline dummy that mirrors the REAL DoD class interface.


This dummy implements the SAME method names and parameters, tracks state, and
enforces collision-avoidance on moves via pathplan -- so routines written against
this dummy will work against the real DoD class with minimal change (swap the
object). Every real parameter (frequency, voltage, pulse width, probe volume,
dispense mode, nozzle) is a real attribute you can set and read.

Values on the dummy are simulated for now; on the real robot they come from hardware.
"""

import json
import time
from pathplan import Point, Zone, is_move_safe, plan_detour


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

    # ---------------------------------------------------------------- motion
    def _raw_to(self, x, y, z):
        self.z = float(z); self.x = float(x); self.y = float(y)

    def move_absolute(self, x, y, z):
        """Move to absolute X/Y/Z (um), collision-checked against the keep-out zone."""
        target = Point(float(x), float(y), float(z))
        if self.zone is not None and self.zone.contains(target):
            self._rec(f"move_absolute REFUSED (in zone): {target.as_tuple()}")
            return {"ok": False, "reason": "target in keep-out zone"}
        start = Point(self.x, self.y, self.z)
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
        return self.move_absolute(self.x + dx, self.y + dy, self.z + dz)

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
        """
        import random
        self._measured_volume = round(random.gauss(100.0, 4.0), 2)
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