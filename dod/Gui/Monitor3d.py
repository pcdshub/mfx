"""
monitor_3d.py -- simplified 3D live view of the DoD robot + safety tools.

3D view: workspace box, station markers, interaction point (beam hit) + beam
line, keep-out zone, and the live nozzle. Drag to rotate.

Safety tools (share the SAME robot as the view):
  - Pre-Flight Check: sanity-checks coordinates and workspace.
  - Preview Move: shows what a move WOULD do (using the real pathplan logic) and
    DRAWS the planned path on the 3D view -- without moving the robot.
  - Move Demo Dot To Target: actually moves the dummy to a chosen station.

Real coordinates + drive range from the robot config
(named_position_coords.json + MaxAxisPos). Swap the client in build_robot() for
the real myClient to monitor live.

Run:  uv run monitor_3d.py
"""

import json
import tkinter as tk
from tkinter import ttk, messagebox

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from pathplan import Zone
from dod_dummy import DoDDummy
from dod_safety_tools import preflight_check, preview_move, KEEP_OUT

DRIVE_RANGE = {"X": 254000, "Y": 118000, "Z": 40000}

# Use the SAME zone the safety tools use (single source of truth).
ZONE = {"xmin": KEEP_OUT.xmin, "ymin": KEEP_OUT.ymin, "zmin": KEEP_OUT.zmin,
        "xmax": KEEP_OUT.xmax, "ymax": KEEP_OUT.ymax, "zmax": KEEP_OUT.zmax}

KEY_STATIONS = ["Home", "InteractionPoint", "WashStation1", "WasteStation1",
                "CameraStation", "Eppi1Nozzle1", "Nozzle 4 IP"]
POLL_MS = 300


def load_positions():
    try:
        with open("named_position_coords.json") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"Home": {"X": 253300, "Y": 0, "Z": 0},
                "InteractionPoint": {"X": 17866, "Y": 101160, "Z": 32797}}


STATIONS = load_positions()


def build_robot():
    d = DoDDummy(zone=KEEP_OUT)
    d.connect()
    return d


class Monitor3D:
    def __init__(self, root):
        self.root = root
        self.root.title("DoD Robot 3D Monitor + Safety Tools")
        self.robot = build_robot()

        self._targets = [(n, (c["X"], c["Y"], c["Z"])) for n, c in STATIONS.items()]
        self._ti = 0
        self.nozzle_plot = None
        self.path_plot = []   # line artists for a previewed path

        self._build()
        self._poll()

    def _build(self):
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=8, pady=4)
        self.pos_var = tk.StringVar(value="X=? Y=? Z=?")
        self.disp_var = tk.StringVar(value="?")
        self.last_var = tk.StringVar(value="-")
        ttk.Label(top, text="Position:", font=("Arial", 10, "bold")).pack(side="left")
        ttk.Label(top, textvariable=self.pos_var, font=("Consolas", 10)).pack(side="left", padx=(4, 16))
        ttk.Label(top, text="Dispensing:", font=("Arial", 10, "bold")).pack(side="left")
        ttk.Label(top, textvariable=self.disp_var, font=("Consolas", 10)).pack(side="left", padx=(4, 16))
        ttk.Label(top, text="Last:", font=("Arial", 10, "bold")).pack(side="left")
        ttk.Label(top, textvariable=self.last_var, font=("Consolas", 10)).pack(side="left", padx=4)
        self.demo = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Demo motion", variable=self.demo).pack(side="right")

        tools = ttk.LabelFrame(self.root, text="Automation / Safety Tools")
        tools.pack(fill="x", padx=8, pady=4)
        ttk.Button(tools, text="Run Pre-Flight Check", command=self.run_preflight).pack(side="left", padx=4, pady=4)
        ttk.Label(tools, text="Move target:").pack(side="left", padx=(16, 4))
        self.target_var = tk.StringVar(value="InteractionPoint")
        ttk.Combobox(tools, textvariable=self.target_var, values=list(STATIONS.keys()),
                     width=26).pack(side="left", padx=4)
        ttk.Button(tools, text="Preview Move", command=self.run_preview_move).pack(side="left", padx=4, pady=4)
        ttk.Button(tools, text="Move Demo Dot To Target", command=self.move_demo_to_target).pack(side="left", padx=4, pady=4)

        self.fig = Figure(figsize=(7, 6), dpi=100)
        self.ax = self.fig.add_subplot(111, projection="3d")
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.root)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self._draw_static()

    # ---- tool buttons ----
    def run_preflight(self):
        try:
            passed, total, text = preflight_check()
            messagebox.showinfo("Pre-Flight Check", f"{passed}/{total} checks passed.\n\nSee terminal for details.")
        except Exception as e:
            messagebox.showerror("Pre-Flight Check Error", str(e))

    def run_preview_move(self):
        target = self.target_var.get().strip()
        try:
            # preview uses THIS robot (shared state) and the real pathplan logic
            result = preview_move(self.robot, target)
            self._draw_preview_path(result.get("path"))
            messagebox.showinfo("Move Preview", result["message"].split("===")[-1].strip()
                                if "message" in result else "See terminal.")
        except Exception as e:
            messagebox.showerror("Move Preview Error", str(e))

    def move_demo_to_target(self):
        target = self.target_var.get().strip()
        if target not in STATIONS:
            messagebox.showerror("Unknown Position", f"Unknown target: {target}")
            return
        c = STATIONS[target]
        self.robot.move_absolute(c["X"], c["Y"], c["Z"])
        self.robot.last_position = target

    # ---- drawing ----
    def _draw_preview_path(self, path):
        # clear any old previewed path
        for artist in self.path_plot:
            try:
                artist.remove()
            except Exception:
                pass
        self.path_plot = []
        if not path:
            self.canvas.draw_idle()
            return
        xs = [p[0] for p in path]; ys = [p[1] for p in path]; zs = [p[2] for p in path]
        line, = self.ax.plot(xs, ys, zs, color="#2ecc71", linewidth=2.0, marker="o", markersize=4)
        self.path_plot.append(line)
        self.canvas.draw_idle()

    def _draw_static(self):
        ax = self.ax
        ax.clear()
        rx, ry, rz = DRIVE_RANGE["X"], DRIVE_RANGE["Y"], DRIVE_RANGE["Z"]
        corners = [(0,0,0),(rx,0,0),(rx,ry,0),(0,ry,0),(0,0,rz),(rx,0,rz),(rx,ry,rz),(0,ry,rz)]
        edges = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
        for a, b in edges:
            ax.plot([corners[a][0],corners[b][0]],[corners[a][1],corners[b][1]],
                    [corners[a][2],corners[b][2]], color="#33415c", linewidth=0.8)

        xs = [c["X"] for c in STATIONS.values()]; ys = [c["Y"] for c in STATIONS.values()]; zs = [c["Z"] for c in STATIONS.values()]
        ax.scatter(xs, ys, zs, c="#5dade2", s=18, depthshade=True)
        for name in KEY_STATIONS:
            if name in STATIONS:
                c = STATIONS[name]
                ax.text(c["X"], c["Y"], c["Z"], "  " + name, fontsize=7, color="#2c3e50")

        if "InteractionPoint" in STATIONS:
            ip = STATIONS["InteractionPoint"]
            ax.scatter([ip["X"]],[ip["Y"]],[ip["Z"]], c="#f1c40f", s=90, marker="*", edgecolors="black", linewidths=0.5)
            ax.plot([0, rx],[ip["Y"], ip["Y"]],[ip["Z"], ip["Z"]], color="#e74c3c", linewidth=1.0, linestyle="--", alpha=0.7)

        self._draw_zone_box(ax)
        self._draw_slide_grid(ax)
        ax.set_xlabel("X (um)"); ax.set_ylabel("Y (um)"); ax.set_zlabel("Z (um)")
        ax.set_xlim(0, rx); ax.set_ylim(0, ry); ax.set_zlim(0, rz)
        try:
            ax.set_box_aspect((rx, ry, rz))
        except Exception:
            pass

    def _draw_slide_grid(self, ax):
        # Connect the Slide A1-A6 and B1-B6 grid points with faint lines so the
        # sample-slide structure is recognizable, and label it once.
        for row in ("A", "B"):
            pts = []
            for i in range(1, 7):
                name = f"Slide {row}{i}"
                if name in STATIONS:
                    c = STATIONS[name]
                    pts.append((c["X"], c["Y"], c["Z"]))
            if len(pts) >= 2:
                xs = [p[0] for p in pts]; ys = [p[1] for p in pts]; zs = [p[2] for p in pts]
                ax.plot(xs, ys, zs, color="#9b59b6", linewidth=1.0, alpha=0.7)
        # connect A to B columns too (so it reads as a grid, not two lines)
        for i in range(1, 7):
            a = STATIONS.get(f"Slide A{i}"); b = STATIONS.get(f"Slide B{i}")
            if a and b:
                ax.plot([a["X"], b["X"]], [a["Y"], b["Y"]], [a["Z"], b["Z"]],
                        color="#9b59b6", linewidth=0.6, alpha=0.4)
        # label the grid once (near A1)
        if "Slide A1" in STATIONS:
            c = STATIONS["Slide A1"]
            ax.text(c["X"], c["Y"], c["Z"] + 3000, "  Sample Slide", fontsize=7, color="#9b59b6")

    def _draw_zone_box(self, ax):
        z = ZONE
        c = [(z["xmin"],z["ymin"],z["zmin"]),(z["xmax"],z["ymin"],z["zmin"]),
             (z["xmax"],z["ymax"],z["zmin"]),(z["xmin"],z["ymax"],z["zmin"]),
             (z["xmin"],z["ymin"],z["zmax"]),(z["xmax"],z["ymin"],z["zmax"]),
             (z["xmax"],z["ymax"],z["zmax"]),(z["xmin"],z["ymax"],z["zmax"])]
        edges = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
        for a, b in edges:
            ax.plot([c[a][0],c[b][0]],[c[a][1],c[b][1]],[c[a][2],c[b][2]], color="#e74c3c", linewidth=0.7, alpha=0.6)

    def _step_demo(self):
        if not self.demo.get():
            return
        name, (tx, ty, tz) = self._targets[self._ti]
        p = self.robot.where()
        nx = p.x + (tx - p.x) * 0.4; ny = p.y + (ty - p.y) * 0.4; nz = p.z + (tz - p.z) * 0.4
        self.robot.x, self.robot.y, self.robot.z = nx, ny, nz
        if abs(tx-nx) > 2000 or abs(ty-ny) > 2000 or abs(tz-nz) > 2000:
            self.robot.dispense_on("Trigger")
        if abs(tx-nx) < 2000 and abs(ty-ny) < 2000 and abs(tz-nz) < 2000:
            self.robot.last_position = name
            self.robot.dispense_off()
            self._ti = (self._ti + 1) % len(self._targets)

    def _poll(self):
        self._step_demo()
        p = self.robot.where()
        self.pos_var.set(f"X={p.x:.0f} Y={p.y:.0f} Z={p.z:.0f}")
        self.disp_var.set(self.robot.dispensing_state)
        self.last_var.set(str(self.robot.last_position))
        if self.nozzle_plot is not None:
            try:
                self.nozzle_plot.remove()
            except Exception:
                pass
        self.nozzle_plot = self.ax.scatter([p.x],[p.y],[p.z], c="#e74c3c", s=80, edgecolors="white", linewidths=1.0)
        self.canvas.draw_idle()
        self.root.after(POLL_MS, self._poll)

    def on_close(self):
        try:
            self.robot.disconnect()
        finally:
            self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = Monitor3D(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()