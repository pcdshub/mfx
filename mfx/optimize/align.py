from bluesky import RunEngine


class Align:
    def __init__(self):
        self.beam_alignment_diagnostics = ["XCS1", "DG1", "DG2"]
        self.beam_alignment_methods = ["Xopt", "blop"]
        self.beam_alignment_devices = ["yag", "wave8"]

    def beam(
            self,
            with_goal: float,
            on_diagnostic: str = "DG1",
            with_method: str = 'Xopt',
            using_device: str = "yag",
            xopt_turbo_option: str = "safety",
            ):
        """Perform Beam Alignment

        Parameters:

            on_diagnostic (str): diagnostic to use for alignment. Options: "XCS1, DG1, DG2".

            with_method(str): method to use for alignment. Options: "blop, Xopt".
        """
        if on_diagnostic not in self.beam_alignment_diagnostics:
            print(f"Diagnostic {on_diagnostic} not usable for beam alignment. Use {self.beam_alignment_diagnostics}.")
            return None

        if with_method not in self.beam_alignment_methods:
            print(f"Alignment method {with_method} not implemented yet. Use {self.beam_alignment_methods}.")
            return None

        if using_device not in self.beam_alignment_devices:
            print(f"Only implemented devices: {self.beam_alignment_devices}")
            return None

        if with_method == 'Xopt':
            from .xopt_scans import get_xopt_obj, init_devices
            xopt = get_xopt_obj(
                device_type=using_device,
                location=on_diagnostic,
                goal=with_goal,
                xopt_generator_turbo_controller=xopt_turbo_option,
            )
            customized_boundaries = {'mirror_pitch': [-549.0,-546.0]}
            xopt.random_evaluate(3, custom_bounds=customized_boundaries)
            print(xopt.data)
            for num in range(10):
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
        elif with_method == 'blop':
            from .blop_scans import get_blop_agent
            try:
                from mfx.db import RE
            except ImportError:
                RE = RunEngine({})
            agent = get_blop_agent(on_diagnostic.lower(), wave8_xpos=with_goal)
            RE(agent.learn("qr", n=16))
            RE(agent.learn("qei", n=16, iterations=5))
            RE(agent.go_to_best())
            agent.plot_objectives()
            return agent
