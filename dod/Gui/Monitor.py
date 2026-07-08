"""
monitor.py -- live monitoring dashboard for the DoD robot (2D, three views).

Three standard engineering views: top-down (X-Y), front (X-Z), side (Y-Z).
Uses real coordinates + drive range, runs against the DoDDummy.

Run:  uv run monitor.py
"""

import json
import tkinter as tk
from tkinter import ttk

from pathplan import Zone
from dod_dummy import DoDDummy

WORKSPACE = {"X": 254000, "Y": 118000, "Z": 40000}
ZONE = {"xmin": 100000, "ymin": 40000, "zmin": 0,
        "xmax": 140000, "ymax": 70000, "zmax": 20000}
KEY_STATIONS = ["Home", "InteractionPoint", "WashStation1", "WasteStation1",
                "CameraStation", "Eppi1Nozzle1", "Nozzle 4 IP", "Probe (96WP-1nozzle)"]
POLL_MS = 300
CANVAS_PX = 320


def load_stations():
    try:
        with open("named_position_coords.json") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"Home": {"X": 253300, "Y": 0, "Z": 0},
                "InteractionPoint": {"X": 17866, "Y": 101160, "Z": 32797}}


STATION_COORDS = load_stations()


def build_robot():
    zone = Zone(ZONE["xmin"], ZONE["ymin"], ZONE["zmin"],
                ZONE["xmax"], ZONE["ymax"], ZONE["zmax"], margin=2000)
    d = DoDDummy(zone=zone)
    d.connect()
    return d


class MonitorDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("DoD Robot Monitor (dummy)")
        self.robot = build_robot()

        self._demo_targets = [(n, (c["X"], c["Y"], c["Z"])) for n, c in STATION_COORDS.items()]
        self._demo_i = 0
        self.dot_top = None
        self.dot_front = None
        self.dot_side = None

        self._build_widgets()
        self._poll()

    def _build_widgets(self):
        pad = {"padx": 8, "pady": 6}

        status = ttk.LabelFrame(self.root, text="Robot Status")
        status.grid(row=0, column=0, rowspan=2, sticky="nsew", **pad)

        self.vars = {
            "Connected": tk.StringVar(value="?"),
            "Position":  tk.StringVar(value="?"),
            "Dispensing": tk.StringVar(value="?"),
            "Last position": tk.StringVar(value="?"),
        }
        r = 0
        for label, var in self.vars.items():
            ttk.Label(status, text=label + ":", font=("Arial", 11, "bold")).grid(row=r, column=0, sticky="w", padx=6, pady=4)
            ttk.Label(status, textvariable=var, font=("Consolas", 11)).grid(row=r, column=1, sticky="w", padx=6, pady=4)
            r += 1

        self.live_dot = tk.Canvas(status, width=16, height=16, highlightthickness=0)
        self.live_dot.grid(row=r, column=0, sticky="w", padx=6, pady=8)
        self.live_dot_id = self.live_dot.create_oval(2, 2, 14, 14, fill="#2ecc71", outline="")
        ttk.Label(status, text="live", font=("Arial", 9)).grid(row=r, column=1, sticky="w")
        r += 1

        self.demo_motion = tk.BooleanVar(value=True)
        ttk.Checkbutton(status, text="Demo motion (dummy only)",
                        variable=self.demo_motion).grid(row=r, column=0, columnspan=2, sticky="w", padx=6, pady=6)

        self.c_top = self._make_view("Top-down view (X-Y)", 0, 1)
        self.c_front = self._make_view("Front view (X-Z, height)", 0, 2)
        self.c_side = self._make_view("Side view (Y-Z, height)", 1, 1)

        self._draw_static()

    def _make_view(self, title, row, col):
        frame = ttk.LabelFrame(self.root, text=title)
        frame.grid(row=row, column=col, sticky="nsew", padx=8, pady=6)
        c = tk.Canvas(frame, width=CANVAS_PX, height=CANVAS_PX,
                      bg="#0e1116", highlightthickness=1, highlightbackground="#444")
        c.pack(padx=8, pady=8)
        return c

    def _px(self, a_um, b_um, a_max, b_max):
        m = 28
        usable = CANVAS_PX - 2 * m
        x = m + (a_um / a_max) * usable
        y = m + (1 - (b_um / b_max)) * usable
        return x, y

    def _px_top(self, x, y, z):
        return self._px(x, y, WORKSPACE["X"], WORKSPACE["Y"])

    def _px_front(self, x, y, z):
        return self._px(x, z, WORKSPACE["X"], WORKSPACE["Z"])

    def _px_side(self, x, y, z):
        return self._px(y, z, WORKSPACE["Y"], WORKSPACE["Z"])

    def _draw_static(self):
        m = 28
        views = [
            (self.c_top, self._px_top, "X ->", "Y"),
            (self.c_front, self._px_front, "X ->", "Z"),
            (self.c_side, self._px_side, "Y ->", "Z"),
        ]
        for canvas, mapper, hlabel, vlabel in views:
            canvas.create_rectangle(m, m, CANVAS_PX - m, CANVAS_PX - m, outline="#33415c")

            zx1, zy1 = mapper(ZONE["xmin"], ZONE["ymin"], ZONE["zmin"])
            zx2, zy2 = mapper(ZONE["xmax"], ZONE["ymax"], ZONE["zmax"])
            canvas.create_rectangle(zx1, zy1, zx2, zy2, outline="#e74c3c",
                                    fill="#e74c3c", stipple="gray25")

            for name, c in STATION_COORDS.items():
                px, py = mapper(c["X"], c["Y"], c["Z"])
                canvas.create_oval(px-3, py-3, px+3, py+3, fill="#5dade2", outline="")

            used = []
            for name in KEY_STATIONS:
                if name not in STATION_COORDS:
                    continue
                c = STATION_COORDS[name]
                px, py = mapper(c["X"], c["Y"], c["Z"])
                ly = py
                bumped = True
                while bumped:
                    bumped = False
                    for ux, uy in used:
                        if abs(px - ux) < 55 and abs(ly - uy) < 11:
                            ly += 10
                            bumped = True
                            break
                used.append((px, ly))
                canvas.create_text(px+6, ly, text=name, anchor="w",
                                   fill="#cfd8dc", font=("Arial", 7))

            if "InteractionPoint" in STATION_COORDS:
                ip = STATION_COORDS["InteractionPoint"]
                px, py = mapper(ip["X"], ip["Y"], ip["Z"])
                canvas.create_text(px, py, text="*", fill="#f1c40f", font=("Arial", 16, "bold"))

            canvas.create_text(CANVAS_PX/2, CANVAS_PX-10, text=hlabel, fill="#667", font=("Arial", 7))
            canvas.create_text(14, CANVAS_PX/2, text=vlabel, fill="#667", font=("Arial", 7))

    def _step_demo_motion(self):
        if not self.demo_motion.get():
            return
        name, (tx, ty, tz) = self._demo_targets[self._demo_i]
        p = self.robot.where()
        nx = p.x + (tx - p.x) * 0.4
        ny = p.y + (ty - p.y) * 0.4
        nz = p.z + (tz - p.z) * 0.4
        self.robot.x, self.robot.y, self.robot.z = nx, ny, nz
        if abs(tx-nx) > 3000 or abs(ty-ny) > 3000 or abs(tz-nz) > 3000:
            self.robot.dispense_on("Trigger")
        if abs(tx-nx) < 3000 and abs(ty-ny) < 3000 and abs(tz-nz) < 3000:
            self.robot.last_position = name
            self.robot.dispense_off()
            self._demo_i = (self._demo_i + 1) % len(self._demo_targets)

    def _draw_nozzle(self, canvas, existing, px, py):
        if existing is None:
            return canvas.create_oval(px-6, py-6, px+6, py+6, fill="#e74c3c", outline="white")
        canvas.coords(existing, px-6, py-6, px+6, py+6)
        return existing

    def _poll(self):
        self._step_demo_motion()

        p = self.robot.where()

        self.vars["Connected"].set("yes" if self.robot.connected else "no")
        self.vars["Position"].set(f"X={p.x:.0f}  Y={p.y:.0f}  Z={p.z:.0f}")
        self.vars["Dispensing"].set(self.robot.dispensing_state)
        self.vars["Last position"].set(str(self.robot.last_position))

        tx, ty = self._px_top(p.x, p.y, p.z)
        self.dot_top = self._draw_nozzle(self.c_top, self.dot_top, tx, ty)
        fx, fy = self._px_front(p.x, p.y, p.z)
        self.dot_front = self._draw_nozzle(self.c_front, self.dot_front, fx, fy)
        sx, sy = self._px_side(p.x, p.y, p.z)
        self.dot_side = self._draw_nozzle(self.c_side, self.dot_side, sx, sy)

        cur = self.live_dot.itemcget(self.live_dot_id, "fill")
        self.live_dot.itemconfig(self.live_dot_id, fill="#145a32" if cur == "#2ecc71" else "#2ecc71")

        self.root.after(POLL_MS, self._poll)

    def on_close(self):
        try:
            self.robot.disconnect()
        finally:
            self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = MonitorDashboard(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()