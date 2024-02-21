from bluesky.plans import outer_product_scan
from bluesky.plan_stubs import one_nd_step
from ophyd import Device, EpicsSignal, EpicsSignalRO, Component as C
from ophyd.status import SubscriptionStatus, wait as status_wait

from mfx.db import inj_x, inj_y


class EventSequencer(Device):
    """
    Simple Event Sequencer
    """
    play_control = C(EpicsSignal, ':PLYCTL')
    play_status = C(EpicsSignalRO, ':PLSTAT', auto_monitor=True)

    _default_read_attrs = ['play_status']
    _default_configuration_attrs = ['play_control']

    def set(self, *args, wait=False, timeout=None):
        # Start the sequencer
        self.play_control.set(1)
        # Wait for the sequencer to start before subscribing
        while self.play_status.value == 0:
            time.sleep(0.001)
        # Create our status
        def done(*args, value=None, old_value=None,  **kwargs):
            return value == 0 and old_value == 2
        status = SubscriptionStatus(self.play_status, done)

        # Wait on the sequencer
        if wait:
            status_wait(status, timeout=timeout)
        return status

    def stop(self, wait=False):
        self.play_control.put(0)
        while play_status.value != 0:
            time.sleep(0.001)


def grid_scan(x_start, x_finish, x_steps,
              y_start, y_finish, y_steps,
              snake=False):
    """
    Parameters
    ----------
    x_start : float
        First point in X scan

    x_finish: float
        Last point in X scan

    x_steps : int
        Number of steps in X to perform

    y_start: float
        First point in Y scan

    y_finish: float
        Last point in Y scan

    y_steps: int
        Number of steps in Y to perform

    snake: bool, optional
        Snake scan instead of typewriter
    """
    # Per step function
    def run_sequencer(detectors, step, pos_cache):
        yield from one_nd_step(detectors, step, pos_cache)
        yield from abs_set(detectors[0], 0, wait=True)

    # The main plan
    def inner():
        yield from outer_product_scan([seq],
                                      inj_x, x_start, x_finish, x_steps,
                                      inj_y, y_start, y_finish, y_steps, snake,
                                      per_step=run_sequencer)
    # Return plan to user
    yield from inner()
