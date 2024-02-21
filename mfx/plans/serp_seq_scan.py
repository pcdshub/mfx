from bluesky.plans import list_grid_scan
from bluesky.plan_stubs import one_nd_step, trigger
from pcdsdaq.preprocessors import daq_during_decorator


@daq_during_decorator()
def serp_seq_scan(shift_motor, shift_pts, fly_motor, fly_pts, seq):
    """
    Serpentine scan that triggers the event sequencer on every row.

    Parameters
    ----------
    shift_motor: Positioner
        The column axis to shift to the next fly scan row

    shift_pts:  list of floats
        The positions of the rows to scan down, e.g. [0, 1, 2, 3 ...],
        np.arange(0, 100, 1000), etc.

    fly_motor: Positioner
        The row axis to do fly collection on

    fly_pts: list of 2 floats
        The positions to fly between, e.g. [0, 100]

    seq: Sequencer
        The sequencer to start on each row.
    """
    if len(fly_pts) != 2:
        raise ValueError('Expected fly_pts to have exactly 2 points!')

    is_seq_step = False

    def per_step(detectors, step, pos_cache):
        """
        Override default per_step to start the sequencer on each row.

        The first move is not a fly scan move: it moves us into the start
        position. The second move is, as is the fourth, sixth...
        """
        nonlocal is_seq_step
        if is_seq_step:
            yield from trigger(seq)
            is_seq_step = False
        else:
            is_seq_step = True
        yield from one_nd_step(detectors, step, pos_cache)

    return (yield from list_grid_scan([],
                                      shift_motor, shift_pts,
                                      fly_motor, fly_pts,
                                      snake_axes=[False, True],
                                      per_step=per_step))

def test_serp_scan():
    """Note: run this standalone, not inside mfx hutch python."""
    import numpy as np
    from bluesky import RunEngine
    from bluesky.callbacks.best_effort import BestEffortCallback
    from ophyd.sim import motor1, motor2
    from ophyd.status import StatusBase
    from pcdsdaq.daq import Daq
    from pcdsdaq.sim import set_sim_mode

    class FakeSeq:
        def trigger(self):
            print('Triggered the sequencer!')
            status = StatusBase()
            status.set_finished()
            return status

    set_sim_mode(True)
    RE = RunEngine({})
    bec = BestEffortCallback()
    RE.subscribe(bec)
    seq = FakeSeq()
    daq = Daq(RE=RE)

    RE(serp_seq_scan(motor1, np.arange(100, 200, 10), motor2, [0, 100], seq))
