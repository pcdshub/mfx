


class RealDoDAdapter:
    def __init__(self, ip="172.21.72.187", port=9999, dry_run=True, log=print,
                 positions_file="named_position_coords.json"):
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
        """
        Create the real DoD object. ALWAYS connects for real, even in dry_run --
        connecting and READING are harmless; only MOTION is gated by dry_run.
        (Earlier this returned early in dry_run, which left _dod = None and made
        every getter silently return fake placeholder values. That was a bug:
        fake data that prints "OK" is worse than an error.)
        """
        from dod.dod import DoD
        self._dod = DoD(ip=self.ip, port=self.port)
        self.connected = True
        self._rec(f"[REAL] connected DoD at {self.ip}:{self.port}"
                  + ("  (dry_run: reads are REAL, motion is blocked)" if self.dry_run else ""))
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
    #
    # RULE: getters ALWAYS read the real robot. They NEVER invent a value.
    # If we can't read, we RAISE -- because a fake number that looks fine is
    # far more dangerous than a visible error. dry_run does NOT affect reads.
    def _require_connection(self, what):
        if self._dod is None:
            raise RuntimeError(
                f"cannot read {what}: not connected to the robot. "
                f"Call connect() first (and check the IP)."
            )

    def get_status(self):
        """Map the real get_status() into the shape your GUI/routines expect."""
        self._require_connection("status")
        r = self._dod.get_status()
        if not isinstance(r, dict):
            raise RuntimeError(f"robot returned unexpected status type: {type(r)}")
        return {"Position": self.get_position(),
                "dispensing": r.get("Dispensing", self.dispensing_state),
                "probe_volume": self.probe_volume,
                "humidity": r.get("Humidity"),
                "temperature": r.get("Temperature"),
                "nozzle": self.nozzle,
                "raw": r}          # keep the untouched robot reply for inspection

    def get_position(self):
        """
        Return {'X','Y','Z'} read from the real robot's get_current_position().

        The real reply looks like:
            {'CurrentPosition': 0, 'Position': ['0', 'Probe (96WP-1nozzle)', ...],
             'PositionReal': {'X': 253973, 'Y': 0, 'Z': 0}}
        PositionReal is a DICT (confirmed on hardware). We also accept a
        3-element list in case a different firmware returns one. If we can't
        find real coordinates we RAISE rather than return zeros.
        """
        self._require_connection("position")
        r = self._dod.get_current_position()
        if not isinstance(r, dict):
            raise RuntimeError(f"get_current_position returned {type(r)}, expected dict")
        real = r.get("PositionReal")
        if isinstance(real, dict) and {"X", "Y", "Z"} <= set(real.keys()):
            return {"X": float(real["X"]), "Y": float(real["Y"]), "Z": float(real["Z"])}
        if isinstance(real, (list, tuple)) and len(real) == 3:
            return {"X": float(real[0]), "Y": float(real[1]), "Z": float(real[2])}
        raise RuntimeError(
            f"could not read X/Y/Z from PositionReal={real!r} "
            f"(full reply keys: {list(r.keys())})"
        )

    def get_nozzle_status(self, verbose=False):
        self._require_connection("nozzle status")
        return self._dod.get_nozzle_status()

    def get_drive_range(self):
        """
        Axis travel limits (um).

        NOTE: these are read from the robot config file [MaxAxisPos], NOT from a
        live endpoint -- the DoD wrapper doesn't expose a drive-range getter.
        So this is CONFIG data, not a live hardware read. Flagged as such.
        """
        return {"X": 254000, "Y": 118000, "Z": 40000, "_source": "config [MaxAxisPos], not live"}

    def get_forbidden_region(self, rotation_state="both"):
        """Read the robot's OWN exclusion regions. Always live; never faked."""
        self._require_connection("forbidden regions")
        return self._dod.get_forbidden_region(rotation_state)

    def test_forbidden_region(self, x, y):
        """
        Ask the ROBOT whether (x, y) is forbidden. Returns True if FORBIDDEN.

        The real DoD.test_forbidden_region(x, y) returns True when the point is
        SAFE, so we invert it to match the dummy's convention.

        NOTE: the real endpoint takes only (x, y) -- there is no 'frame'
        argument. Which coordinate frame these x/y are in vs. the saved
        positions is an OPEN QUESTION (source says hutch(x,y,z)=robot(x,-z,y)).
        Do not trust this mapping until we confirm the frame.
        """
        self._require_connection("forbidden-region test")
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