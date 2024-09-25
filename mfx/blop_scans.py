import random
from types import SimpleNamespace

from bluesky import RunEngine
from bluesky.callbacks.best_effort import BestEffortCallback
from blop import DOF, Objective, Agent
from databroker import Broker
from happi import Client
from matplotlib import pyplot as plt
from ophyd.device import Device
from ophyd.sim import SynAxis, SynSignal
from pcdsdevices.ipm import Wave8

HAPPI_NAMES = (
    "mr1l4_homs",
    "mfx_dg1_ipm",
    "mfx_dg2_ipm",
)
# Default constants so I can re-use them in sim_devices
MIRROR_NOMINAL = -544
DG1_WAVE8_XPOS = 8
DG2_WAVE8_XPOS = 41

devices: dict[str, Device] = {}
bluesky_objs = dict[str, object] = {}
re_setup_info = {
    "databroker_sub_token": None,
    "bec_starting_state": None,
}


def init_devices(force: bool = False) -> dict[str, Device]:
    """
    Collect all the devices needed for blop scanning into the "devices" dictionary.

    Returns the fully-loaded device dictionary.
    This can be simulated devices if sim_devices was called first.
    """
    if devices and not force:
        return devices

    client = Client.from_config("/cds/group/pcds/pyps/apps/hutch-python/device_config/happi.cfg")

    for name in HAPPI_NAMES:
        devices[name] = client.load_device(name=name)

    # Happi IPMs do not currently have wave8s, add manually
    for stand in ("dg1", "dg2"):
        name = f"mfx_{stand}_wave8"
        devices[name] = Wave8(f"MFX:{stand.upper()}:BMMON", name=name)
        devices[name].kind = "hinted"
    
    return devices


def sim_devices() -> dict[str, Device]:
    """
    Collect simulated stand-ins for all devices we might use in blop into the "devices" dictionary.

    Returns the fully-loaded device dictionary.
    This is guaranteed to always be simulated devices.
    """
    if devices:
        if isinstance(devices["mr1l4_homs"], SimpleNamespace):
            return devices
    
    devices["mr1l4_homs"] = SimpleNamespace(pitch=SynAxis("mr1l4_homs_pitch", value=MIRROR_NOMINAL))
    devices["mfx_dg1_ipm"] = SimpleNamespace(inserted=True)
    devices["mfx_dg2_ipm"] = SimpleNamespace(inserted=False)
    dg1_offset = random.uniform(-1, 1)
    dg2_offset = random.uniform(-1, 1)

    def get_fake_dg1_wave8():
        pitch = devices["mr1l4_homs"].pitch.position
        return pitch - MIRROR_NOMINAL + DG1_WAVE8_XPOS + dg1_offset
    
    def get_fake_dg2_wave8():
        pitch = devices["mr1l4_homs"].pitch.position
        return pitch - MIRROR_NOMINAL + DG2_WAVE8_XPOS + dg2_offset

    devices["mfx_dg1_wave8"] = SimpleNamespace(
        xpos=SynSignal(
            func=get_fake_dg1_wave8,
            name="mfx_dg1_wave8_xpos"
        )
    )
    devices["mfx_dg2_wave8"] = SimpleNamespace(
        xpos=SynSignal(
            func=get_fake_dg2_wave8,
            name="mfx_dg2_wave8_xpos"
        )
    )
    devices["mfx_dg1_wave8"].kind = "hinted"
    devices["mfx_dg2_wave8"].kind = "hinted"
    
    return devices


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


def get_mirror_wave8_agent(
    use_dg1: bool,
    use_dg2: bool,
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
        detectors=detectors,
        verbose=True,
        db=bluesky_objs["broker"],
        tolerate_acquisition_errors=False,
        enforce_all_objectives_value=True,
        train_every=3,
    )


def setup_sim_test() -> None:
    """
    Prep offline test without using mfx hardware or mfx3 startup script
    """
    plt.ion()
    globals().update(**sim_devices())
    globals().update(**init_bluesky_objs())
    print(f"devices: {devices}")
    print(f"bluesky objs: {bluesky_objs}")
    print("Agent factory: get_mirror_wave8_agent")
    print(get_mirror_wave8_agent.__doc__)


if __name__ == "__main__":
    setup_sim_test()
