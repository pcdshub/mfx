import argparse
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from datetime import datetime

# every robot call comes from safe_demo -- nothing is reimplemented here
from safe_demo import (connect_dod, read_live_position, read_drive_range,
                       read_task_names, preflight,
                       run_task, describe_task, jog_axis, set_nozzle_params, task_risk,
                       read_activated_nozzles, select_nozzle, set_dispensing)

POLL_MS = 1000


class DodGui:
    def __init__(self, root, ip):
        self.root = root
        self.ip = ip
        self.root.title("DoD Robot -- live (%s)" % ip)
        self.dod = connect_dod(ip)
        self.busy = False
        self.drive_range = None

        self._build()
        self._load_tasks()
        self._load_nozzles()
        self._read_drive_range()
        self._poll()

    # ------------------------------------------------------------ layout
    def _build(self):
        pad = {"padx": 6, "pady": 4}

        pf = ttk.LabelFrame(self.root, text="Live position (read-only)")
        pf.grid(row=0, column=0, columnspan=2, sticky="ew", **pad)
        self.pos_lbl = tk.Label(pf, text="X=?  Y=?  Z=?", font=("Consolas", 16), width=30)
        self.pos_lbl.grid(row=0, column=0, padx=6, pady=6)
        self.state_lbl = tk.Label(pf, text="connecting...", font=("Arial", 10, "bold"), width=22)
        self.state_lbl.grid(row=0, column=1, padx=6)
        self.range_lbl = tk.Label(pf, text="drive range: ?", font=("Consolas", 9))
        self.range_lbl.grid(row=1, column=0, columnspan=2, sticky="w", padx=6)

        gf = ttk.LabelFrame(self.root, text="Run a task")
        gf.grid(row=1, column=0, columnspan=2, sticky="ew", **pad)

        ttk.Label(gf, text="task:").grid(row=0, column=0, padx=4, pady=6, sticky="e")
        self.task = tk.StringVar()
        self.task_box = ttk.Combobox(gf, textvariable=self.task, width=30)
        self.task_box.grid(row=0, column=1, padx=4)
        self.task_box.bind("<<ComboboxSelected>>", self._describe)

        self.desc_lbl = tk.Label(gf, text="pick a task", font=("Arial", 9),
                                 fg="#444441", wraplength=340, justify="left")
        self.desc_lbl.grid(row=1, column=0, columnspan=2, sticky="w", padx=4, pady=(0, 4))

        self.dry = tk.BooleanVar(value=True)
        ttk.Checkbutton(gf, text="Dry run (print the plan, do not move)",
                        variable=self.dry).grid(row=2, column=0, columnspan=2,
                                                sticky="w", padx=4, pady=(2, 4))

        self.go_btn = tk.Button(gf, text="RUN TASK", bg="#2e7d32", fg="white",
                                font=("Arial", 11, "bold"), height=3, width=14,
                                command=self.run_selected_task)
        self.go_btn.grid(row=0, column=2, rowspan=3, padx=8, pady=6)

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
                          font=("Arial", 10, "bold"),
                          command=lambda a=axis, s=sign: self.jog(a, s))
            b.grid(row=0, column=col, padx=3)

        tk.Label(jf, text="move_x/y/z do NOT lift Z or check collision. Small steps only.",
                 fg="#b71c1c", font=("Arial", 9)).grid(row=2, column=0, columnspan=6,
                                                       sticky="w", padx=4, pady=(0, 4))

        # ---- nozzle parameters panel ----
        nf = ttk.LabelFrame(self.root, text="Nozzle")
        nf.grid(row=3, column=0, columnspan=2, sticky="ew", **pad)

        # select nozzle (only the activated channels)
        ttk.Label(nf, text="select:").grid(row=0, column=0, padx=(6, 2), pady=6, sticky="e")
        self.nozzle = tk.StringVar()
        self.nozzle_box = ttk.Combobox(nf, textvariable=self.nozzle, width=5, state="readonly")
        self.nozzle_box.grid(row=0, column=1, padx=(0, 4))
        tk.Button(nf, text="SELECT", bg="#1565c0", fg="white", font=("Arial", 9, "bold"),
                  command=self.select_nozzle_btn).grid(row=0, column=2, padx=(0, 12))

        self.volts = tk.StringVar(value="80")
        self.pulse = tk.StringVar(value="20")
        self.freq = tk.StringVar(value="30000")
        for col, (lab, var, w) in enumerate([("volts:", self.volts, 6),
                                             ("pulse:", self.pulse, 6),
                                             ("freq:", self.freq, 8)]):
            ttk.Label(nf, text=lab).grid(row=0, column=3 + col * 2, padx=(4, 2), pady=6, sticky="e")
            ttk.Entry(nf, textvariable=var, width=w).grid(row=0, column=4 + col * 2, padx=(0, 4))
        tk.Button(nf, text="SET PARAMS", bg="#1565c0", fg="white",
                  font=("Arial", 10, "bold"), command=self.set_params).grid(
                      row=0, column=9, padx=8, pady=6)
        tk.Label(nf, text="select dropdown shows only ACTIVATED channels. params: one call sets all three.",
                 fg="#444441", font=("Arial", 8)).grid(row=1, column=0, columnspan=10,
                                                       sticky="w", padx=4, pady=(0, 4))

        # dispensing row
        ttk.Label(nf, text="dispensing:").grid(row=2, column=0, padx=(6, 2), pady=(2, 6), sticky="e")
        tk.Button(nf, text="OFF", bg="#2e7d32", fg="white", font=("Arial", 9, "bold"), width=7,
                  command=lambda: self.dispense("Off")).grid(row=2, column=1, padx=2, pady=(2, 6))
        tk.Button(nf, text="Free", bg="#e65100", fg="white", font=("Arial", 9, "bold"), width=7,
                  command=lambda: self.dispense("Free")).grid(row=2, column=2, padx=2, pady=(2, 6))
        tk.Button(nf, text="Trigger", bg="#e65100", fg="white", font=("Arial", 9, "bold"), width=7,
                  command=lambda: self.dispense("Trigger")).grid(row=2, column=3, padx=2, pady=(2, 6))
        tk.Label(nf, text="Free/Trigger EJECT LIQUID. OFF is always safe.",
                 fg="#b71c1c", font=("Arial", 8)).grid(row=2, column=4, columnspan=6,
                                                       sticky="w", padx=6, pady=(2, 6))

        lf = ttk.LabelFrame(self.root, text="Log")
        lf.grid(row=4, column=0, columnspan=2, sticky="nsew", **pad)
        self.logbox = scrolledtext.ScrolledText(lf, width=82, height=22, font=("Consolas", 13),
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
        """The `confirm` callback -- the GUI's version of typing GO."""
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
        try:
            v = int(self.volts.get())
            p = self.pulse.get().strip()
            f = int(self.freq.get())
        except ValueError:
            self.log("volts and freq must be integers; pulse is a string")
            return
        self.busy = True
        threading.Thread(target=self._params_worker, args=(v, p, f), daemon=True).start()

    def _params_worker(self, v, p, f):
        try:
            set_nozzle_params(self.dod, volts=v, pulse=p, frequency=f,
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