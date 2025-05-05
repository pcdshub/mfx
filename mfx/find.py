import ophyd
from ophyd.signal import EpicsSignal

import mfx.db

from pcdsdevices.epics_motor import EpicsMotorInterface as Motor
from pcdsdevices.pv_positioner import OnePVMotor

class Find:
    def __init__(self):
        pass

    def get_motor_by_pvname(self, pvname: str) -> Motor:
        """
        Get a motor given its PV name.

        If it exists in this environment, the existing instance will be reused.
        If not, a new instance will be created.
        """

        _motor_cache = {}
        _pv_cache = {}
        _pv_motor_cache = {}
        pvname = pvname.strip()

        for motor in mfx.db.motors:
            try:
                if motor.prefix == pvname:
                    return motor
            except AttributeError:
                ...

        if pvname not in _motor_cache:
            _motor_cache[pvname] = Motor(pvname, name=pvname)
        return _motor_cache[pvname]


    def get_signal_by_pvname(self, pvname: str) -> ophyd.EpicsSignal:
        """
        Get an EpicsSignal given its PV name.

        If it exists in this environment, the existing instance will be reused.
        If not, a new instance will be created.
        """

        _motor_cache = {}
        _pv_cache = {}
        _pv_motor_cache = {}
        pvname = pvname.strip()

        for sig in mfx.db.a:
            if getattr(sig, "setpoint_pvname", None) == pvname:
                return sig

        if pvname not in _pv_cache:
            _pv_cache[pvname] = EpicsSignal(pvname, name=pvname)
        return _pv_cache[pvname]


    def get_signal_motor_by_pvname(self,pvname: str) -> OnePVMotor:
        """
        Get a OnePVMotor given its PV name.
        """

        _motor_cache = {}
        _pv_cache = {}
        _pv_motor_cache = {}
        pvname = pvname.strip()

        if pvname not in _pv_motor_cache:
            _pv_motor_cache[pvname] = OnePVMotor(pvname, name=pvname)
        return _pv_motor_cache[pvname]