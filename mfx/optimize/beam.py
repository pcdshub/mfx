import traceback
import datetime
from typing import Literal, Optional
import matplotlib.pyplot as plt
from pydantic import validate_call, ConfigDict
import bluesky.plans as bp
from bluesky import RunEngine
from xopt import Xopt
from .errors import FeasibilityError
from .plots import UpdatingDeviceCentroidPathPlot, UpdatingXoptVisualizeModelPlot
from .type_checking import validate_w_lowercase_args, Diagnostics, Methods, Devices, Turbo, Movers
from .user_select import select_diagnostic, select_goal
from .constraints import constraint_data
from bluesky.callbacks.best_effort import BestEffortCallback
from bluesky.callbacks import CallbackBase, LivePlot
import numpy as np
from pcdsdevices.sim import FastMotor
from ophyd import EpicsSignal
from event_model import compose_event_page
from pprint import pprint, pformat
from xopt import Xopt
from bluesky.callbacks.best_effort import BestEffortCallback
from bluesky.callbacks import CallbackBase, LivePlot
import numpy as np
from pcdsdevices.sim import FastMotor
from ophyd import EpicsSignal
from event_model import compose_event_page
from pprint import pprint, pformat

Diagnostics = Literal["xcs1", "dg1", "dg2"]
Methods = Literal["xopt", "blop"]
Devices = Literal["yag", "wave8"]
Turbo = Literal["safety", "optimize"]


def validate_w_lowercase_args(func):
    """
    Decorator to make string inputs lowercase, and then validate.

    Parameters:
    -----------
    func (Callable): 
        The function to decorate.

    Returns:
    --------
    Callable: 
        The decorated function with string arguments converted to lowercase.
    """
    def wrapper(*args, **kwargs):
        # Convert all string arguments to lowercase
        new_args = tuple(arg.lower() if isinstance(arg, str) else arg for arg in args)
        new_kwargs = {k: v.lower() if isinstance(v, str) else v for k, v in kwargs.items()}

        # Call the original function with the modified arguments, validated by Pydantic
        validated_func = validate_call(func, config=ConfigDict(validate_default=True))
        return validated_func(*new_args, **new_kwargs)

    return wrapper

class FeasibilityError(Exception):
    """
    A custom exception class to tell users when no Xopt sample points are feasible,
    e.g. due to the constraints being too tight.
    """
    pass


class Beam:
    @validate_call
    def __init__(self, mirror_pitch: list[float] = [-549.0, -546.0]):
        self.mirror_pitch: list[float] = mirror_pitch
        try:
            from mfx.db import RE
        except ImportError:
            RE = RunEngine({})
        self.RE = RE
        #self.RE.subscribe(BestEffortCallback())

    @validate_w_lowercase_args
    def align(
            self,
            with_goal: Optional[float] = None,
            on_diagnostic: Diagnostics = "dg1",
            with_method: Methods = "xopt",
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
            num_frames: int = 1
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
        """
        # Validate goal with not doing 2d optimization using camera markers
        if (using_device=="wave8" or not use_2d_markers) and not with_goal:
            raise ValueError("Must provide parameter with_goal (float) for running YAG or wave8 optimization.")

        path_plot = None
        if with_method == "xopt":
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
                    path_plot = UpdatingDeviceCentroidPathPlot(
                        imager=select_diagnostic("yag", on_diagnostic),
                        goal=select_goal(
                            device_type=using_device,
                            location=on_diagnostic,
                            goal=with_goal,
                            goal_2d=with_goal_2d,
                            use_2d_markers=use_2d_markers,
                        ),
                        constraints=constraint_data.yag.get(on_diagnostic),
                    )
                    xopt._cached_path_plot = path_plot
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
        elif with_method == "blop":
            from .blop_scans import get_blop_agent
            agent = get_blop_agent(on_diagnostic.lower(), wave8_xpos=with_goal)
            self.RE(agent.learn("qr", n=blop_qr_n))
            self.RE(agent.learn("qei", n=blop_qei_n, iterations=blop_qei_iterations))
            self.RE(agent.go_to_best())
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
        mirror_pitch_start = mirror_pitch_start or self.mirror_pitch[0]
        mirror_pitch_end = mirror_pitch_end or self.mirror_pitch[1]
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

# this is the plan then apply runengine OUTSIDE RE(beam.focus)
# yield from plan
# IP - inflection point
# IPM - device for measuring position of beam (not real sensor but a way to measure and understand where beam is)
# YAG - Yttrium Aluminum Garnet laser

    def focus(
            self,
            with_goal: float,
            on_diagnostic: Diagnostics = "ip",
            with_method: Methods = "xopt",
            using_device: Devices = "yag",
            tfs_positions: list[float] = np.arange(1,6,1)
    ):
        # tfs_translation = FastMotor()
        #det = EpicsSignal('MFX:GIGE:02:IMAGE1:ArrayData', name='gige-cam')
        from ophyd.sim import det, motor as tfs_translation
        #self.RE.subscribe(AggLivePlot(y=det.name, x=tfs_translation.name))
        self.RE.subscribe(print)
        self.RE(bp.scan([det], tfs_translation, tfs_positions[0], tfs_positions[-1], len(tfs_positions)))
        

class AggLivePlot(LivePlot):
    def __init__(self, num_points: int = 5, *args, **kwargs):
        self.num_points = num_points
        self._cached_events = []
        self._descriptor = None
        super().__init__(*args, **kwargs)
    
    def descriptor(self, doc):
        print(f"\n\n\ndescription\n{pformat(doc)}")
        self._descriptor = doc
        super().descriptor(doc)
    
    def event(self, doc):
        print(f"\n\n\nevent\n{pformat(doc)}")
        self._cached_events.append(doc)
        if len(self._cached_events) >= self.num_points:
            new_doc = compose_event_page(self._descriptor["uid"], self.num_points, self._cached_events,{}, [])
            print(f"\n\n\nevent new doc\n{pformat(new_doc)}")
            super().event_page(new_doc)
            self._cached_events = []
            
    # def event_page(self, doc):
    #     if len(self._cached_events) > self.num_points:
    #         new_doc = compose_event_page(self._descriptor["uid"], self.num_points, self._cached_events,{}, [])
    #         print(f"\n\n\nevent page\n{pformat(new_doc)}")
    #         super().event_page(new_doc)

    
    @validate_w_lowercase_args
    def scan(
            self,
            on_diagnostic: Diagnostics = "dg1",
            using_device: Devices = "yag",
            mirror_pitch_start = self.mirror_pitch[0],
            mirror_pitch_end = self.mirror_pitch[1],
            num_steps: int = 51,
            sequencer_fps: int = 120,
            num_events_per_step: int = 120,
            record: bool = True
            ):
        """Perform Beam Alignment

        Parameters
        ----------
        on_diagnostic : str, optional
            Diagnostic to use for alignment. Options: "xcs1, dg1, dg2". Default is "dg1".
        using_device : str, optional
            Device to use for alignment. Options: "yag, wave8". Default is "yag".
        mirror_pitch_start : int, optional
            Starting mirror pitch for scan.
        mirror_pitch_end : int, optional
            Final mirror pitch for scan.
        num_steps : int, optional
            Number of steps in scan.
        sequencer_fps : int, optional
            Sequencer rate in fps.
        num_events_per_step : int, optional
            Number of events to record per step.
        record : bool, optional
            Whether to record or not.
        """
        try:
            from mfx.db import RE
        except ImportError:
            RE = RunEngine({})

        try:
            from mfx.db import daq
        except ImportError:
            print("> access to the daq is required to scan the beam.")

        from .xopt_scans import init_devices

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
                daq,
                init_devices()["mr1l4_homs"].pitch,
                mirror_pitch_start,
                mirror_pitch_end,
                num_steps,
                events=num_events_per_step,
                record=record
            )
        )
