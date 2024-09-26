"""
To run for real, import get_blop_agent, generate agents, and try to agent.learn().
To test with sim, ipython -i mfx/optimize/blop_scans.py
"""
from __future__ import annotations

from bluesky import RunEngine
from bluesky.callbacks.best_effort import BestEffortCallback
from blop import DOF, Objective, Agent
from databroker import Broker
from matplotlib import pyplot as plt

from mfx.optimize.mirror_hw import MIRROR_NOMINAL, DG1_WAVE8_XPOS, DG2_WAVE8_XPOS, init_devices, sim_devices

bluesky_objs: dict[str, object] = {}
re_setup_info = {
    "databroker_sub_token": None,
    "bec_starting_state": None,
}

def init_bluesky_objs(force: bool = False) -> dict[str, object]:
    """
    Collect all the bluesky helper objects, creating them if necessary.
    """
    if bluesky_objs and not force:
        return bluesky_objs
    
    bluesky_objs["broker"] = Broker.named("temp")
    try:
        from mfx.db import RE
    except ImportError:
        RE = RunEngine({})
    bluesky_objs["RE"] = RE
    try:
        from mfx.db import bec
    except ImportError:
        bec = BestEffortCallback()
        # Sync up with how RE is configured outside of this module
        RE.subscribe(bec)
    bluesky_objs["bec"] = bec

    return bluesky_objs


def init_re() -> None:
    """
    Set up the run engine for use with blop, if needed.

    Things to do:
    - Create and subscribe to an in-memory databroker with HDF5 support
    - turn off the bec's plots if the bec exists and plots are enabled
    """
    objs = init_bluesky_objs()
    RE = objs["RE"]
    db = objs["broker"]
    bec = objs["bec"]

    if re_setup_info["databroker_sub_token"] is None:
        re_setup_info["databroker_sub_token"] = RE.subscribe(db.insert)
        bluesky_objs["broker"] = db

    if re_setup_info["bec_starting_state"] is None:
        re_setup_info["bec_starting_state"] = bec._plots_enabled
        bec.disable_plots()


def clean_re(re: RunEngine, bec: BestEffortCallback):
    """
    Undo init_re
    """
    if not bluesky_objs:
        return

    objs = init_bluesky_objs()
    RE = objs["RE"]
    bec = objs["bec"]

    if re_setup_info["databroker_sub_token"] is not None:
        RE.unsubscribe(re_setup_info["databroker_sub_token"])
        re_setup_info["databroker_sub_token"] = None
    
    if re_setup_info["bec_starting_state"]:
        bec.enable_plots()
        re_setup_info["bec_starting_state"] = None


def get_blop_agent(
    use_dg1: bool = False,
    use_dg2: bool = False,
    mirror_nominal: float = MIRROR_NOMINAL,
    search_delta: float = 5,
    dg1_wave8_xpos: float = DG1_WAVE8_XPOS,
    dg2_wave8_xpos: float = DG2_WAVE8_XPOS,
    wave8_tol: float = 0.1,
    wave8_max_value: float = 10,
    setup_re: bool = True,
) -> Agent:
    """
    Set up the RE for blop and create an appropriate blop optimization agent.

    When you have an agent, it can be used to optimize the position of
    the MFX flat mirror.

    RE(agent.learn("qei", n=20))
    Options for optimizer: https://github.com/NSLS-II/blop/blob/main/src/blop/bayesian/acquisition/config.yml
    Signature: https://github.com/NSLS-II/blop/blob/76ddd5a64db4a7eddd99c5d1bd3a92823b2ccb23/src/blop/agent.py#L388
    agent.plot_objectives() when done

    Parameters
    ----------
    use_dg1 : bool
        If True, we'll try to optimize the position on DG1.
    use_dg2 : bool
        If True, we'll try to optimize the position on DG2.
    mirror_nominal : float
        The starting mirror pitch position and midpoint of the optimization search.
    search_delta : float
        How far +/- we check away from the mirror nominal pitch position
    dg1_wave8_xpos : float
        The goal position on dg1
    dg2_wave8_xpos : float
        The goal position on dg2
    wave8_tol : float
        How close to our goal we need to get before we consider ourselves "done".
    wave8_max_value : float
        The maximum absolute wave8 value that is considered "reasonable".
    setup_re : bool
        If True, we'll set up the run engine first. Set to False to avoid
        setting up the run engine.
    """
    if setup_re:
        init_re()
    
    devices = init_devices()
    bluesky_objs = init_bluesky_objs()

    dofs = [
        DOF(
            description="MFX Mirror",
            device=devices["mr1l4_homs"].pitch,
            search_domain=(mirror_nominal - search_delta, mirror_nominal + search_delta),
        ),
    ]
    objectives = []
    detectors = []
    if use_dg1:
        objectives.append(
            Objective(
                name="mfx_dg1_wave8_xpos",
                target=(dg1_wave8_xpos - wave8_tol, dg1_wave8_xpos + wave8_tol),
                trust_domain=(-1 * wave8_max_value, wave8_max_value),
            )
        )
        detectors.append(devices["mfx_dg1_wave8"].xpos)
        if not devices["mfx_dg1_ipm"].inserted:
            print("Warning: DG1 Wave8 is not inserted!")
    if use_dg2:
        objectives.append(
            Objective(
                name="mfx_dg2_wave8_xpos",
                target=(dg2_wave8_xpos - wave8_tol, dg2_wave8_xpos + wave8_tol),
                trust_domain=(-1 * wave8_max_value, wave8_max_value),
            )
        )
        detectors.append(devices["mfx_dg2_wave8"].xpos)
        if not devices["mfx_dg2_ipm"].inserted:
            print("Warning: DG2 Wave8 is not inserted!")
    
    return Agent(
        dofs=dofs,
        objectives=objectives,
        dets=detectors,         # blop =0.7.0
        # detectors=detectors,  # blop >0.7.0
        verbose=True,
        db=bluesky_objs["broker"],
        tolerate_acquisition_errors=False,
        # enforce_all_objectives_valid=True,  # blop >0.7.0
        train_every=1,
    )


def setup_sim_test() -> None:
    """
    Prep offline test without using mfx hardware or mfx3 startup script
    """
    plt.ion()
    print("Creating sim devices")
    globals().update(**sim_devices())
    print("Setting up bluesky")
    globals().update(**init_bluesky_objs())
    print("Configuring RE")
    init_re()
    print(f"devices: {list(init_devices().keys())}")
    print(f"bluesky objs: {list(bluesky_objs.keys())}")
    print("Agent factory: get_mirror_wave8_agent")
    print("Canned test: run_sim_test")


def run_sim_test() -> Agent:
    print("Create agent")
    RE = bluesky_objs["RE"]
    agent = get_blop_agent(use_dg1=True)
    print("QR sampling")
    RE(agent.learn("qr", n=16))
    print("QEI optimization")
    agent.refresh()
    try:
        RE(agent.learn("qei", n=4, iterations=4))
    except Exception as exc:
        ...
        # raise
    agent.refresh()
    print("Move to best")
    RE(agent.go_to_best())
    print(f"pitch is at {init_devices()['mr1l4_homs'].pitch.position}")
    print("Generating plots")
    agent.plot_objectives()
    return agent


if __name__ == "__main__":
    from IPython import get_ipython
    ip = get_ipython()
    if ip is not None:
        ip.run_line_magic("matplotlib", "qt")
    setup_sim_test()
