from ophyd import Device, EpicsSignal, EpicsSignalRO, Component as C

import pcdsdevices.device_types


class XFLS(pcdsdevices.device_types.XFLS):
    """
    XRay Focusing Lens (Be)

    These are the stacks with common names on their states and state config PVs
    that show the focusing config
    """
    states_list = ['6K70', '7K50', '9K45', 'OUT']
    in_states = ['6K70', '7K50', '9K45']

class Piezo(Device):
    """
    Device for controlling piezo injector motors
    """
    velocity =  C(EpicsSignalRO, ':VELOCITYGET')
    req_velocity = C(EpicsSignal, ':VELOCITYSET')
    open_loop_step = C(EpicsSignal, ':OPENLOOPSTEP')

    _default_read_attrs = ['open_loop_step']
    _default_configuration_attrs = ['velocity']

    def tweak(self, distance):
        """
        Tweak the Piezo by a distance
        """
        return self.open_loop_step.set(distance)
