class Align:
    def __init__(self):
        self.beam_alignment_diagnostics = ["DG1", "DG2"]
        self.beam_alignment_methods = ["Xopt", "blop"]

    def beam(
            self,
            on_diagnostic: str = "DG1",
            with_method: str = 'Xopt'):
        """Perform Beam Alignment

        Parameters:

            on_diagnostic (str): diagnostic to use for alignment. Options: "DG1, DG2".

            with_method(str): method to use for alignment. Options: "blop, Xopt".
        """
        if on_diagnostic not in self.beam_alignment_diagnostics:
            print(f"Diagnostic {on_diagnostic} not usable for beam alignment. Use {self.beam_alignment_diagnostics}.")
            return None

        if with_method not in self.beam_alignment_methods:
            print(f"Alignment method {with_method} not implemented yet. Use {self.beam_alignment_methods}.")
            return None

        if with_method == 'Xopt':
            from mfx.optimize.xopt_scans import get_xopt_obj, init_devices
            xopt = get_xopt_obj(lower(on_diagnostic))
            xopt.random_evaluate(3)
            for num in range(10):
                print(f"Step {num + 1}")
                xopt.step()
            _, val, params = xopt.vocs.select_best(xopt.data)
            print(f"Best objective value {val}")
            print(f"Best point {params}")
            mirror_pitch = init_devices()["mr1l4_homs"].pitch
            mirror_pitch.set(params["mirror_pitch"]).wait(timeout=20)
            print(f"pitch is at {mirror_pitch.position}")
            xopt.data.plot(y=xopt.vocs.objective_names)
            return xopt
        elif with_method == 'blop':
            from mfx.optimize.blop_scans import get_blop_agent
            agent = get_blop_agent(lower(on_diagnostic))
            RE(agent.learn("qr", n=16))
            RE(agent.learn("qei", n=4, iterations=4))
            RE(agent.go_to_best())
            agent.plot_objectives()
            return agent