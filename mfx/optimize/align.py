from typing import Literal
from pydantic import validate_call, ConfigDict
from bluesky import RunEngine


Diagnostics = Literal["xcs1", "dg1", "dg2"]
Methods = Literal["xopt", "blop"]
Devices = Literal["yag", "wave8"]
Turbo = Literal["safety", "optimize"]


def validate_w_lowercase_args(func):
    """
   Decorator to make string inputs lowercase before validating.

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


class Align:
    @validate_call
    def __init__(self, mirror_pitch: list[float] = [-549.0, -546.0]):
        self.mirror_pitch: list[float] = mirror_pitch

    @validate_w_lowercase_args
    def beam(
            self,
            with_goal: float,
            on_diagnostic: Diagnostics = "dg1",
            with_method: Methods = "xopt",
            using_device: Devices = "yag",
            xopt_turbo_option: Turbo = "safety",
            xopt_rand_evaluate: int = 3,
            xopt_steps: int = 10,
            blop_qr_n: int = 16,
            blop_qei_n: int = 16,
            blop_qei_iterations: int = 5
            ):
        """Perform Beam Alignment

        Parameters
        ----------
        with_goal : float
            Goal to align to.
        on_diagnostic : str, optional
            Diagnostic to use for alignment. Options: "XCS1, DG1, DG2". Default is "dg1".
        with_method : str, optional
            Method to use for alignment. Options: "blop, Xopt". Default is "xopt".
        using_device : str, optional
            Device to use for alignment. Options: "yag, wave8". Default is "yag".
        xopt_turbo_option : str, optional
            Xopt turbo controller option. Options: "safety, optimize". Default is "safety".
        xopt_rand_evaluate : int, optional
            Number of random evaluations to perform in Xopt. Default is 3.
        xopt_steps : int, optional
            Number of steps to perform in Xopt. Default is 10.
        blop_qr_n : int, optional
            Number of qr iterations to perform in blop. Default is 16.
        blop_qei_n : int, optional
            Number of qei iterations to perform in blop. Default is 16.
        blop_qei_iterations : int, optional
            Number of iterations to perform in blop. Default is 5.
        """
        if with_method == "xopt":
            from .xopt_scans import get_xopt_obj, init_devices
            xopt = get_xopt_obj(
                device_type=using_device,
                location=on_diagnostic,
                goal=with_goal,
                xopt_generator_turbo_controller=xopt_turbo_option,
            )
            customized_boundaries = {"mirror_pitch": self.mirror_pitch}
            xopt.random_evaluate(xopt_rand_evaluate, custom_bounds=customized_boundaries)
            print(xopt.data)
            for num in range(xopt_steps):
                print(f"Step {num + 1}")
                xopt.step()
                print(xopt.data)
            _, val, params = xopt.vocs.select_best(xopt.data)
            print(f"Best objective value {val}")
            print(f"Best point {params}")
            mirror_pitch = init_devices()["mr1l4_homs"].pitch
            mirror_pitch.set(params["mirror_pitch"]).wait(timeout=20)
            print(f"pitch is at {mirror_pitch.position}")
            xopt.data.plot(y=xopt.vocs.objective_names)
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
