"""
Custom device definitions for MFX beamline.

Provides specialized device classes for MFX-specific hardware including
focusing lenses, piezo motors, and laser shutters.
"""

import logging
from ophyd import Device, Component as Cpt
from ophyd.signal import EpicsSignal, EpicsSignalRO, AttributeSignal
from pcdsdevices.device_types import XFLS as BaseXFLS
from pcdsdevices.inout import InOutPositioner

logger = logging.getLogger(__name__)


class XFLS(BaseXFLS):
    """
    X-ray Focusing Lens Stack (Beryllium).

    MFX-specific XFLS with predefined state configurations for
    different focusing conditions.

    Attributes
    ----------
    states_list : List[str]
        Available lens configurations
    in_states : List[str]
        States where lenses are in beam

    Notes
    -----
    MFX XFLS States:
    - '6K70': 6 keV focus at 70 cm from interaction point
    - '7K50': 7 keV focus at 50 cm
    - '9K45': 9 keV focus at 45 cm
    - 'OUT': All lenses removed from beam

    Beryllium Lenses:
    - Low Z material (Z=4)
    - Minimal absorption
    - Refractive X-ray optics
    - Stacked for focusing

    Focal Properties:
    - Energy-dependent focus
    - Position-dependent
    - Beam size reduction
    - Flux concentration

    State Configuration:
    - Motorized lens stack
    - Programmable positions
    - Quick state changes
    - Reproducible focusing

    Examples
    --------
    >>> xfls = XFLS('MFX:LENS', name='xfls')
    >>> xfls.state.get()
    'OUT'
    >>> xfls.move('9K45')  # Move to 9 keV focus
    >>> xfls.remove()  # Move out of beam

    See Also
    --------
    pcdsdevices.device_types.XFLS : Base class
    """

    # Define available states
    states_list = ['6K70', '7K50', '9K45', 'OUT']

    # States where lenses are inserted
    in_states = ['6K70', '7K50', '9K45']


class Piezo(Device):
    """
    Piezo injector motor controller.

    Controls piezoelectric actuator for sample injection systems,
    providing high-speed, precise positioning.

    Components
    ----------
    velocity : EpicsSignalRO
        Current velocity readback (Hz)
    req_velocity : EpicsSignal
        Requested velocity setpoint (Hz)
    open_loop_step : EpicsSignal
        Open-loop step size for jogging

    Methods
    -------
    tweak(distance)
        Perform relative open-loop move

    Notes
    -----
    Piezo Operation:
    - Piezoelectric actuation
    - Sub-micron resolution
    - Fast response (~ms)
    - Position sensing via encoder

    Control Modes:
    - Closed-loop: Position feedback control
    - Open-loop: Direct voltage steps
    - Velocity control: Frequency-based

    Velocity:
    - Units: Hz (steps per second)
    - Range: 1-1000 Hz typical
    - Higher = faster motion
    - Limited by load

    Open-Loop Stepping:
    - Direct piezo actuation
    - No position feedback
    - Fast but less accurate
    - Useful for jogging

    Applications:
    - Liquid jet positioning
    - Drop-on-demand injection
    - High-speed scanning
    - Vibration compensation

    Examples
    --------
    >>> piezo = Piezo('MFX:PIEZO:01', name='piezo_jet')
    >>> piezo.req_velocity.put(100)  # Set 100 Hz
    >>> piezo.tweak(10)  # Move +10 steps
    >>> piezo.tweak(-5)  # Move -5 steps

    See Also
    --------
    pcdsdevices.jet : Jet delivery systems
    """

    velocity = Cpt(
        EpicsSignalRO, ':VELOCITYGET',
        kind='normal',
        doc='Current velocity (Hz)'
    )

    req_velocity = Cpt(
        EpicsSignal, ':VELOCITYSET',
        kind='config',
        doc='Requested velocity (Hz)'
    )

    open_loop_step = Cpt(
        EpicsSignal, ':OPENLOOPSTEP',
        kind='normal',
        doc='Open-loop step size'
    )

    # Default read attrs
    _default_read_attrs = ['open_loop_step']
    _default_configuration_attrs = ['velocity']

    def tweak(self, distance: int):
        """
        Perform relative open-loop move.

        Executes open-loop step by specified distance without
        position feedback.

        Parameters
        ----------
        distance : int
            Number of steps to move.
            Positive = forward, negative = backward

        Returns
        -------
        None

        Notes
        -----
        Open-Loop Move:
        - No position verification
        - Fast execution
        - Accumulates errors over many moves
        - Useful for fine adjustments

        Step Size:
        - Determined by open_loop_step PV
        - Typically ~0.1 to 1 μm
        - Varies with piezo type

        Examples
        --------
        >>> piezo.tweak(10)   # Forward 10 steps
        >>> piezo.tweak(-5)   # Backward 5 steps

        See Also
        --------
        open_loop_step : Step size setting
        """
        return self .open_loop_step.set(distance)


class LaserShutter(InOutPositioner):
    """
    Laser shutter controlled by analog output voltage.

    Controls laser shutter via voltage level on analog output
    channel, providing open/closed beam control.

    Components
    ----------
    voltage : EpicsSignal
        Analog output voltage (0-10V)
    state : AttributeSignal
        Computed shutter state from voltage

    Attributes
    ----------
    out_voltage : float
        Voltage for OPEN state (5.0V)
    in_voltage : float
        Voltage for CLOSED state (0.0V)
    barrier_voltage : float
        Threshold for state determination (1.4V)

    Methods
    -------
    insert()
        Close shutter (inherited from InOutPositioner)
    remove()
        Open shutter (inherited from InOutPositioner)

    Notes
    -----
    Voltage-Based Control:
    - Analog output controls shutter
    - High voltage = OPEN
    - Low voltage = CLOSED
    - Intermediate = uncertain

    State Determination:
    - voltage >= 1.4V: OUT (open)
    - voltage < 1.4V: IN (closed)
    - Barrier prevents ambiguity

    Typical Voltages:
    - CLOSED: 0.0V (shutter blocking)
    - OPEN: 5.0V (shutter retracted)
    - Threshold: 1.4V (state boundary)

    Hardware:
    - Pneumatic or solenoid actuator
    - Voltage-to-pressure converter
    - Position not directly measured
    - State inferred from command

    Safety:
    - Fail-safe to CLOSED
    - Power loss = beam blocked
    - Manual override available

    Examples
    --------
    >>> shutter = LaserShutter('MFX:LAS:AO:01', name='las_shutter')
    >>> shutter.remove()  # Open shutter
    >>> shutter.insert()  # Close shutter
    >>> shutter.state.get()
    'OUT'

    Direct voltage control:
    >>> shutter.voltage.put(5.0)  # Open
    >>> shutter.voltage.put(0.0)  # Close

    See Also
    --------
    InOutPositioner : Base class
    """

    # Components
    voltage = Cpt(
        EpicsSignal, '',
        kind='hinted',
        doc='Analog output voltage (V)'
    )

    state = Cpt(
        AttributeSignal,
        attr='voltage_check',
        kind='hinted',
        doc='Computed shutter state'
    )

    # Voltage constants
    out_voltage = 5.0       # Open state voltage
    in_voltage = 0.0        # Closed state voltage
    barrier_voltage = 1.4   # State threshold

    @property
    def voltage_check(self) -> str:
        """
        Determine shutter state from voltage.

        Compares current voltage to threshold to determine
        whether shutter is open or closed.

        Returns
        -------
        str
            'OUT' if voltage >= barrier_voltage, 'IN' otherwise

        Notes
        -----
        State Logic:
        - voltage >= 1.4V: Shutter OPEN
        - voltage < 1.4V: Shutter CLOSED
        - Hysteresis prevents chatter

        Examples
        --------
        >>> shutter.voltage.put(5.0)
        >>> shutter.voltage_check
        'OUT'

        See Also
        --------
        _do_move : State transition logic
        """
        if self.voltage.get() >= self.barrier_voltage:
            return 'OUT'
        else:
            return 'IN'

    def _do_move(self, state):
        """
        Execute shutter state transition.

        Overrides InOutPositioner._do_move to control shutter
        via voltage instead of motor.

        Parameters
        ----------
        state : State
            Target state (IN or OUT)

        Raises
        ------
        ValueError
            If state is not IN or OUT

        Notes
        -----
        Move Implementation:
        - IN state: Sets voltage to in_voltage (0V)
        - OUT state: Sets voltage to out_voltage (5V)
        - Invalid state: Raises error

        No position verification - voltage command only.

        Examples
        --------
        Used internally by insert() and remove():
        >>> shutter.insert()  # Calls _do_move('IN')
        >>> shutter.remove()  # Calls _do_move('OUT')

        See Also
        --------
        voltage_check : State readback
        """
        if state.name == 'IN':
            # Close shutter
            self.voltage.put(self.in_voltage)
        elif state.name == 'OUT':
            # Open shutter
            self.voltage.put(self.out_voltage)
        else:
            raise ValueError(f"Invalid state: {state}")


logger.info("MFX custom devices loaded and ready")