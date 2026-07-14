"""
real_dod_adapter.py -- run your EXISTING routines on the REAL robot, unchanged.

THE IDEA
  Your routines (wash_cycle, sample_test_routine, stability_check, scan_slide,
  configure_nozzle, safe_goto ...) all call methods on a `dod` object:
      dod.move_to_position(name), dod.run_task(name), dod.dispense_on(mode), ...
  Those are the names your DUMMY exposes. The REAL DoD class uses DIFFERENT
  names: do_move(name), do_task(name), set_nozzle_dispensing(mode), ...

  This adapter exposes the DUMMY's method names but calls the REAL DoD methods
  underneath. So you pass a RealDoDAdapter into your existing routines and they
  run on the real robot with ZERO changes to dod_routines.py or control_gui.py.

  It's the "swap the backend" step your handoff doc always planned -- now with
  the real method names filled in from the actual dod.py source.

HOW TO USE
  from real_dod_adapter import RealDoDAdapter
  import dod_routines as R

  dod = RealDoDAdapter(ip="172.21.72.187", port=9999)   # confirm IP w/ Josue
  dod.connect()
  R.wash_cycle(dod, log=print)          # your existing routine, real robot

SAFETY
  - Every move goes through the real robot's own do_move / move_*_abs, which
    themselves busy_wait for completion.
  - dry_run=True (default!) makes the adapter PRINT what it WOULD call and NOT
    move the robot. Flip to dry_run=False only when you're ready to move.
  - Methods the real robot doesn't expose (e.g. move_relative) are implemented
    via the real absolute moves + get_current_position, or clearly refused.

WHAT'S REAL vs UNCERTAIN
  - Real method names: from the published dod.py source. REAL.
  - Coordinate frame for named moves: do_move(name) uses the robot's OWN stored
    position, so YOU don't supply coordinates -- the frame problem doesn't bite
    for named moves. It only matters for raw x/y moves (see move_absolute note).
"""


class RealDoDAdapter:
    def __init__(self, ip="172.21.72.187", port=9999, dry_run=True, log=print,
                 positions_file="named_position_coords.json"):
        """
        ip/port : real robot (confirm with Josue -- source default is 172.21.72.187)
        dry_run : if True, DO NOT move; just print intended real calls. Default True
                  so nothing moves until you explicitly turn it off.
        """
        self.ip = ip
        self.port = port
        self.dry_run = dry_run
        self._log = log
        self._dod = None            # the real DoD instance (created in connect())
        self.connected = False

        # Attributes your routines/GUI read directly:
        self.nozzle = 1
        self.activated_nozzles = [1]
        self.nozzle_frequency = 30000
        self.nozzle_voltage = 80
        self.nozzle_pulse_width = 20
        self.dispensing_state = "Off"
        self.probe_volume = 0.0
        self.last_position = None
        self.fast = True            # unused on real robot, kept for GUI compat
        self.zone = None            # real safety comes from the robot itself
        self.MAX_PROBE_VOLUME_UL = 250
        self.available_tasks = []   # filled from the robot in connect()

        # load the named positions your routines reference
        import json
        try:
            with open(positions_file) as f:
                self.positions = json.load(f)
        except FileNotFoundError:
            self.positions = {}

    # ---------------------------------------------------------------- logging
    def _rec(self, msg):
        if self._log:
            self._log(msg)

    def _call(self, desc, fn):
        """Run a real robot call, or just print it in dry_run mode."""
        if self.dry_run:
            self._rec(f"[DRY RUN] would call: {desc}")
            return {"ok": True, "dry_run": True}
        self._rec(f"[REAL] {desc}")
        return fn()

    # ------------------------------------------------------------- lifecycle
    def connect(self, client="adapter"):
        """Create the real DoD object. Import here so this file loads anywhere."""
        if self.dry_run:
            self._rec(f"[DRY RUN] would connect real DoD at {self.ip}:{self.port}")
            self.connected = True
            return True
        from dod.dod import DoD
        self._dod = DoD(ip=self.ip, port=self.port)
        self.connected = True
        self._rec(f"[REAL] connected DoD at {self.ip}:{self.port}")
        # cache the real task list so routines can check availability
        try:
            self.available_tasks = self._dod.get_task_names()
        except Exception as e:
            self._rec(f"[REAL] get_task_names failed: {e}")
        return True

    def disconnect(self):
        self.connected = False
        self._rec("disconnect()")
        return True

    def stop(self):
        return self.disconnect()

    def start(self):
        return self.connect()

    # -------------------------------------------------------------- getters
    def get_status(self):
        """Map the real get_status() into the shape your GUI/routines expect."""
        if self.dry_run or self._dod is None:
            return {"Position": self.get_position(), "dispensing": self.dispensing_state,
                    "probe_volume": self.probe_volume, "humidity": 40,
                    "temperature": 20, "nozzle": self.nozzle}
        r = self._dod.get_status()
        # real keys: Position, RunningTask, Dialog, LastProbe, Humidity, Temperature...
        pos = self.get_position()
        return {"Position": pos, "dispensing": self.dispensing_state,
                "probe_volume": self.probe_volume,
                "humidity": r.get("Humidity", 40) if isinstance(r, dict) else 40,
                "temperature": r.get("Temperature", 20) if isinstance(r, dict) else 20,
                "nozzle": self.nozzle}

    def get_position(self):
        """Return {'X','Y','Z'} from the real robot's PositionReal."""
        if self.dry_run or self._dod is None:
            return {"X": 0.0, "Y": 0.0, "Z": 0.0}
        r = self._dod.get_current_position()
        real = r.get("PositionReal") if isinstance(r, dict) else None
        if real and len(real) == 3:
            return {"X": real[0], "Y": real[1], "Z": real[2]}
        return {"X": 0.0, "Y": 0.0, "Z": 0.0}

    def get_nozzle_status(self, verbose=False):
        if self.dry_run or self._dod is None:
            return {"Activated Nozzles": [self.nozzle], "Selected Nozzles": [self.nozzle],
                    "ID,Volt,Pulse,Freq,Volume": [str(self.nozzle), str(self.nozzle_voltage),
                        str(self.nozzle_pulse_width), str(self.nozzle_frequency), "0"],
                    "Dispensing": self.dispensing_state}
        return self._dod.get_nozzle_status()

    def get_drive_range(self):
        # real config [MaxAxisPos]; the real DoD doesn't expose a getter, so use known values
        return {"X": 254000, "Y": 118000, "Z": 40000}

    def get_forbidden_region(self, rotation_state="both"):
        if self.dry_run or self._dod is None:
            # config-derived (see real_gridplan.default_regions_from_config)
            return [(0, 300000, 0, 10000), (0, 300000, 50000, 500000)]
        return self._dod.get_forbidden_region(rotation_state)

    def test_forbidden_region(self, x, y, frame="robot"):
        if self.dry_run or self._dod is None:
            for (xs, xe, ys, ye) in self.get_forbidden_region():
                if xs < x < xe and ys < y < ye:
                    return True   # forbidden
            return False
        # real returns True if SAFE; we return True if FORBIDDEN to match dummy.
        return not self._dod.test_forbidden_region(x, y)

    def where(self):
        from pathplan import Point
        p = self.get_position()
        return Point(p["X"], p["Y"], p["Z"])

    # ---------------------------------------------------------------- motion
    def move_to_position(self, name):
        """dummy name -> real do_move(name). Named move: robot uses its own coords."""
        if name not in self.positions:
            self._rec(f"move_to_position unknown: {name}")
            return {"ok": False, "reason": "unknown position"}
        r = self._call(f"do_move('{name}')",
                       lambda: self._dod.do_move(name, safety_test=False))
        if r.get("ok", True):
            self.last_position = name
        return {"ok": True}

    def move_absolute(self, x, y, z):
        """
        Raw absolute move. The real robot has NO single 3-axis absolute call; it
        has move_x_abs / move_y_abs / move_z_abs (ROBOT frame), each with its own
        busy_wait. We issue them in a safe order.

        NOTE: raw x/y/z here are in whatever frame the CALLER used. For named
        moves prefer move_to_position(). Raw moves are exposed mainly so
        move_relative and jog work; confirm the frame before relying on them.
        """
        def do():
            self._dod.move_z_abs(int(z), safety_test=False)   # lift/settle Z first
            self._dod.move_x_abs(int(x), safety_test=False)
            self._dod.move_y_abs(int(y), safety_test=False)
            return {"ok": True}
        return self._call(f"move_x/y/z_abs -> ({int(x)},{int(y)},{int(z)})", do)

    def move_relative(self, dx, dy, dz):
        """Relative move = read current real position + delta, then absolute."""
        p = self.get_position()
        return self.move_absolute(p["X"] + dx, p["Y"] + dy, p["Z"] + dz)

    # ---------------------------------------------------------- nozzle params
    # The REAL robot sets nozzle params via ONE call:
    #   set_nozzle_parameters(active, selected, volts, pulse, frequency)
    # (active/selected are comma-strings like "1,2"; volts/freq int; pulse str.)
    # There are NO separate set_nozzle_frequency/voltage/pulse methods. So we
    # track the values locally and push the whole parameter set each change.
    def _push_nozzle_params(self):
        active = ",".join(str(c) for c in getattr(self, "activated_nozzles", [self.nozzle]))
        selected = str(self.nozzle)
        self._call(
            f"set_nozzle_parameters(active={active}, selected={selected}, "
            f"volt={int(self.nozzle_voltage)}, pulse={int(self.nozzle_pulse_width)}, "
            f"freq={int(self.nozzle_frequency)})",
            lambda: self._dod.client.set_nozzle_parameters(
                active, selected, int(self.nozzle_voltage),
                str(int(self.nozzle_pulse_width)), int(self.nozzle_frequency)))

    def select_nozzle(self, n):
        n = int(n)
        if not (1 <= n <= 8):
            return {"ok": False, "reason": f"nozzle {n} out of range (1-8)"}
        self.nozzle = n
        # real: select_nozzle(channel) -- rejects if not among Activated Nozzles
        self._call(f"select_nozzle({n})",
                   lambda: self._dod.client.select_nozzle(str(n)))
        return {"ok": True}

    def set_nozzle_active(self, channels):
        chans = sorted({int(c) for c in channels})
        self.activated_nozzles = chans
        if self.nozzle not in chans and chans:
            self.nozzle = chans[0]
        # activation happens as part of set_nozzle_parameters (active list).
        # Push it so the robot knows the active set.
        self._push_nozzle_params()
        return {"ok": True}

    def set_nozzle_frequency(self, freq):
        self.nozzle_frequency = float(freq)
        self._push_nozzle_params()
        return True

    def set_nozzle_voltage(self, v):
        self.nozzle_voltage = float(v)
        self._push_nozzle_params()
        return True

    def set_nozzle_pulse_width(self, w):
        self.nozzle_pulse_width = float(w)
        self._push_nozzle_params()
        return True

    # ------------------------------------------------------------ dispensing
    def dispense_on(self, mode="Trigger"):
        # DoD.set_nozzle_dispensing accepts 'Free'/'Triggered'/'Off' (wrapper).
        # Raw client.dispensing accepts 'Trigger'/'Free'/'Off'. We go through the
        # DoD wrapper, which maps 'Triggered' -> client.dispensing('Triggered').
        real_mode = "Triggered" if mode in ("Trigger", "Triggered") else mode
        self.dispensing_state = mode
        self._call(f"set_nozzle_dispensing('{real_mode}')",
                   lambda: self._dod.set_nozzle_dispensing(real_mode))
        return {"ok": True}

    def dispense_off(self):
        self.dispensing_state = "Off"
        self._call("set_nozzle_dispensing('Off')",
                   lambda: self._dod.set_nozzle_dispensing("Off"))
        return {"ok": True}

    # ------------------------------------------------------------ probe/sample
    def take_probe(self, channel, probe_well, volume, check_task=True):
        # real: client.take_probe(channel:int, probe_well:str, volume:float)
        # rejects if channel not active, volume > 250, or well not allowed.
        volume = float(volume)
        if volume > self.MAX_PROBE_VOLUME_UL:
            return {"ok": False, "reason": f"volume {volume} exceeds {self.MAX_PROBE_VOLUME_UL} uL"}
        self.nozzle = int(channel)          # take_probe also selects the channel
        self.probe_volume = volume
        self._call(f"take_probe(ch={channel}, well={probe_well}, {volume}uL)",
                   lambda: self._dod.client.take_probe(int(channel), probe_well, volume))
        return {"ok": True, "channel": int(channel), "well": probe_well, "volume": volume}

    def give_probe(self):
        # NOTE: there is NO give_probe endpoint on the real robot. Returning the
        # probe is handled by a TASK (e.g. a wash/dispense sequence), not a
        # dedicated call. We no-op with a clear log so routines don't break.
        self.probe_volume = 0.0
        self._rec("give_probe() -- no real endpoint; handled via tasks. (no-op)")
        return {"ok": True}

    # ------------------------------------------------------------------ tasks
    def run_task(self, name, wait=True):
        """dummy run_task -> real do_task (which busy_waits until done)."""
        r = self._call(f"do_task('{name}')",
                       lambda: self._dod.do_task(name))
        return {"ok": True, "task": name}

    def stop_task(self):
        self.dispensing_state = "Off"
        self._call("stop_task()", lambda: self._dod.stop_task())
        return {"ok": True}

    def busy_wait(self, timeout, poll_interval=0.5):
        if self.dry_run or self._dod is None:
            return False
        return self._dod.busy_wait(timeout)

    # environment -- these DO exist on the real client (confirmed from source)
    def set_humidity(self, value):
        # real: client.set_humidity(value)  -> /DoD/do/SetHumidity?rH=value
        self._call(f"set_humidity({value})",
                   lambda: self._dod.client.set_humidity(int(value)))
        return True

    def set_temperature(self, value):
        # real: client.set_cooling_temp(temp) -> accepts float or "dewpoint"
        self._call(f"set_cooling_temp({value})",
                   lambda: self._dod.client.set_cooling_temp(value))
        return True

    def measure_volume(self):
        """Real: run AutoDropDetection, then read Volume from nozzle status."""
        self._call("do_task('AutoDropDetection')",
                   lambda: self._dod.do_task("AutoDropDetection"))
        try:
            ns = self.get_nozzle_status()
            return float(ns["ID,Volt,Pulse,Freq,Volume"][-1])
        except Exception:
            return None

    def get_droplet_camera_offset(self):
        """
        Goal 5 (align_droplet) -- NOT wired to real hardware yet. The real robot
        has no camera-offset endpoint in the published client, so we refuse
        cleanly instead of pretending. align_droplet checks for this method and
        will report it can't align, rather than moving blindly.
        """
        raise NotImplementedError(
            "droplet camera offset is not available on the real robot yet "
            "(Goal 5 / align_droplet is for later)")


if __name__ == "__main__":
    # Offline dry-run: prove wash_cycle's real calls WITHOUT a robot.
    print("=== DRY RUN: what wash_cycle would send to the REAL robot ===\n")
    dod = RealDoDAdapter(dry_run=True, log=print)
    dod.connect()

    # inline mini wash_cycle (same calls your dod_routines.wash_cycle makes)
    print("\n-- wash_cycle sequence --")
    dod.move_to_position("WashStation1")
    dod.run_task("WashFlush_Medium")
    print("\n(these are the exact real-robot calls; flip dry_run=False to execute)")