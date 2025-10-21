import traceback
import datetime
import time
import json
from typing import Optional
import numpy as np
import pandas as pd
from pathlib import Path
from pydantic import validate_call
from bluesky import RunEngine
from xopt import Xopt
from sklearn.linear_model import LinearRegression
from .errors import FeasibilityError
from .plots import UpdatingDeviceCentroidPathPlot, UpdatingXoptVisualizeModelPlot
from .type_checking import validate_w_lowercase_args, Diagnostics, Methods, Devices, Turbo, Movers
from .user_select import select_diagnostic, select_goal, MP_KEY, UNDP_KEY_X, UNDP_KEY_Y
from .constraints import constraint_data
from .utils import snake_order

class Beam:

    def _predict_centroid(self, undp_xy: tuple[float, float], calib: dict) -> tuple[float, float]:
        """Predict centroid from undulator position using calibration coefficients."""
        a0, a1, a2 = calib["coeff_x"]
        b0, b1, b2 = calib["coeff_y"]
        ux, uy = undp_xy
        pred_x = a0 + a1 * ux + a2 * uy
        pred_y = b0 + b1 * ux + b2 * uy
        return (float(pred_x), float(pred_y))

    def _undp_solve(self, goal: tuple[float, float], calib: dict) -> tuple[float, float]:
        """
        Solve for undp_x, undp_y that achieve target centroid given calibration.
        """
        a0, a1, a2 = calib["coeff_x"]
        b0, b1, b2 = calib["coeff_y"]
        M = np.array([[a1, a2], [b1, b2]], dtype=float)
        rhs = np.array([goal[0] - a0, goal[1] - b0], dtype=float)
        sol = np.linalg.solve(M, rhs)
        return (float(sol[0]), float(sol[1]))

    
    def _save_calibration_plots(self, res, reg_x, reg_y, out_dir, on_diagnostic, ts):
        """Save calibration plots to file."""
        plot_path = None
        try:
            import matplotlib.pyplot as plt
            fig, axs = plt.subplots(2, 2, figsize=(10, 8))

            undp_x = res[UNDP_KEY_X]
            undp_y = res[UNDP_KEY_Y]
            cent_x = res["centroid_x"]
            cent_y = res["centroid_y"]

            undp_x_range = np.linspace(undp_x.min(), undp_x.max(), 100)
            undp_y_range = np.linspace(undp_y.min(), undp_y.max(), 100)
            undp_x_mean = float(undp_x.mean())
            undp_y_mean = float(undp_y.mean())

            # centroid_x vs undp_x (vary undp_x, hold undp_y at mean)
            axs[0, 0].scatter(undp_x, cent_x, s=20)
            X_line = np.column_stack([undp_x_range, np.full_like(undp_x_range, undp_y_mean)])
            axs[0, 0].plot(undp_x_range, reg_x.predict(X_line), 'r--', linewidth=1)
            axs[0, 0].set_xlabel("undp_x [um]")
            axs[0, 0].set_ylabel("centroid_x [px]")
            axs[0, 0].set_title("centroid_x vs undp_x")

            # centroid_x vs undp_y (vary undp_y, hold undp_x at mean)
            axs[0, 1].scatter(undp_y, cent_x, s=20, color="orange")
            X_line = np.column_stack([np.full_like(undp_y_range, undp_x_mean), undp_y_range])
            axs[0, 1].plot(undp_y_range, reg_x.predict(X_line), 'r--', linewidth=1)
            axs[0, 1].set_xlabel("undp_y [um]")
            axs[0, 1].set_ylabel("centroid_x [px]")
            axs[0, 1].set_title("centroid_x vs undp_y")

            # centroid_y vs undp_x (vary undp_x, hold undp_y at mean)
            axs[1, 0].scatter(undp_x, cent_y, s=20, color="green")
            Y_line = np.column_stack([undp_x_range, np.full_like(undp_x_range, undp_y_mean)])
            axs[1, 0].plot(undp_x_range, reg_y.predict(Y_line), 'r--', linewidth=1)
            axs[1, 0].set_xlabel("undp_x [um]")
            axs[1, 0].set_ylabel("centroid_y [px]")
            axs[1, 0].set_title("centroid_y vs undp_x")

            # centroid_y vs undp_y (vary undp_y, hold undp_x at mean)
            axs[1, 1].scatter(undp_y, cent_y, s=20, color="purple")
            Y_line = np.column_stack([np.full_like(undp_y_range, undp_x_mean), undp_y_range])
            axs[1, 1].plot(undp_y_range, reg_y.predict(Y_line), 'r--', linewidth=1)
            axs[1, 1].set_xlabel("undp_y [um]")
            axs[1, 1].set_ylabel("centroid_y [px]")
            axs[1, 1].set_title("centroid_y vs undp_y")

            fig.tight_layout()
            plot_path = str(out_dir / f"calib_scatter_{on_diagnostic}_{ts}.png")
            fig.savefig(plot_path, dpi=120)
            plt.close(fig)
            print(f"[calibrate] Wrote scatter plot: {plot_path}")
        except Exception as exc:
            print(f"[calibrate] Warning: failed to save plot: {exc}")
        return plot_path

    def _load_calibration(self, on_diagnostic: Diagnostics) -> Optional[dict]:
        """Load most recent calibration coefficients for the given diagnostic."""
        try:
            root = Path(__file__).parent.parent.parent / "logs" / "xopt" / "calibration"
            root.mkdir(parents=True, exist_ok=True)
            candidates = sorted(root.glob(f"calib_{on_diagnostic}_und_yag_*.json"))
            if not candidates:
                return None
            with open(candidates[-1], "r") as f:
                return json.load(f)
        except Exception:
            return None

    def check_calibration(
        self,
        on_diagnostic: Diagnostics = "dg1",
        xopt_obj: Optional[Xopt] = None,
        threshold_sigma: float = 2.0,
    ) -> bool:
        """
        Predict centroid from current undp_x, undp_y using latest calibration.
        Return True if error < threshold_sigma * calibration sigma, else False.
        """
        calib = self._load_calibration(on_diagnostic)
        if calib is None:
            print(f"[check_calibration] No calibration found for {on_diagnostic}")
            return False
        print(f"[check_calibration] Loading calibration for {on_diagnostic} from {calib.get('timestamp')}")
        try:
            from .xopt_scans import init_devices
            und = init_devices()["und_abs"]
            curr_xy = (float(und.xpos.get()), float(und.ypos.get()))
        except Exception:
            print(f"[check_calibration] Failed to get current undulator position")
            return False

        pred = self._predict_centroid(curr_xy, calib)

        if xopt_obj is None:
            print(f"[check_calibration] No xopt_obj provided")
            return False
        df_curr = pd.DataFrame([{UNDP_KEY_X: curr_xy[0], UNDP_KEY_Y: curr_xy[1]}])
        res = xopt_obj.evaluate_data(df_curr)
        meas = (float(res["centroid_x"].iat[-1]), float(res["centroid_y"].iat[-1]))

        err = float(np.hypot(pred[0] - meas[0], pred[1] - meas[1]))
        expected_error = float(calib["sigma_px"])
        return err < threshold_sigma * expected_error


    @validate_w_lowercase_args
    def calibrate(
        self,
        xopt_obj: Xopt,
        on_diagnostic: Diagnostics = "dg1",
        grid_bins: int = 5,
    ) -> dict:
        """
        Run grid scan over undp_x/undp_y, fit linear model, save coefficients.
        Returns the calibration dict.
        """
        # Set safe bounds for undulator
        xopt_obj.vocs.variables[UNDP_KEY_X] = [0, 200]
        xopt_obj.vocs.variables[UNDP_KEY_Y] = [-450, -200]

        # Build grid in the VOCS variable space, then evaluate via connected evaluator
        df_grid = xopt_obj.vocs.grid_inputs(n=grid_bins)
        print(f"[calibrate] Grid inputs generated: shape={df_grid.shape}")
        df_snake = snake_order(df_grid)
        print(f"[calibrate] Snaked grid: shape={df_snake.shape}")
        res = xopt_obj.evaluate_data(df_snake)
        print(f"[calibrate] Evaluated snaked grid: shape={res.shape}; columns={list(res.columns)}")
        print(res.head())

        print(f"[calibrate] Fitting linear regression models...")
        X = res[[UNDP_KEY_X, UNDP_KEY_Y]].to_numpy(dtype=float)
        yx = res["centroid_x"].to_numpy(dtype=float)
        yy = res["centroid_y"].to_numpy(dtype=float)
        
        reg_x = LinearRegression().fit(X, yx)
        reg_y = LinearRegression().fit(X, yy)
        
        coeff_x = np.concatenate([[reg_x.intercept_], reg_x.coef_])
        coeff_y = np.concatenate([[reg_y.intercept_], reg_y.coef_])

        pred_x = reg_x.predict(X)
        pred_y = reg_y.predict(X)
        err_px = np.hypot(pred_x - yx, pred_y - yy)
        sigma_px = float(np.std(err_px))
        sigma_x = float(np.std(pred_x - yx))
        sigma_y = float(np.std(pred_y - yy))

        print(f"[calibrate] coeff_x: a0={float(coeff_x[0]):.3f}, a1={float(coeff_x[1]):.3f}, a2={float(coeff_x[2]):.3f}")
        print(f"[calibrate] coeff_y: b0={float(coeff_y[0]):.3f}, b1={float(coeff_y[1]):.3f}, b2={float(coeff_y[2]):.3f}")
        print(f"[calibrate] sigma_px={sigma_px:.2f}, sigma_x={sigma_x:.2f}, sigma_y={sigma_y:.2f}")

        ts = datetime.datetime.now().strftime("%y-%m-%d-%H:%M:%S")
        out_dir = Path(__file__).parent.parent.parent / "logs" / "xopt" / "calibration"
        out_dir.mkdir(parents=True, exist_ok=True)
        grid_csv = None
        try:
            grid_csv = str(out_dir / f"calib_grid_{on_diagnostic}_{ts}.csv")
            res[[UNDP_KEY_X, UNDP_KEY_Y, "centroid_x", "centroid_y"]].to_csv(grid_csv, index=False)
            print(f"[calibrate] Wrote grid preview CSV: {grid_csv}")
        except Exception as exc:
            print(f"[calibrate] Warning: failed to write grid CSV: {exc}")

        plot_path = self._save_calibration_plots(
            res=res,
            reg_x=reg_x,
            reg_y=reg_y,
            out_dir=out_dir,
            on_diagnostic=on_diagnostic,
            ts=ts,
        )

        calib = {
            "diagnostic": on_diagnostic,
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "coeff_x": [float(v) for v in coeff_x.tolist()],
            "coeff_y": [float(v) for v in coeff_y.tolist()],
            "sigma_px": sigma_px,
            "sigma_x": sigma_x,
            "sigma_y": sigma_y,
            "grid_bins": int(grid_bins),
            "grid_csv": grid_csv,
            "plot_path": plot_path,
        }
        out_path = out_dir / f"calib_{on_diagnostic}_und_yag_{ts}.json"
        try:
            with open(out_path, "w") as f:
                json.dump(calib, f, indent=2)
        except Exception:
            # Best-effort persistence; continue even if write fails
            ...
        return calib


    def _calib(self, xopt, goal, on_diagnostic, using_device, mover, grid_bins=5):
        """Calibrate, fit linear model, solve for undulator position"""
        if mover != "und":
            raise ValueError(f"Only 'und' mover is supported for calibration.")
        if using_device != "yag":
            raise ValueError(f"Only 'yag' device is supported for calibration.")
        if not isinstance(goal, tuple) or len(goal) != 2:
            raise ValueError(f"Goal must be a tuple of two floats.")

        from .xopt_scans import evaluator_move
        
        print(f"[_calib] Checking calibration freshness...")
        fresh = self.check_calibration(on_diagnostic=on_diagnostic, xopt_obj=xopt, threshold_sigma=2.0)
        if fresh: 
            calib = self._load_calibration(on_diagnostic)
            print(f"[_calib] Calibration is fresh, using calibration from {calib.get('timestamp')}")
        else:
            print(f"[_calib] Calibration is stale, running calibrate() with grid_bins={grid_bins}...")
            calib = self.calibrate(xopt_obj=xopt, on_diagnostic=on_diagnostic, grid_bins=grid_bins)

        print(f"[_calib] Solving for undulator position to achieve goal {goal}...")
        undp_xy = self._undp_solve(goal, calib)
        print(f"[_calib] Moving to undulator position {undp_xy}...")
        evaluator_move(mover=mover, input={UNDP_KEY_X: undp_xy[0], UNDP_KEY_Y: undp_xy[1]})
        return xopt

    def _turbo(self, xopt, path_plot, xopt_rand_evaluate, xopt_steps, mover, xopt_turbo_option):
        """Execute turbo optimization method."""
        from .xopt_scans import evaluator_move, get_variables
        
        xopt.random_evaluate(
            n_samples=xopt_rand_evaluate,
            custom_bounds=get_variables(mover=mover, narrow=True),
        )
        print(xopt.data)
        xopt_eval_plot = UpdatingXoptVisualizeModelPlot(xopt)

        # Seed the path plot with all the random points
        if path_plot is not None:
            x_series = xopt.data.get("centroid_x")
            y_series = xopt.data.get("centroid_y")
            path_plot.add_points([(xpt, ypt) for xpt, ypt in zip(x_series, y_series)])

        for num in range(xopt_steps):
            print(f"Step {num + 1}")
            try:
                xopt.step()
                xopt_eval_plot.refresh()
                if path_plot is not None:
                    path_plot.add_point(
                        (xopt.data.get("centroid_x").iat[-1], xopt.data.get("centroid_y").iat[-1])
                    )
            except RuntimeError:
                trb = traceback.format_exc()
                if "turbo requires at least one valid point in the training dataset" in str(trb):
                    raise FeasibilityError(
                        f"No feasible points within acceptable region. "
                        f"Try adjusting constraints in 'xopt_scans.get_xopt_obj'.\n"
                        f"Current constraints: {xopt.vocs.constraints}"
                    )
                else:
                    # Raise if it's something else
                    raise
            except ValueError:
                trb = traceback.format_exc()
                if xopt_turbo_option == "safety" and "no data available to build model" in str(trb):
                    raise FeasibilityError(
                        f"No feasible points within TuRBO trust region. "
                        f"Try adjusting constraints in 'xopt_scans.get_xopt_obj'.\n"
                        f"Current constraints: {xopt.vocs.constraints}"
                    )
                else:
                    # Raise if it's something else
                    raise

            print(xopt.data)
        try:
            _, val, params = xopt.vocs.select_best(xopt.data)
        except IndexError:
            # Make error more user-friendly/readable
            raise FeasibilityError(
                f"No feasible points within acceptable region. "
                f"Try adjusting constraints in 'xopt_scans.get_xopt_obj'.\n"
                f"Current constraints: {xopt.vocs.constraints}"
            )

        print(f"Best objective value {val}")
        print(f"Best point {params}")
        evaluator_move(
            mover=mover,
            input=params,
        )
        ax = xopt.data.plot(y=xopt.vocs.objective_names)
        ax.set_xlabel("steps")
        ax.set_ylabel("objective (to minimize)")
        xopt_eval_plot.refresh()
        if path_plot is not None:
            path_plot.refresh()
        return xopt

    @validate_w_lowercase_args
    def align(
            self,
            with_goal: Optional[float] = None,
            on_diagnostic: Diagnostics = "dg1",
            with_package: Methods = "xopt",
            with_method: str = "turbo",
            using_device: Devices = "yag",
            mover: Movers = "mirr",
            xopt_turbo_option: Turbo = "safety",
            xopt_rand_evaluate: int = 3,
            xopt_steps: int = 10,
            xopt_max_iter: int = 2000,
            blop_qr_n: int = 16,
            blop_qei_n: int = 16,
            blop_qei_iterations: int = 5,
            use_2d_markers: bool = False,
            with_goal_2d: Optional[tuple[float, float]] = None,
            xopt_obj: Optional[Xopt] = None,
            save_run: bool = True,
            num_frames: int = 1,
            grid_bins: int = 5
            ):
        """Perform Beam Alignment

        Parameters
        ----------
        with_goal : float, optional
            1D Goal to align to. This can be omitted if other goal arguments are used.
        on_diagnostic : str, optional
            Diagnostic to use for alignment. Options: "xcs1, dg1, dg2". Default is "dg1".
        with_package : str, optional
            Package to use for alignment. Options: "blop, xopt". Default is "xopt".
        with_method : str, optional
            Method to use for optimization. Options: "turbo, calib". Default is "turbo".
        using_device : str, optional
            Device to use for alignment. Options: "yag, wave8". Default is "yag".
        mover : str, optional
            Motion device to steer the beam. Options: "mirr, und". Default is "mirr".
        xopt_turbo_option : str, optional
            Xopt turbo controller option. Options: "safety, optimize". Default is "safety".
        xopt_rand_evaluate : int, optional
            Number of random evaluations to perform in Xopt. Default is 3.
        xopt_steps : int, optional
            Number of steps to perform in Xopt. Default is 10.
        xopt_max_iter: int, optional
            Max number of steps for maximizing the acquisition function in Xopt. Default is 2000.
        blop_qr_n : int, optional
            Number of qr iterations to perform in blop. Default is 16.
        blop_qei_n : int, optional
            Number of qei iterations to perform in blop. Default is 16.
        blop_qei_iterations : int, optional
            Number of iterations to perform in blop. Default is 5.
        use_2d_markers: bool, optional
            Run a 2D YAG optimization using camera markers. Default is False.
        with_goal_2d: tuple(float, float), optional
            The 2D optimization goal if running a 2D YAG optimization. Default is False.
        save_run: bool, optional
            Save the Xopt run to YAML. Default is True.
        num_frames: int, optional
            Number of frames to average for YAG image collection. Default is 1 (no averaging).
            Only applies when using_device is "yag".
        grid_bins: int, optional
            Number of grid bins for calibration. Default is 5.
        """
        # Validate goal with not doing 2d optimization using camera markers
        if (using_device=="wave8" or not use_2d_markers) and not with_goal:
            raise ValueError("Must provide parameter with_goal (float) for running YAG or wave8 optimization.")

        path_plot = None
        if with_package == "xopt":
            from .xopt_scans import get_xopt_obj, evaluator_move, get_variables
            # Allow the loading of an already instantiated xopt object, e.g. to take more steps
            if xopt_obj:
                print("Using existing Xopt object.")
                xopt = xopt_obj
                try:
                    old_path_plot = xopt._cached_path_plot
                except AttributeError:
                    ...
                else:
                    print("Generating new path plot from cached settings")
                    path_plot = UpdatingDeviceCentroidPathPlot(
                        imager=old_path_plot.imager,
                        goal=old_path_plot.goal,
                        constraints=old_path_plot.constraints,
                    )
            else:
                print("Loading Xopt object.")
                if save_run:
                    now = datetime.datetime.now()
                    formatted_string = now.strftime("%y-%m-%d-%H:%M:%S")
                    filename  = f"xopt_run_{on_diagnostic}_{using_device}_{mover}_{formatted_string}.yaml"
                    # The logs folder at the root of the repo should exist and be writeable
                    logs_folder = Path(__file__).parent.parent.parent / "logs" / "xopt"
                    logs_folder.mkdir(parents=True, exist_ok=True)
                    dump_file = str(logs_folder / filename)
                xopt = get_xopt_obj(
                    device_type=using_device,
                    location=on_diagnostic,
                    mover=mover,
                    goal=with_goal,
                    xopt_generator_turbo_controller=xopt_turbo_option,
                    use_2d_markers=use_2d_markers,
                    goal_2d=with_goal_2d,
                    max_iter=xopt_max_iter,
                    dump_file=dump_file,
                    num_frames=num_frames,
                )
                if using_device == "yag":
                    print("Generating path plot")
                    goal = select_goal(
                            device_type=using_device,
                            location=on_diagnostic,
                            goal=with_goal,
                            goal_2d=with_goal_2d,
                            use_2d_markers=use_2d_markers,
                        )
                    path_plot = UpdatingDeviceCentroidPathPlot(
                        imager=select_diagnostic("yag", on_diagnostic),
                        goal= goal,
                        constraints=constraint_data.yag.get(on_diagnostic),
                    )
                    xopt._cached_path_plot = path_plot
            if with_method == "turbo":
                return self._turbo(xopt, path_plot, xopt_rand_evaluate, xopt_steps, mover, xopt_turbo_option)
            elif with_method == "calib":
                return self._calib(
                    xopt=xopt,
                    goal=goal,
                    on_diagnostic=on_diagnostic,
                    using_device=using_device,
                    mover=mover,
                    grid_bins=grid_bins,
                )
            else:
                raise ValueError(f"Invalid method: {with_method}. Only 'turbo' and 'calib' are supported.")
        elif with_package == "blop":
            from .blop_scans import get_blop_agent
            try:
                from mfx.db import RE
            except ImportError:
                RE = RunEngine({})
            agent = get_blop_agent(on_diagnostic.lower(), wave8_xpos=with_goal)
            RE(agent.learn("qr", n=blop_qr_n))
            RE(agent.learn("qei", n=blop_qei_n, iterations=blop_qei_iterations))
            RE(agent.go_to_best())
            agent.plot_objectives()
            return agent
        else:
            raise ValueError("Only 'xopt' and 'blop' packages are supported.")

    @validate_w_lowercase_args
    def scan(
            self,
            on_diagnostic: Diagnostics = "dg1",
            using_device: Devices = "yag",
            mirror_pitch_start = None,
            mirror_pitch_end = None,
            num_steps: int = 51,
            sequencer_fps: int = 120
            ):
        """Perform Beam Scan

        Parameters
        ----------
        on_diagnostic : str, optional
            Diagnostic to use for alignment. Options: "xcs1, dg1, dg2". Default is "dg1".
        using_device : str, optional
            Device to use for alignment. Options: "yag, wave8". Default is "yag".
        mirror_pitch_start : int, optional
            Starting mirror pitch for scan. Default is mirror_pitch[0].
        mirror_pitch_end : int, optional
            Final mirror pitch for scan. Default is mirror_pitch[1]/
        num_steps : int, optional
            Number of steps in scan. Default is 51.
        sequencer_fps : int, optional
            Sequencer rate in fps. Default is 120.
        """
        try:
            from mfx.db import RE
        except ImportError:
            RE = RunEngine({})

        try:
            import bluesky.plans as bp
        except ImportError:
            print("could not import bp")

        try:
            from mfx.db import daq
        except ImportError:
            print("> access to the daq is required to scan the beam.")

        from .xopt_scans import init_devices

        if mirror_pitch_start is None:
            mirror_pitch_start = self.mirror_pitch[0]
        if mirror_pitch_end is None:
            mirror_pitch_end = self.mirror_pitch[1]

        if using_device == "yag":
            from mfx.autorun import ioc_cam_recorder
            num_events_per_step=120
            cam_pv = f"MFX:GIGE:{on_diagnostic.upper()}:YAG:"
            cam_record_length = 1.5 * num_steps * num_events_per_step / sequencer_fps
            tag = f"{on_diagnostic}_mr1l4_scan"
            ioc_cam_recorder(cam_pv,
                             cam_record_length,
                             tag=tag)
            print(f"beam.scan: writing {tag} to /cds/data/iocData while scanning...")

        RE(
            bp.scan(
                [daq],
                init_devices()["mr1l4_homs"].pitch,
                mirror_pitch_start,
                mirror_pitch_end,
                num_steps
            )
        )

class Crystal:
    @validate_call
    def __init__(self, name: str = "c1", dof: str = "x"):
        self.crystal_name_list = ["c1","c2","c3","c4","c5","c6"]
        self.crystal_dof_list = ["x", "rot", "tilt"]

        self.name = None
        if name in self.crystal_name_list:
            self.name: str = name

        self.dof = None
        if dof in self.crystal_dof_list:
            self.dof: str = dof

        if self.dof == "x":
            self.boundaries: list[float] = [0., 78.]
        elif self.dof == "rot":
            self.boundaries: list[float] = [10., 30.]
        elif self.dof == "tilt":
            self.boundaries: list[float] = [10., 30.]


    @validate_w_lowercase_args
    def scan(
            self,
            scan_start=None, #self.boundaries[0],
            scan_end=None, #self.boundaries[1],
            num_steps: int = 51
    ):
        """Perform Crystal Scan

        Parameters
        ----------
        scan_start : int, optional
            Starting mirror pitch for scan. Default is mirror_pitch[0].
        scan_end : int, optional
            Final mirror pitch for scan. Default is mirror_pitch[1]/
        num_steps : int, optional
            Number of steps in scan. Default is 51.
        """
        try:
            from mfx.db import RE
        except ImportError:
            RE = RunEngine({})

        try:
            import bluesky.plans as bp
        except ImportError:
            print("could not import bp")

        try:
            from mfx.db import daq
        except ImportError:
            print("> access to the daq is required to scan the beam.")

        from .xopt_scans import init_devices

        RE(
            bp.scan(
                [daq],
                getattr(getattr(init_devices()["mfx_von_hamos_6crystal"],self.name),self.dof),
                scan_start,
                scan_end,
                num_steps
            )
        )
