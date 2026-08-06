import argparse
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from datetime import datetime

# every robot call comes from safe_demo -- nothing is reimplemented here
from safe_demo import (connect_dod, read_live_position, read_drive_range,
                       read_task_names, preflight,
                       run_task, describe_task, jog_axis, set_nozzle_params, task_risk,
                       read_activated_nozzles, select_nozzle, set_dispensing,
                       read_pulse_names)

POLL_MS = 1000

# ---- safe_motion configuration -------------------------------------------
# EDIT THESE TWO PATHS to point at the real files on mezz01. If either is
# missing, the GUI falls back to a plain DoD connection (safe mode + the
# planned-path plot are then disabled, but everything else works normally).
EXCLUSION_ZONES_JSON = "exclusion_zones.json"        # <-- EDIT: full path on mezz01
ROBOT_CONFIG_PATH    = "robot_config.json"           # <-- EDIT: INI or .json sidecar


def connect_safe_or_plain(ip, log=print):
    """
    Try to build a SafeRobot (so safe mode + plot_path are available). If the
    package or config files aren't there, fall back to a plain DoD so the GUI
    still opens. Returns (robot, is_safe_robot).
    """
    import os
    try:
        from safe_motion import SafeRobot
        if not os.path.exists(EXCLUSION_ZONES_JSON):
            raise FileNotFoundError("exclusion zones json not found: %s" % EXCLUSION_ZONES_JSON)
        if not os.path.exists(ROBOT_CONFIG_PATH):
            raise FileNotFoundError("robot config not found: %s" % ROBOT_CONFIG_PATH)
        robot = SafeRobot(
            robot_config_path=ROBOT_CONFIG_PATH,
            exclusion_zone_config=EXCLUSION_ZONES_JSON,
            ip=ip,
        )
        log("connected as SafeRobot (safe mode available, starts OFF)")
        return robot, True
    except Exception as e:
        log("SafeRobot unavailable (%s) -- using plain DoD" % e)
        from safe_demo import connect_dod
        return connect_dod(ip), False


class DodGui:
    def __init__(self, root, ip):
        self.root = root
        self.ip = ip
        self.root.title("DoD Robot -- live (%s)" % ip)
        self.dod, self.is_safe_robot = connect_safe_or_plain(ip, log=print)
        self.busy = False
        self.drive_range = None

        self._build()
        self._load_tasks()
        self._load_nozzles()
        self._load_pulses()
        self._read_drive_range()
        self._poll()

    # ------------------------------------------------------------ layout
    def _build(self):
        # ---- overall look: a bit bigger, nicer fonts, more breathing room ----
        self.root.geometry("760x900")          # a bit bigger starting size
        self.root.minsize(680, 760)
        self.root.configure(bg="#eceff1")

        UI   = ("Segoe UI", 11)                # clean sans for labels/buttons
        UI_B = ("Segoe UI", 11, "bold")
        MONO = ("Consolas", 13)               # readable monospace for numbers/log

        style = ttk.Style()
        try:
            style.theme_use("clam")           # cleaner base than the default
        except Exception:
            pass
        style.configure("TLabelframe", background="#eceff1", borderwidth=1,
                        relief="solid", padding=8)
        style.configure("TLabelframe.Label", background="#eceff1",
                        font=("Segoe UI", 11, "bold"), foreground="#37474f")
        style.configure("TLabel", background="#eceff1", font=UI)
        style.configure("TCheckbutton", background="#eceff1", font=UI)
        style.configure("TCombobox", font=UI)
        style.configure("TEntry", font=UI)
        self._font_ui, self._font_ui_b, self._font_mono = UI, UI_B, MONO

        pad = {"padx": 10, "pady": 7}

        pf = ttk.LabelFrame(self.root, text="Live position (read-only)")
        pf.grid(row=0, column=0, columnspan=2, sticky="ew", **pad)
        self.pos_lbl = tk.Label(pf, text="X=?  Y=?  Z=?", font=("Consolas", 20),
                                width=26, bg="#eceff1", fg="#1a237e")
        self.pos_lbl.grid(row=0, column=0, padx=8, pady=8)
        self.state_lbl = tk.Label(pf, text="connecting...", font=UI_B, width=20)
        self.state_lbl.grid(row=0, column=1, padx=8)
        self.range_lbl = tk.Label(pf, text="drive range: ?", font=("Consolas", 11),
                                  bg="#eceff1", fg="#37474f")
        self.range_lbl.grid(row=1, column=0, columnspan=2, sticky="w", padx=8)

        gf = ttk.LabelFrame(self.root, text="Run a task")
        gf.grid(row=1, column=0, columnspan=2, sticky="ew", **pad)

        ttk.Label(gf, text="task:").grid(row=0, column=0, padx=4, pady=6, sticky="e")
        self.task = tk.StringVar()
        self.task_box = ttk.Combobox(gf, textvariable=self.task, width=30)
        self.task_box.grid(row=0, column=1, padx=4)
        self.task_box.bind("<<ComboboxSelected>>", self._describe)

        self.desc_lbl = tk.Label(gf, text="pick a task", font=("Segoe UI", 10),
                                 fg="#444441", wraplength=340, justify="left")
        self.desc_lbl.grid(row=1, column=0, columnspan=2, sticky="w", padx=4, pady=(0, 4))

        self.dry = tk.BooleanVar(value=True)
        ttk.Checkbutton(gf, text="Dry run (print the plan, do not move)",
                        variable=self.dry).grid(row=2, column=0, columnspan=2,
                                                sticky="w", padx=4, pady=(2, 0))

        self.skip_confirm = tk.BooleanVar(value=False)
        ttk.Checkbutton(gf, text="Skip confirmation pop-ups (act immediately)",
                        variable=self.skip_confirm).grid(row=3, column=0, columnspan=2,
                                                         sticky="w", padx=4, pady=(0, 4))

        # ---- safe mode toggle (only meaningful when connected as SafeRobot) ----
        self.safe_mode = tk.BooleanVar(value=False)
        self.safe_chk = ttk.Checkbutton(
            gf, text="Safe mode (obstacle-avoiding moves via safe_motion)",
            variable=self.safe_mode, command=self.toggle_safe_mode)
        self.safe_chk.grid(row=5, column=0, columnspan=2, sticky="w", padx=4, pady=(0, 4))
        if not getattr(self, "is_safe_robot", False):
            self.safe_chk.state(["disabled"])

        self.go_btn = tk.Button(gf, text="RUN TASK", bg="#2e7d32", fg="white",
                                font=("Segoe UI", 12, "bold"), height=2, width=15,
                                command=self.run_selected_task)
        self.go_btn.grid(row=0, column=2, rowspan=3, padx=8, pady=6)

        # ---- safe-motion path preview (opens Sebastian's matplotlib plot) ----
        ttk.Label(gf, text="target position:").grid(row=4, column=0, padx=4, pady=(6, 4), sticky="e")
        self.plan_target = tk.StringVar()
        ttk.Entry(gf, textvariable=self.plan_target, width=18).grid(
            row=4, column=1, sticky="w", padx=4, pady=(6, 4))
        tk.Button(gf, text="Show planned path", bg="#1565c0", fg="white",
                  font=("Segoe UI", 10, "bold"), command=self.show_path).grid(
                      row=4, column=2, padx=8, pady=(6, 4))

        # ---- jog panel ----
        jf = ttk.LabelFrame(self.root, text="Jog (raw move -- no safety check)")
        jf.grid(row=2, column=0, columnspan=2, sticky="ew", **pad)

        ttk.Label(jf, text="step (um):").grid(row=0, column=0, padx=4, pady=4, sticky="e")
        self.step = tk.StringVar(value="100")
        ttk.Entry(jf, textvariable=self.step, width=8).grid(row=0, column=1, padx=4, sticky="w")

        btns = ttk.Frame(jf)
        btns.grid(row=1, column=0, columnspan=6, padx=4, pady=4)
        for col, (label, axis, sign) in enumerate([
            ("-X", "X", -1), ("+X", "X", +1),
            ("-Y", "Y", -1), ("+Y", "Y", +1),
            ("-Z", "Z", -1), ("+Z", "Z", +1),
        ]):
            b = tk.Button(btns, text=label, width=5, height=1,
                          font=("Segoe UI", 10, "bold"),
                          command=lambda a=axis, s=sign: self.jog(a, s))
            b.grid(row=0, column=col, padx=3)

        tk.Label(jf, text="move_x/y/z do NOT lift Z or check collision. Small steps only.",
                 fg="#b71c1c", font=("Segoe UI", 9)).grid(row=2, column=0, columnspan=6,
                                                       sticky="w", padx=4, pady=(0, 4))

        # ---- nozzle parameters panel ----
        nf = ttk.LabelFrame(self.root, text="Nozzle")
        nf.grid(row=3, column=0, columnspan=2, sticky="ew", **pad)

        # select nozzle (only the activated channels)
        ttk.Label(nf, text="select:").grid(row=0, column=0, padx=(6, 2), pady=6, sticky="e")
        self.nozzle = tk.StringVar()
        self.nozzle_box = ttk.Combobox(nf, textvariable=self.nozzle, width=5, state="readonly")
        self.nozzle_box.grid(row=0, column=1, padx=(0, 4))
        self.nozzle_box.bind("<<ComboboxSelected>>", self._on_nozzle_change)
        tk.Button(nf, text="SELECT", bg="#1565c0", fg="white", font=("Segoe UI", 10, "bold"),
                  command=self.select_nozzle_btn).grid(row=0, column=2, padx=(0, 12))

        self.volts = tk.StringVar(value="80")
        self.pulse = tk.StringVar(value="")
        self.freq = tk.StringVar(value="30000")

        # volts (number entry)
        ttk.Label(nf, text="volts:").grid(row=0, column=3, padx=(4, 2), pady=6, sticky="e")
        ttk.Entry(nf, textvariable=self.volts, width=6).grid(row=0, column=4, padx=(0, 4))

        # pulse -- nozzles 1&2 take a NAME (dropdown); nozzles 3&4 take a NUMBER
        # (typed). The field switches mode based on the selected nozzle.
        ttk.Label(nf, text="pulse:").grid(row=0, column=5, padx=(4, 2), pady=6, sticky="e")
        self.pulse_box = ttk.Combobox(nf, textvariable=self.pulse, width=20, state="readonly")
        self.pulse_box.grid(row=0, column=6, padx=(0, 4))
        self._pulse_names = []   # filled by _load_pulses

        # freq (number entry)
        ttk.Label(nf, text="freq:").grid(row=0, column=7, padx=(4, 2), pady=6, sticky="e")
        ttk.Entry(nf, textvariable=self.freq, width=8).grid(row=0, column=8, padx=(0, 4))

        tk.Button(nf, text="SET PARAMS", bg="#1565c0", fg="white",
                  font=("Segoe UI", 10, "bold"), command=self.set_params).grid(
                      row=0, column=9, padx=8, pady=6)
        self.pulse_hint = tk.Label(nf, text="pulse depends on the selected nozzle",
                                   fg="#607d8b", font=("Segoe UI", 9), bg="#eceff1")
        self.pulse_hint.grid(row=1, column=0, columnspan=10, sticky="w", padx=4, pady=(0, 4))

        # dispensing row
        ttk.Label(nf, text="dispensing:").grid(row=2, column=0, padx=(6, 2), pady=(2, 6), sticky="e")
        tk.Button(nf, text="OFF", bg="#2e7d32", fg="white", font=("Segoe UI", 10, "bold"), width=8,
                  command=lambda: self.dispense("Off")).grid(row=2, column=1, padx=2, pady=(2, 6))
        tk.Button(nf, text="Free", bg="#e65100", fg="white", font=("Segoe UI", 10, "bold"), width=8,
                  command=lambda: self.dispense("Free")).grid(row=2, column=2, padx=2, pady=(2, 6))
        tk.Button(nf, text="Trigger", bg="#e65100", fg="white", font=("Segoe UI", 10, "bold"), width=8,
                  command=lambda: self.dispense("Trigger")).grid(row=2, column=3, padx=2, pady=(2, 6))
        tk.Label(nf, text="Free/Trigger EJECT LIQUID. OFF is always safe.",
                 fg="#b71c1c", font=("Segoe UI", 9)).grid(row=2, column=4, columnspan=6,
                                                       sticky="w", padx=6, pady=(2, 6))

        lf = ttk.LabelFrame(self.root, text="Log")
        lf.grid(row=4, column=0, columnspan=2, sticky="nsew", **pad)
        self.logbox = scrolledtext.ScrolledText(lf, width=82, height=22, font=("Consolas", 13), borderwidth=0,
                                                state="disabled", bg="#0e1116", fg="#cfd8dc")
        self.logbox.pack(fill="both", expand=True, padx=4, pady=4)

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(4, weight=1)
        self.log("connected to %s" % self.ip)

    def log(self, msg):
        """The `log` callback safe_demo's routine writes into."""
        ts = datetime.now().strftime("%H:%M:%S")
        self.logbox.configure(state="normal")
        self.logbox.insert("end", "[%s] %s\n" % (ts, msg))
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def confirm(self, message):
        """
        The `confirm` callback -- the GUI's version of typing GO.

        If "Skip confirmation pop-ups" is ticked, auto-approve WITHOUT showing
        the dialog. Dry-run still protects you (it never calls confirm at all
        when dry_run is on -- it just prints), and every action is still logged,
        so skipping confirms only removes the extra click, not the safety record.
        """
        if self.skip_confirm.get():
            self.log("(confirmation skipped -- 'skip pop-ups' is on)")
            return True
        return messagebox.askyesno("Confirm move", message)

    # ------------------------------------------------------------ startup reads
    def _describe(self, event=None):
        t = self.task.get().strip()
        if not t:
            self.desc_lbl.config(text="pick a task", fg="#444441")
            return
        risk = task_risk(t)
        color = {"none": "#2e7d32", "move": "#b71c1c",
                 "op": "#e65100", "?": "#444441"}.get(risk, "#444441")
        tag = {"none": "[no motion] ", "move": "[MOVES ROBOT] ",
               "op": "[operator pause] ", "?": ""}.get(risk, "")
        self.desc_lbl.config(text=tag + describe_task(t), fg=color)

    def _load_tasks(self):
        try:
            tasks = read_task_names(self.dod)
            self.task_box["values"] = sorted(tasks)
            self.log("loaded %d tasks from the robot" % len(tasks))
        except Exception as e:
            self.log("could not read task names: %s" % e)
            self.log("   -> type a task name into the box instead")

    def _read_drive_range(self):
        try:
            self.drive_range = read_drive_range(self.dod)
            d = self.drive_range
            self.range_lbl.config(text="drive range (live):  X 0-%.0f   Y 0-%.0f   Z 0-%.0f"
                                       % (d["X"], d["Y"], d["Z"]))
            self.log("drive range: X=%.0f Y=%.0f Z=%.0f" % (d["X"], d["Y"], d["Z"]))
        except Exception as e:
            self.range_lbl.config(text="drive range: FAILED (%s)" % e)
            self.log("could not read drive range: %s" % e)

    # ------------------------------------------------------------ polling
    def _poll(self):
        try:
            p = read_live_position(self.dod)
            self.pos_lbl.config(text="X=%.0f  Y=%.0f  Z=%.0f" % (p["X"], p["Y"], p["Z"]))
            if self.busy:
                self.state_lbl.config(text="RUNNING", bg="#f9a825", fg="black")
            elif p["X"] == 0 and p["Y"] == 0 and p["Z"] == 0:
                self.state_lbl.config(text="SUSPECT (0,0,0)", bg="#c0392b", fg="white")
            elif self.drive_range and not self._in_range(p):
                self.state_lbl.config(text="OUTSIDE DRIVE RANGE", bg="#c0392b", fg="white")
            else:
                self.state_lbl.config(text="live", bg="#2e7d32", fg="white")
        except Exception as e:
            self.pos_lbl.config(text="read failed")
            self.state_lbl.config(text="READ ERROR", bg="#c0392b", fg="white")
            self.log("position read failed: %s" % e)
        self.root.after(POLL_MS, self._poll)

    def _in_range(self, p):
        d = self.drive_range
        return (0 <= p["X"] <= d["X"] and 0 <= p["Y"] <= d["Y"] and 0 <= p["Z"] <= d["Z"])

    # ------------------------------------------------------------ the button
    def _load_nozzles(self):
        try:
            armed = read_activated_nozzles(self.dod)
            self.nozzle_box["values"] = armed
            if armed:
                self.nozzle.set(armed[0])
            self.log("activated nozzles: %s" % armed)
        except Exception as e:
            self.log("could not read activated nozzles: %s" % e)

    def _load_pulses(self):
        try:
            names = read_pulse_names(self.dod)
            self._pulse_names = names
            self.pulse_box["values"] = names
            if names:
                self.pulse.set(names[0])
            self.log("loaded %d pulse shapes from the robot" % len(names))
        except Exception as e:
            self._pulse_names = []
            self.log("could not read pulse names: %s" % e)
            self.log("   -> pulse dropdown is empty until names load")
        # set the field mode for whatever nozzle is currently selected
        self._on_nozzle_change()

    def _on_nozzle_change(self, event=None):
        """
        Nozzles 1 & 2 use a NAMED pulse shape -> dropdown of names.
        Nozzles 3 & 4 use a NUMBER (waveform duration) -> free typing.
        Switch the pulse field to match the selected nozzle.
        """
        ch = self.nozzle.get().strip()
        named = ch in ("1", "2")
        if named:
            self.pulse_box["values"] = self._pulse_names
            self.pulse_box.config(state="readonly")   # pick from the list
            if self._pulse_names and self.pulse.get() not in self._pulse_names:
                self.pulse.set(self._pulse_names[0])
            self.pulse_hint.config(text="nozzle %s: pulse is a NAME (pick from list)" % (ch or "?"))
        else:
            self.pulse_box["values"] = []
            self.pulse_box.config(state="normal")      # type a number
            # clear a leftover name so a number can be typed
            if self.pulse.get() in self._pulse_names:
                self.pulse.set("")
            self.pulse_hint.config(text="nozzle %s: pulse is a NUMBER (e.g. 48)" % (ch or "?"))

    def select_nozzle_btn(self):
        if self.busy:
            self.log("busy -- ignoring")
            return
        ch = self.nozzle.get().strip()
        if not ch:
            self.log("no nozzle selected")
            return
        self.busy = True
        threading.Thread(target=self._select_worker, args=(ch,), daemon=True).start()

    def _select_worker(self, ch):
        try:
            select_nozzle(self.dod, ch, dry_run=self.dry.get(),
                          log=self.log, confirm=self.confirm)
        except Exception as e:
            self.log("SELECT FAILED: %s" % e)
        finally:
            self.busy = False

    def dispense(self, mode):
        if self.busy:
            self.log("busy -- ignoring")
            return
        self.busy = True
        threading.Thread(target=self._dispense_worker, args=(mode,), daemon=True).start()

    def _dispense_worker(self, mode):
        try:
            set_dispensing(self.dod, mode, dry_run=self.dry.get(),
                           log=self.log, confirm=self.confirm)
        except Exception as e:
            self.log("DISPENSE FAILED: %s" % e)
        finally:
            self.busy = False

    def set_params(self):
        if self.busy:
            self.log("busy -- ignoring")
            return
        ch = self.nozzle.get().strip()
        if not ch:
            self.log("pick a nozzle in the 'select' dropdown first -- params apply to that nozzle")
            return
        try:
            v = int(self.volts.get())
            f = int(self.freq.get())
        except ValueError:
            self.log("volts and freq must be whole numbers")
            return
        p = self.pulse.get().strip()
        self.busy = True
        threading.Thread(target=self._params_worker, args=(ch, v, p, f), daemon=True).start()

    def _params_worker(self, ch, v, p, f):
        try:
            set_nozzle_params(self.dod, ch, volts=v, pulse=p, frequency=f,
                              dry_run=self.dry.get(), log=self.log, confirm=self.confirm)
        except Exception as e:
            self.log("SET PARAMS FAILED: %s" % e)
        finally:
            self.busy = False

    def jog(self, axis, sign):
        if self.busy:
            self.log("busy -- ignoring jog")
            return
        try:
            step = float(self.step.get())
        except ValueError:
            self.log("step must be a number, got %r" % self.step.get())
            return
        if step <= 0:
            self.log("step must be positive")
            return
        delta = sign * step
        self.busy = True
        self.go_btn.config(state="disabled")
        threading.Thread(target=self._jog_worker, args=(axis, delta), daemon=True).start()

    def _jog_worker(self, axis, delta):
        try:
            jog_axis(self.dod, axis, delta, dry_run=self.dry.get(),
                     log=self.log, confirm=self.confirm)
        except Exception as e:
            self.log("JOG FAILED: %s" % e)
        finally:
            self.busy = False
            self.go_btn.config(state="normal")

    def toggle_safe_mode(self):
        """Turn safe_mode on/off on the SafeRobot. No-op on a plain DoD."""
        if not getattr(self, "is_safe_robot", False):
            self.log("safe mode needs SafeRobot -- not available on this connection.")
            self.safe_mode.set(False)
            return
        want = self.safe_mode.get()
        # if a divergence locked safe mode, don't silently re-enable
        if want and getattr(self.dod, "safe_mode_locked", False):
            self.log("*** safe mode is LOCKED after a position divergence. ***")
            self.log("    verify the robot, then acknowledge the divergence before re-enabling.")
            self.safe_mode.set(False)
            return
        try:
            self.dod.safe_mode = want
            self.log("safe mode %s" % ("ON -- moves are obstacle-checked" if want
                                       else "OFF -- passthrough to DoD"))
        except Exception as e:
            self.log("could not set safe mode: %s" % e)
            self.safe_mode.set(False)

    def show_path(self):
        """
        Open Sebastian's real matplotlib path preview via SafeRobot.plot_path().
        The target is a POSITION NAME (must be in the registry), e.g. 'Home'.
        Start defaults to the robot's live position.
        """
        if not getattr(self, "is_safe_robot", False):
            self.log("planned-path plot needs SafeRobot -- check the config paths "
                     "at the top of dod_gui.py (safe_motion + exclusion_zones.json).")
            return
        target = self.plan_target.get().strip()
        if not target:
            self.log("type a target POSITION NAME first (e.g. Home, CameraStation) "
                     "-- it must exist in the registry.")
            return
        self.log("opening path preview to '%s' (matplotlib window; close it to continue)" % target)

        def _worker():
            try:
                self.dod.plot_path(target)     # start defaults to live position
            except KeyError:
                self.log("'%s' is not in the registry -- check the exact position name." % target)
            except Exception as e:
                self.log("plot failed: %s" % e)

        threading.Thread(target=_worker, daemon=True).start()

    def run_selected_task(self):
        if self.busy:
            self.log("already running -- ignoring")
            return
        task = self.task.get().strip()
        if not task:
            self.log("no task selected -- pick one first")
            return
        self.busy = True
        self.go_btn.config(state="disabled")
        threading.Thread(target=self._worker, args=(task,), daemon=True).start()

    def _worker(self, task):
        """Runs safe_demo.run_task with THIS window's log box and confirm dialog."""
        try:
            if not preflight(self.dod, None, task, log=self.log):
                self.log("preflight did not pass -- stopping.")
                return
            run_task(self.dod, task, dry_run=self.dry.get(),
                     log=self.log, confirm=self.confirm)
        except Exception as e:
            self.log("TASK FAILED: %s" % e)
        finally:
            self.busy = False
            self.go_btn.config(state="normal")


def main():
    ap = argparse.ArgumentParser(description="Live GUI for the real DoD robot")
    ap.add_argument("--ip", default="172.21.39.172")
    args = ap.parse_args()
    root = tk.Tk()
    DodGui(root, args.ip)
    root.mainloop()


if __name__ == "__main__":
    main()