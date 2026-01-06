import threading

import numpy as np

from bluesky.suspenders import SuspendFloor
from ophyd.signal import Signal, EpicsSignalRO


class AvgSignal(Signal):
    """
    Signal that acts as a rolling average of another signal
    """
    def __init__(self, signal, averages, name=None, parent=None, **kwargs):
        super().__init__(name=name, parent=parent, **kwargs)
        self.sig = signal
        self.lock = threading.RLock()
        self.index = 0
        self.values = np.ones(averages) * self.sig.get()
        self.sig.subscribe(self._update_avg)

    def _update_avg(self, *args, value, **kwargs):
        with self.lock:
            self.values[self.index] = value
            self.index += 1
            if self.index == len(self.values):
                self.index = 0
            self.put(np.mean(self.values))


class BeamEnergySuspendFloor(SuspendFloor):
    """
    Suspend the run if the beam energy falls below a set value.
    """
    def __init__(self, suspend_thresh, resume_thresh=None, sleep=5.0,
                 averages=120, **kwargs):

        sig = EpicsSignalRO('GDET:FEE1:241:ENRC')
        if averages > 1:
            sig = AvgSignal(sig, averages, name=sig.name + "_avg")

        super().__init__(sig, suspend_thresh, resume_thresh=resume_thresh,
                         sleep=sleep, **kwargs)
