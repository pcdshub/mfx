import traceback
import datetime
from typing import Optional
import matplotlib.pyplot as plt
from pydantic import validate_call
from bluesky import RunEngine
from xopt import Xopt
from .errors import FeasibilityError
from .plots import UpdatingDeviceCentroidPathPlot, UpdatingXoptVisualizeModelPlot, refresh_mpl_plots
from .type_checking import validate_w_lowercase_args, Diagnostics, Methods, Devices, Turbo
from .user_select import select_diagnostic, select_goal


class Beam:
    @validate_call
    def __init__(self, mirror_pitch: list[float] = [-549.0, -546.0]):
        self.mirror_pitch: list[float] = mirror_pitch

    @validate_w_lowercase_args
    def align(
            self,
            with_goal: Optional[float] = None,
            on_diagnostic: Diagnostics = "dg1",
            with_method: Methods = "xopt",
            using_device: Devices = "yag",
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
            save_run: bool = True
            ):
        """Perform Beam Alignment

        Parameters
        ----------
        with_goal : float, optional
            1D Goal to align to. This can be omitted if other goal arguments are used.
        on_diagnostic : str, optional
            Diagnostic to use for alignment. Options: "xcs1, dg1, dg2". Default is "dg1".
        with_method : str, optional
            Method to use for alignment. Options: "blop, xopt". Default is "xopt".
        using_device : str, optional
            Device to use for alignment. Options: "yag, wave8". Default is "yag".
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
        """
        # Validate goal with not doing 2d optimization using camera markers
        if (using_device=="wave8" or not use_2d_markers) and not with_goal:
            raise ValueError("Must provide parameter with_goal (float) for running YAG or wave8 optimization.")

        path_plot = None
        if with_method == "xopt":
            from .xopt_scans import get_xopt_obj, init_devices
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
                    )
            else:
                print("Loading Xopt object.")
                xopt = get_xopt_obj(
                    device_type=using_device,
                    location=on_diagnostic,
                    goal=with_goal,
                    xopt_generator_turbo_controller=xopt_turbo_option,
                    use_2d_markers=use_2d_markers,
                    goal_2d=with_goal_2d,
                    max_iter=xopt_max_iter
                )
                customized_boundaries = {"mirror_pitch": self.mirror_pitch}
                if using_device == "yag":
                    print("Generating path plot")
                    path_plot = UpdatingDeviceCentroidPathPlot(
                        imager=select_diagnostic("yag", on_diagnostic),
                        goal=select_goal(
                            device_type=using_device,
                            location=on_diagnostic,
                            goal=with_goal,
                            goal_2d=with_goal_2d,
                            use_2d_markers=use_2d_markers,
                        ),
                    )
                    xopt._cached_path_plot = path_plot
                xopt.random_evaluate(xopt_rand_evaluate, custom_bounds=customized_boundaries)
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
            mirror_pitch = init_devices()["mr1l4_homs"].pitch
            mirror_pitch.set(params["mirror_pitch"]).wait(timeout=20)
            print(f"pitch is at {mirror_pitch.position}")
            if save_run:
                now = datetime.datetime.now()
                formatted_string = now.strftime("%y-%m-%d-%H:%M:%S")
                filename  = f"xopt_run_{on_diagnostic}_{using_device}_{formatted_string}.yaml"
                xopt.dump(filename)
            ax = xopt.data.plot(y=xopt.vocs.objective_names)
            ax.set_xlabel("steps")
            ax.set_ylabel("mirror pitch")
            xopt_eval_plot.refresh()
            if path_plot is not None:
                path_plot.refresh()
            return xopt
        elif with_method == "blop":
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
            raise ValueError("Only 'xopt' and 'blop' methods are supported.")

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
            scan_start=self.boundaries[0],
            scan_end=self.boundaries[1],
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
        num_events_per_step : int, optional
            Number of events to record per step. Default is 120.
        record : bool, optional
            Whether to record or not. Default is True.
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
