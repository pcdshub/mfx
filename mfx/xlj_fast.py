from ophyd.device import Component as Cpt
from ophyd.signal import EpicsSignal

from pcdsdevices.pv_positioner import PVPositionerDone


class BypassPositionCheck(PVPositionerDone):
    setpoint = Cpt(EpicsSignal, ":PLC:fPosition")
    actuate = Cpt(EpicsSignal, ":PLC:bMoveCmd")
