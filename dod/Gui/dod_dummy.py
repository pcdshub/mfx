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
        self.nozzle = 1                 # selected nozzle (1-8)
        self.nozzle_frequency = 30000   # Hz
        self.nozzle_voltage = 80        # V
        self.nozzle_pulse_width = 20    # us
        # --- dispensing state ---
        self.dispensing_state = "Off"   # Off / Trigger / Free / Auto
        # --- probe / sample ---
        self.probe_volume = 0.0         # uL currently held
        self._measured_volume = 0.0     # last measured droplet volume (from volume task)
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
        results = {
            "Activated Nozzles": [self.nozzle],
            "Selected Nozzles": [self.nozzle],
            # packed as [ID, Volt, Pulse, Freq, Volume]
            "ID,Volt,Pulse,Freq,Volume": [
                self.nozzle, self.nozzle_voltage, self.nozzle_pulse_width,
                self.nozzle_frequency, self._measured_volume,
            ],
            "Dispensing": self.dispensing_state,
        }
        return results

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
    def select_nozzle(self, n):
        n = int(n)
        if not (1 <= n <= 8):
            self._rec(f"select_nozzle REJECTED: {n} (valid range is 1-8)")
            return {"ok": False, "reason": f"nozzle {n} out of range (1-8)"}
        self.nozzle = n; self._rec(f"select_nozzle({n})"); return {"ok": True}

    def set_nozzle_frequency(self, freq):
        self.nozzle_frequency = float(freq); self._rec(f"set_nozzle_frequency({freq})"); return True

    def set_nozzle_voltage(self, voltage):
        self.nozzle_voltage = float(voltage); self._rec(f"set_nozzle_voltage({voltage})"); return True

    def set_nozzle_pulse_width(self, width):
        self.nozzle_pulse_width = float(width); self._rec(f"set_nozzle_pulse_width({width})"); return True

    # ------------------------------------------------------------ dispensing
    def dispense_on(self, mode="Trigger"):
        if mode not in ("Trigger", "Free", "Auto"):
            self._rec(f"dispense_on invalid mode: {mode}")
            return {"ok": False, "reason": "invalid mode"}
        self.dispensing_state = mode
        self._rec(f"dispense_on({mode})")
        return {"ok": True}

    def dispense_off(self):
        self.dispensing_state = "Off"
        self._rec("dispense_off()")
        return {"ok": True}

    # ------------------------------------------------------------ probe/sample
    def take_probe(self, volume):
        self.probe_volume = float(volume)
        self._rec(f"take_probe({volume} uL)")
        return {"ok": True}

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

    def measure_volume(self):
        """
        Simulate running the droplet-volume measurement task.
        On the REAL robot you'd instead run the actual volume task (name TBC with
        Sebastian -- likely AutoDropDetectionDropVolume / AutoDropDetection_Dropvol)
        and then read get_nozzle_status. Here we just simulate a value so the
        routine flow is identical.
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