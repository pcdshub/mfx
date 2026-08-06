"""
control_gui.py -- full DoD robot control panel (dummy), REAL interface.

Uses the real DoD interface (dod_dummy.DoDDummy) and exposes the REAL parameters:
nozzle selection, frequency, voltage, pulse width, probe volume, dispense mode.

Features:
  - color-coded status readouts (green in-bounds / red outside or in keep-out zone)
  - environment + nozzle readouts (humidity, temp, nozzle params)
  - EMERGENCY STOP (stop_task + dispense_off)
  - jog with fine/medium/coarse steps
  - go-to named position (collision-checked)
  - editable PARAMETER fields (nozzle/freq/voltage/pulse/probe volume/mode)
  - automation routines that use those parameters
  - timestamped command log

Run:  uv run control_gui.py
"""

import threading
from datetime import datetime
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

from pathplan import Point, Zone
from dod_dummy import DoDDummy
import dod_routines as R

KEEP_OUT = Zone(100000, 40000, 0, 140000, 70000, 20000, margin=2000)
WORKSPACE = {"X": (0, 254000), "Y": (0, 118000), "Z": (0, 40000)}
STEP_SIZES = {"Fine (100)": 100, "Medium (1000)": 1000, "Coarse (10000)": 10000}


def inside_workspace(x, y, z):
    return (WORKSPACE["X"][0] <= x <= WORKSPACE["X"][1]
            and WORKSPACE["Y"][0] <= y <= WORKSPACE["Y"][1]
            and WORKSPACE["Z"][0] <= z <= WORKSPACE["Z"][1])


def build_robot():
    # fast=False -> routines pace like the real robot (an 8 s wash takes 8 s).
    # Toggle it live from the "Realistic task timing" checkbox.
    d = DoDDummy(zone=KEEP_OUT, fast=False)
    d.connect()
    return d


class ControlGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("DoD Robot Control Panel (real interface, dummy)")
        self.dod = build_robot()
        self.step = tk.IntVar(value=1000)

        # editable parameter vars (REAL parameters)
        self.p_nozzle = tk.IntVar(value=1)
        self.p_freq = tk.IntVar(value=30000)
        self.p_voltage = tk.IntVar(value=80)
        self.p_pulse = tk.IntVar(value=20)
        self.p_probe_vol = tk.IntVar(value=40)
        self.p_mode = tk.StringVar(value="Trigger")
        self.p_samples = tk.IntVar(value=3)
        self.p_shots = tk.IntVar(value=10)

        self._build()
        self._refresh()

    def _build(self):
        pad = {"padx": 5, "pady": 3}

        # status
        rf = ttk.LabelFrame(self.root, text="Status")
        rf.grid(row=0, column=0, columnspan=2, sticky="ew", **pad)
        self.pos_lbl = tk.Label(rf, text="X=? Y=? Z=?", font=("Consolas", 12), width=26)
        self.pos_lbl.grid(row=0, column=0, padx=5, pady=3)
        self.state_lbl = tk.Label(rf, text="—", font=("Consolas", 11, "bold"), width=20)
        self.state_lbl.grid(row=0, column=1, padx=5)
        self.env_lbl = tk.Label(rf, text="", font=("Consolas", 9))
        self.env_lbl.grid(row=1, column=0, columnspan=2, sticky="w", padx=5)

        # emergency stop
        tk.Button(self.root, text="EMERGENCY STOP", bg="#c0392b", fg="white",
                  font=("Arial", 13, "bold"), height=2, command=self.estop
                  ).grid(row=1, column=0, columnspan=2, sticky="ew", **pad)

        # jog
        jf = ttk.LabelFrame(self.root, text="Jog")
        jf.grid(row=2, column=0, sticky="nsew", **pad)
        sf = ttk.Frame(jf); sf.grid(row=0, column=0, columnspan=3)
        for label, val in STEP_SIZES.items():
            ttk.Radiobutton(sf, text=label, variable=self.step, value=val).pack(side="left")
        # custom step: type an exact value and use it
        cf = ttk.Frame(jf); cf.grid(row=4, column=0, columnspan=3, pady=(4, 0))
        ttk.Label(cf, text="Custom step (um):").pack(side="left")
        self.custom_step = tk.IntVar(value=500)
        ttk.Entry(cf, textvariable=self.custom_step, width=8).pack(side="left", padx=3)
        ttk.Button(cf, text="Use", command=self.use_custom_step).pack(side="left")
        for axis, r in (("X", 1), ("Y", 2), ("Z", 3)):
            ttk.Label(jf, text=axis).grid(row=r, column=0, padx=3)
            ttk.Button(jf, text=f"{axis}-", width=4, command=lambda a=axis: self.jog(a, -1)).grid(row=r, column=1)
            ttk.Button(jf, text=f"{axis}+", width=4, command=lambda a=axis: self.jog(a, +1)).grid(row=r, column=2)

        # go-to
        gf = ttk.LabelFrame(self.root, text="Go To")
        gf.grid(row=2, column=1, sticky="nsew", **pad)
        self.target = tk.StringVar(value="InteractionPoint")
        ttk.Combobox(gf, textvariable=self.target, values=list(self.dod.positions.keys()),
                     width=22, state="readonly").grid(row=0, column=0, columnspan=2, padx=3, pady=2)
        ttk.Button(gf, text="Safe Go", command=self.safe_go).grid(row=1, column=0, padx=3, pady=2)
        ttk.Button(gf, text="Dispense ON", command=self.dispense_on).grid(row=2, column=0, pady=2)
        ttk.Button(gf, text="Dispense OFF", command=self.dispense_off).grid(row=2, column=1)

        # REAL parameters
        pf = ttk.LabelFrame(self.root, text="Nozzle / Sample Parameters")
        pf.grid(row=3, column=0, columnspan=2, sticky="ew", **pad)
        fields = [
            ("Nozzle (1-8)", self.p_nozzle), ("Frequency (Hz)", self.p_freq),
            ("Voltage (V)", self.p_voltage), ("Pulse width (us)", self.p_pulse),
            ("Probe volume (uL)", self.p_probe_vol),
        ]
        for i, (label, var) in enumerate(fields):
            ttk.Label(pf, text=label).grid(row=i//3, column=(i%3)*2, sticky="e", padx=3, pady=2)
            ttk.Entry(pf, textvariable=var, width=8).grid(row=i//3, column=(i%3)*2+1, padx=3)
        ttk.Label(pf, text="Dispense mode").grid(row=2, column=0, sticky="e", padx=3)
        ttk.Combobox(pf, textvariable=self.p_mode, values=["Trigger", "Free", "Auto"],
                     width=8, state="readonly").grid(row=2, column=1, padx=3)
        ttk.Button(pf, text="Apply nozzle settings", command=self.apply_nozzle).grid(row=2, column=2, columnspan=2, padx=3)

        # routines with their count params
        rtf = ttk.LabelFrame(self.root, text="Automation Routines")
        rtf.grid(row=4, column=0, columnspan=2, sticky="ew", **pad)
        ttk.Label(rtf, text="samples:").grid(row=0, column=0, sticky="e")
        ttk.Entry(rtf, textvariable=self.p_samples, width=5).grid(row=0, column=1)
        ttk.Button(rtf, text="Sample Test", command=self.run_sample_test).grid(row=0, column=2, padx=3, pady=3)
        ttk.Label(rtf, text="shots:").grid(row=0, column=3, sticky="e")
        ttk.Entry(rtf, textvariable=self.p_shots, width=5).grid(row=0, column=4)
        ttk.Button(rtf, text="Stability Check", command=self.run_stability).grid(row=0, column=5, padx=3)
        ttk.Button(rtf, text="Wash Cycle", command=self.run_wash).grid(row=1, column=2, padx=3, pady=3)
        ttk.Button(rtf, text="Scan Slide", command=self.run_scan).grid(row=1, column=5, padx=3)
        ttk.Button(rtf, text="Safety Check", command=self.run_safety).grid(row=1, column=0, columnspan=2, padx=3, pady=3)
        # sweep + align (Goal 5)
        ttk.Label(rtf, text="sweep:").grid(row=2, column=0, sticky="e")
        self.p_sweep = tk.StringVar(value="voltage")
        ttk.Combobox(rtf, textvariable=self.p_sweep, values=["voltage", "frequency", "pulse_width"],
                     width=10, state="readonly").grid(row=2, column=1)
        ttk.Button(rtf, text="Parameter Sweep", command=self.run_sweep).grid(row=2, column=2, padx=3, pady=3)
        ttk.Button(rtf, text="Align Droplet", command=self.run_align).grid(row=2, column=5, padx=3)
        # operational routines (all grounded in real tasks / real APIs)
        ttk.Button(rtf, text="Startup", command=self.run_startup).grid(row=3, column=0, padx=3, pady=3)
        ttk.Button(rtf, text="Shutdown", command=self.run_shutdown).grid(row=3, column=1, padx=3)
        ttk.Button(rtf, text="Nozzle Health", command=self.run_nozzle_health).grid(row=3, column=2, padx=3)
        ttk.Button(rtf, text="Region Check", command=self.run_region).grid(row=3, column=3, columnspan=2, padx=3)
        ttk.Button(rtf, text="Verify Positions", command=self.run_verify).grid(row=3, column=5, padx=3)

        # flush/wash selected nozzles -- opens a pop-up to pick nozzles
        ttk.Button(rtf, text="Flush Nozzles...", command=self.open_flush_dialog
               ).grid(row=5, column=0, columnspan=2, padx=3, pady=(6, 2), sticky="w")

        # realistic task timing toggle -- affects how long routines take, so it
        # lives with the routines. ON = tasks take their real duration.
        self.realistic = tk.BooleanVar(value=not self.dod.fast)
        ttk.Checkbutton(rtf, text="Realistic task timing (tasks take their real duration)",
                variable=self.realistic, command=self.toggle_timing
                ).grid(row=4, column=0, columnspan=6, sticky="w", padx=3, pady=(6, 2))

        # log
        lf = ttk.LabelFrame(self.root, text="Command Log")
        lf.grid(row=5, column=0, columnspan=2, sticky="nsew", **pad)
        self.logbox = scrolledtext.ScrolledText(lf, width=76, height=11, font=("Consolas", 9),
                                                state="disabled", bg="#0e1116", fg="#cfd8dc")
        self.logbox.pack(fill="both", expand=True, padx=4, pady=4)

        self.root.columnconfigure(0, weight=1); self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(5, weight=1)
        self.log("control panel ready (real DoD interface)")

    # ---- helpers ----
    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.logbox.configure(state="normal")
        self.logbox.insert("end", f"[{ts}] {msg}\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def _threaded(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def _params(self):
        return dict(nozzle=self.p_nozzle.get(), frequency=self.p_freq.get(),
                    voltage=self.p_voltage.get(), pulse_width=self.p_pulse.get())

    # ---- actions ----
    def use_custom_step(self):
        # set the active jog step to whatever the user wants
        try:
            val = int(self.custom_step.get())
            if val <= 0:
                self.log("custom step must be positive")
                return
            self.step.set(val)
            self.log(f"jog step set to {val} um")
        except Exception:
            self.log("custom step must be a whole number")

    def jog(self, axis, direction):
        d = {"X": 0, "Y": 0, "Z": 0}
        d[axis] = self.step.get() * direction
        r = self.dod.move_relative(d["X"], d["Y"], d["Z"])
        self.log(f"jog {axis}{'+' if direction>0 else ''}{d[axis]}" + ("" if r.get("ok") else " REFUSED"))
        self._refresh()

    def safe_go(self):
        name = self.target.get()
        self._threaded(lambda: (R.safe_goto(self.dod, name, log=self.log), self._refresh()))

    def dispense_on(self):
        self.dod.dispense_on(self.p_mode.get()); self.log(f"dispense ON ({self.p_mode.get()})"); self._refresh()

    def dispense_off(self):
        self.dod.dispense_off(); self.log("dispense OFF"); self._refresh()

    def apply_nozzle(self):
        # validate nozzle range before applying (robot has 8 nozzles)
        n = self.p_nozzle.get()
        if not (1 <= n <= 8):
            self.log(f"nozzle {n} invalid -- must be 1-8")
            return
        R.configure_nozzle(self.dod, log=self.log, **self._params()); self._refresh()

    def toggle_timing(self):
        # checkbox ON  = realistic  -> dummy.fast must be False
        # checkbox OFF = fast tests -> dummy.fast must be True
        self.dod.fast = not self.realistic.get()
        mode = "realistic (tasks take their real duration)" if self.realistic.get() else "fast (tasks return immediately)"
        self.log(f"task timing: {mode}")

    def estop(self):
        self.dod.stop_task(); self.dod.dispense_off()
        self.log("*** EMERGENCY STOP ***"); self._refresh()

    def run_safety(self):
        self._threaded(lambda: self._report(R.safety_check_routine(self.dod, log=self.log)))

    def run_sample_test(self):
        p = self._params()
        self._threaded(lambda: self._report(R.sample_test_routine(
            self.dod, n_samples=self.p_samples.get(), probe_volume=self.p_probe_vol.get(),
            dispense_mode=self.p_mode.get(), log=self.log, **p)))

    def run_stability(self):
        p = self._params()
        self._threaded(lambda: self._report(R.stability_check(
            self.dod, shots=self.p_shots.get(), dispense_mode=self.p_mode.get(), log=self.log, **p)))

    def run_wash(self):
        self._threaded(lambda: (R.wash_cycle(self.dod, log=self.log), self._refresh()))

    def run_scan(self):
        p = self._params()
        self._threaded(lambda: (R.scan_slide(self.dod, dispense_mode=self.p_mode.get(), log=self.log, **p), self._refresh()))

    def run_sweep(self):
        p = self._params()
        self._threaded(lambda: self._report(R.parameter_sweep(
            self.dod, param=self.p_sweep.get(), dispense_mode=self.p_mode.get(), log=self.log, **p)))

    def run_align(self):
        self._threaded(lambda: (self._report(R.align_droplet(self.dod, log=self.log)), self._refresh()))

    def run_startup(self):
        self._threaded(lambda: (self._report(R.startup_routine(self.dod, log=self.log)), self._refresh()))

    def run_shutdown(self):
        self._threaded(lambda: (self._report(R.shutdown_routine(self.dod, log=self.log)), self._refresh()))

    def run_nozzle_health(self):
        self._threaded(lambda: self._report(R.nozzle_health_check(self.dod, log=self.log)))

    def run_region(self):
        self._threaded(lambda: self._report(R.region_exclusion_check(self.dod, log=self.log)))

    def run_verify(self):
        self._threaded(lambda: self._report(R.verify_positions(self.dod, log=self.log)))

    def open_flush_dialog(self):                                              # <-- NEW (whole method)
        """Pop-up window to select which nozzles to flush and which wash task."""
        win = tk.Toplevel(self.root)
        win.title("Flush / Wash Nozzles")
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)

        ttk.Label(win, text="Select nozzles to flush:",
                  font=("Arial", 10, "bold")).grid(row=0, column=0, columnspan=4,
                                                    sticky="w", padx=8, pady=(8, 2))
        sel = {}
        cf = ttk.Frame(win); cf.grid(row=1, column=0, columnspan=4, padx=8)
        for ch in R.VALID_NOZZLES:
            var = tk.BooleanVar(value=False)
            sel[ch] = var
            ttk.Checkbutton(cf, text=str(ch), variable=var).pack(side="left")

        bf = ttk.Frame(win); bf.grid(row=2, column=0, columnspan=8, sticky="w", padx=8, pady=2)
        ttk.Button(bf, text="All", width=6,
                   command=lambda: [v.set(True) for v in sel.values()]).pack(side="left")
        ttk.Button(bf, text="None", width=6,
                   command=lambda: [v.set(False) for v in sel.values()]).pack(side="left")
        ttk.Button(bf, text="Activated", width=10,
                   command=lambda: [sel[c].set(c in self.dod.activated_nozzles)
                                    for c in sel]).pack(side="left")

        ttk.Label(win, text="Wash task:").grid(row=3, column=0, columnspan=2,
                                               sticky="e", padx=8, pady=(6, 2))
        task_var = tk.StringVar(value="WashFlush_Medium")
        ttk.Combobox(win, textvariable=task_var,
                     values=["WashFlush_Medium", "WashFlush_Light_Narrow",
                             "WashFlush_Strong_Narrow"],
                     width=24, state="readonly").grid(row=3, column=2, columnspan=6,
                                                       sticky="w", padx=4, pady=(6, 2))

        def start():
            channels = [ch for ch, v in sel.items() if v.get()]
            if not channels:
                messagebox.showwarning("Flush", "Select at least one nozzle.",
                                       parent=win)
                return
            task = task_var.get()
            win.destroy()
            self._threaded(lambda: self._report(
                R.flush_nozzles(self.dod, channels, task=task, log=self.log)))

        af = ttk.Frame(win); af.grid(row=4, column=0, columnspan=8, pady=8)
        ttk.Button(af, text="Start Flush", command=start).pack(side="left", padx=6)
        ttk.Button(af, text="Cancel", command=win.destroy).pack(side="left", padx=6)
                                                                              # <-- NEW ends here
    def _report(self, result):
        self.log(f"result: {result}")
        self._refresh()

    def _refresh(self):
        s = self.dod.get_status()
        p = s["Position"]
        self.pos_lbl.config(text=f"X={p['X']:.0f} Y={p['Y']:.0f} Z={p['Z']:.0f}")
        self.env_lbl.config(text=f"dispensing: {s['dispensing']}   nozzle#{self.dod.nozzle} "
                                 f"{self.dod.nozzle_frequency:.0f}Hz {self.dod.nozzle_voltage:.0f}V   probe:{s['probe_volume']:.0f}uL   "
                                 f"hum:{s['humidity']}% temp:{s['temperature']}C   last:{self.dod.last_position}")
        if not inside_workspace(p["X"], p["Y"], p["Z"]):
            self.state_lbl.config(text="OUTSIDE WORKSPACE", bg="#c0392b", fg="white")
        elif KEEP_OUT.contains(Point(p["X"], p["Y"], p["Z"])):
            self.state_lbl.config(text="IN KEEP-OUT ZONE", bg="#c0392b", fg="white")
        else:
            self.state_lbl.config(text="OK / in bounds", bg="#27ae60", fg="white")

    def on_close(self):
        try:
            self.dod.stop()
        finally:
            self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = ControlGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()