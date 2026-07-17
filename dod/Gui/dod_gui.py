"""
dod_gui.py -- a window for the DoD robot. ALL the robot logic lives in
safe_demo.py; this file is only the window.

    button "GO TO STATION"  ->  safe_demo.wash_routine(...)
    position readout        ->  safe_demo.read_live_position(...)
    drive range             ->  safe_demo.read_drive_range(...)
    station dropdown        ->  safe_demo.read_station_names(...)




SAFETY
  - The position readout polls and is read-only. It never moves anything.
  - "GO TO STATION" is the only thing that moves the robot, and it pops a
    confirm dialog first (that dialog IS the `confirm` callback wash_routine uses).
  - do_move() drives a STRAIGHT LINE and does not check the path. Park the robot
    somewhere safe by hand and confirm each path until collision avoidance exists.
  - The routine runs on a background thread because do_move() blocks.
"""

import argparse
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from datetime import datetime

# every robot call comes from safe_demo -- nothing is reimplemented here
from safe_demo import (connect_dod, read_live_position, read_drive_range, preflight, wash_routine)

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
        self._load_stations()
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

        gf = ttk.LabelFrame(self.root, text="Routine")
        gf.grid(row=1, column=0, columnspan=2, sticky="ew", **pad)

        ttk.Label(gf, text="station:").grid(row=0, column=0, padx=4, pady=6, sticky="e")
        self.station = tk.StringVar()
        self.station_box = ttk.Combobox(gf, textvariable=self.station, width=26, state="readonly")
        self.station_box.grid(row=0, column=1, padx=4)

        ttk.Label(gf, text="task (optional):").grid(row=1, column=0, padx=4, sticky="e")
        self.task = tk.StringVar()
        ttk.Entry(gf, textvariable=self.task, width=28).grid(row=1, column=1, padx=4)

        self.dry = tk.BooleanVar(value=True)
        ttk.Checkbutton(gf, text="Dry run (print the plan, do not move)",
                        variable=self.dry).grid(row=2, column=0, columnspan=2,
                                                sticky="w", padx=4, pady=(4, 0))

        self.go_btn = tk.Button(gf, text="GO TO STATION", bg="#2e7d32", fg="white",
                                font=("Arial", 11, "bold"), height=3, width=16,
                                command=self.run_routine)
        self.go_btn.grid(row=0, column=2, rowspan=3, padx=8, pady=6)

        tk.Label(gf, text="do_move drives a STRAIGHT LINE and does not check the path.",
                 fg="#b71c1c").grid(row=3, column=0, columnspan=3, sticky="w",
                                    padx=4, pady=(2, 4))

        lf = ttk.LabelFrame(self.root, text="Log")
        lf.grid(row=2, column=0, columnspan=2, sticky="nsew", **pad)
        self.logbox = scrolledtext.ScrolledText(lf, width=78, height=16, font=("Consolas", 9),
                                                state="disabled", bg="#0e1116", fg="#cfd8dc")
        self.logbox.pack(fill="both", expand=True, padx=4, pady=4)

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)
        self.log("connected to %s" % self.ip)

    def log(self, msg):
        """This is the `log` callback safe_demo's routine writes into."""
        ts = datetime.now().strftime("%H:%M:%S")
        self.logbox.configure(state="normal")
        self.logbox.insert("end", "[%s] %s\n" % (ts, msg))
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def confirm(self, message):
        """This is the `confirm` callback -- the GUI's version of typing GO."""
        return messagebox.askyesno("Confirm move", message)

    # ------------------------------------------------------------ startup reads
   

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
    def run_routine(self):
        if self.busy:
            self.log("already running -- ignoring")
            return
        station = self.station.get().strip()
        if not station:
            self.log("no station selected")
            return
        task = self.task.get().strip() or None

        self.busy = True
        self.go_btn.config(state="disabled")
        threading.Thread(target=self._worker, args=(station, task), daemon=True).start()

    def _worker(self, station, task):
        """
        Runs safe_demo's preflight + wash_routine, hand THIS window's
        log box and confirm dialog. Off the UI thread because do_move blocks.
        """
        try:
            if not preflight(self.dod, station, task, log=self.log):
                self.log("preflight did not pass -- stopping.")
                return
            wash_routine(self.dod, station, task,
                         dry_run=self.dry.get(),
                         log=self.log,
                         confirm=self.confirm)
        except Exception as e:
            self.log("ROUTINE FAILED: %s" % e)
        finally:
            self.busy = False
            self.go_btn.config(state="normal")


def main():
    ap = argparse.ArgumentParser(description="Live GUI for the real DoD robot")
    ap.add_argument("--ip", default="172.21.72.187")
    args = ap.parse_args()
    root = tk.Tk()
    DodGui(root, args.ip)
    root.mainloop()


if __name__ == "__main__":
    main()