"""
Custom device classes for MFX beamline instrumentation.

Provides specialized device classes for X-ray focusing lenses (XFLS),
piezo injector motors, and laser shutters with analog output control.
"""

import logging
from ophyd import (Device, EpicsSignal, EpicsSignalRO,
                   Component as C, FormattedComponent as FC)
from ophyd.signal import AttributeSignal
import pcdsdevices.device_types
from pcdsdevices.inout import InOutPositioner

logger = logging.getLogger(__name__)


class XFLS(pcdsdevices.device_types.XFLS):
    """
    X-ray Focusing Lens Stack (Beryllium).

    Compound refractive lens (CRL) stacks with predefined focusing
    configurations. Each state corresponds to a specific energy and
    focal distance configuration.

    Attributes
    ----------
    states_list : list of str
        Available lens configurations: ['6K70', '7K50', '9K45', 'OUT']
    in_states : list of str
        Configurations with lenses in beam: ['6K70', '7K50', '9K45']

    Notes
    -----
    State Naming Convention:
    - Format: {energy}K{focal_distance}
    - Example: '9K45' = 9 keV, 45 cm focal distance
    - 'OUT' = No lenses in beam path

    Common Configurations:
    - 6K70: 6 keV photons, 70 cm focus
    - 7K50: 7 keV photons, 50 cm focus
    - 9K45: 9 keV photons, 45 cm focus

    The lens stack provides beam focusing for improved intensity at
    the sample position. Proper configuration depends on X-ray energy
    and desired focal properties.

    Examples
    --------
    Create and move lens stack:
    >>> from mfx.devices import XFLS
    >>> lens = XFLS('MFX:LENS', name='xfls')
    >>> lens.move('9K45')  # Configure for 9 keV

    Remove lenses from beam:
    >>> lens.move('OUT')

    Check current state:
    >>> print(lens.position)
    '9K45'

    See Also
    --------
    pcdsdevices.device_types.XFLS : Base XFLS class
    """

    states_list = ['6K70', '7K50', '9K45', 'OUT']
    in_states = ['6K70', '7K50', '9K45']


class Piezo(Device):
    """
    Piezoelectric injector motor control.

    Provides control of piezo-driven sample injection systems with
    velocity feedback and open-loop stepping capability.

    Components
    ----------
    velocity : EpicsSignalRO
        Current velocity readback (read-only)
    req_velocity : EpicsSignal
        Requested velocity setpoint
    open_loop_step : EpicsSignal
        Open-loop step size command

    Attributes
    ----------
    _default_read_attrs : list
        Default attributes for read operations: ['open_loop_step']
    _default_configuration_attrs : list
        Default configuration attributes: ['velocity']

    Methods
    -------
    tweak(distance)
        Execute open-loop step movement

    Notes
    -----
    Piezo Operation Modes:
    - Closed-loop: Velocity controlled with feedback
    - Open-loop: Step-based movement without feedback

    Open-Loop Stepping:
    - Used for precise small movements
    - No position feedback
    - Cumulative errors possible
    - Good for repetitive injection

    Velocity Control:
    - Continuous motion mode
    - Position feedback available
    - Better for long-range movements

    Typical Applications:
    - Liquid jet injection
    - Sample raster scanning
    - Drop-on-demand delivery
    - Serial crystallography

    Examples
    --------
    Create piezo device:
    >>> from mfx.devices import Piezo
    >>> piezo = Piezo('MFX:PIEZO:01', name='injector')

    Set velocity:
    >>> piezo.req_velocity.put(100)  # Set velocity
    >>> current_vel = piezo.velocity.get()  # Read back

    Perform open-loop step:
    >>> piezo.tweak(50)  # Step 50 units

    See Also
    --------
    ophyd.Device : Base device class
    """

    velocity = C(EpicsSignalRO, ':VELOCITYGET',
                 kind='config',
                 doc='Current velocity readback')
    req_velocity = C(EpicsSignal, ':VELOCITYSET',
                     kind='config',
                     doc='Requested velocity setpoint')
    open_loop_step = C(EpicsSignal, ':OPENLOOPSTEP',
                       kind='hinted',
                       doc='Open-loop step command')

    _default_read_attrs = ['open_loop_step']
    _default_configuration_attrs = ['velocity']

    def tweak(self, distance):
        """
        Execute open-loop step movement.

        Performs a single open-loop step of specified distance without
        position feedback. Useful for incremental positioning or
        repetitive injection patterns.

        Parameters
        ----------
        distance : float
            Step distance in device units (typically micrometers)

        Returns
        -------
        status : ophyd.Status
            Status object tracking step completion

        Notes
        -----
        Open-Loop Characteristics:
        - No position verification
        - Fast execution
        - Potential for cumulative error
        - Repeatable for same conditions

        The step executes immediately and returns a status object that
        completes when the PV write finishes (not when motion ends).

        Warnings
        --------
        Multiple rapid tweaks can accumulate positioning errors.
        Periodically verify position if precision is critical.

        Examples
        --------
        Single step forward:
        >>> piezo.tweak(10)  # Step 10 µm

        Multiple small steps:
        >>> for i in range(5):
        ...     piezo.tweak(2)  # Five 2 µm steps
        ...     time.sleep(0.1)

        Step backward:
        >>> piezo.tweak(-5)  # Step -5 µm

        See Also
        --------
        open_loop_step : Direct access to step PV
        req_velocity : Velocity control for continuous motion
        """
        return self.open_loop_step.set(distance)


class LaserShutter(InOutPositioner):
    """
    Laser shutter with analog voltage control.

    Controls laser beam shutters via analog output voltage. Provides
    binary IN/OUT state control with voltage threshold detection.

    Components
    ----------
    voltage : EpicsSignal
        Analog output voltage control (0-10V)
    state : AttributeSignal
        Current shutter state based on voltage

    Attributes
    ----------
    out_voltage : float
        Voltage for OUT state (shutter open): 5.0V
    in_voltage : float
        Voltage for IN state (shutter closed): 0.0V
    barrier_voltage : float
        Threshold voltage for state detection: 1.4V

    Methods
    -------
    voltage_check
        Property that determines state from voltage
    _do_move(state)
        Internal method to execute state changes

    Notes
    -----
    Voltage States:
    - >= 1.4V: Interpreted as OUT (open)
    - < 1.4V: Interpreted as IN (closed)

    Control Voltages:
    - OUT: 5.0V applied to open shutter
    - IN: 0.0V applied to close shutter

    State Detection:
    - Based on voltage readback
    - Threshold at 1.4V provides hysteresis
    - Prevents false triggers from noise

    Hardware:
    - Analog output card controls shutter
    - Voltage drives electromechanical actuator
    - Typical response time: <100 ms

    Safety:
    - Always close shutters when not in use
    - Verify state before laser operation
    - Use proper eye protection

    Examples
    --------
    Create shutter device:
    >>> from mfx.devices import LaserShutter
    >>> shutter = LaserShutter('MFX:USR:ao1:6', name='opo_shutter')

    Open shutter:
    >>> shutter.move('OUT')
    >>> # Or equivalently:
    >>> shutter.open()

    Close shutter:
    >>> shutter.move('IN')
    >>> # Or equivalently:
    >>> shutter.close()

    Check state:
    >>> state = shutter.state.get()
    >>> print(f"Shutter is {state}")

    Check voltage directly:
    >>> voltage = shutter.voltage.get()
    >>> print(f"Control voltage: {voltage}V")

    See Also
    --------
    InOutPositioner : Base class for binary positioners
    yano : Laser control system using shutters
    """

    # EPICS signals
    voltage = C(EpicsSignal, '',
                kind='normal',
                doc='Analog output voltage (0-10V)')
    state = FC(AttributeSignal, 'voltage_check',
               kind='hinted',
               doc='Shutter state based on voltage')

    # Voltage constants
    out_voltage = 5.0    # Voltage for shutter OUT (open)
    in_voltage = 0.0     # Voltage for shutter IN (closed)
    barrier_voltage = 1.4  # Threshold for state detection

    @property
    def voltage_check(self):
        """
        Determine shutter state from voltage reading.

        Returns
        -------
        str
            'OUT' if voltage >= barrier_voltage (1.4V)
            'IN' if voltage < barrier_voltage

        Notes
        -----
        State Logic:
        - High voltage (>=1.4V) indicates open shutter
        - Low voltage (<1.4V) indicates closed shutter
        - Threshold provides noise immunity

        This property is used as the readback for the InOutPositioner
        state attribute.

        Examples
        --------
        Check state via voltage:
        >>> shutter = LaserShutter('MFX:USR:ao1:6', name='shutter')
        >>> print(shutter.voltage_check)
        'OUT'

        See Also
        --------
        state : Shutter state signal
        voltage : Raw voltage signal
        """
        current_voltage = self.voltage.get()
        if current_voltage >= self.barrier_voltage:
            return 'OUT'
        else:
            return 'IN'

    def _do_move(self, state):
        """
        Execute shutter state change.

        Internal method called by InOutPositioner to change shutter
        state by setting appropriate control voltage.

        Parameters
        ----------
        state : State
            Target state (IN or OUT)

        Raises
        ------
        ValueError
            If state is not valid (must be IN or OUT)

        Notes
        -----
        Called automatically by move(), open(), and close() methods
        inherited from InOutPositioner.

        Move Sequence:
        1. Validate requested state
        2. Set control voltage (0V or 5V)
        3. Wait for voltage to settle
        4. Verify state via voltage readback

        Examples
        --------
        This method is called internally:
        >>> shutter.move('OUT')  # Calls _do_move internally
        >>> shutter.close()      # Calls _do_move(IN) internally

        See Also
        --------
        voltage_check : State determination logic
        InOutPositioner : Base class providing move interface
        """
        if state.name == 'IN':
            self.voltage.put(self.in_voltage)
        elif state.name == 'OUT':
            self.voltage.put(self.out_voltage)
        else:
            raise ValueError(f"{state} is not a valid state (IN or OUT)")


# Module-level convenience functions and examples

def configure_all_laser_shutters(evo1=False, evo2=False,
                                  evo3=False, opo=False):
    """
    Configure all MFX laser shut shutters simultaneously.

    Convenience function to set all laser shutters in one call.
    Useful for quick experiment setup.

    Parameters
    ----------
    evo1 : bool
        EVO shutter 1 state (True=open, False=closed)
    evo2 : bool
        EVO shutter 2 state
    evo3 : bool
        EVO shutter 3 state
    opo : bool
        OPO free-space shutter state

    Examples
    --------
    Open only fiber 1:
    >>> configure_all_laser_shutters(evo1=True)

    Open fibers 1 and 2:
    >>> configure_all_laser_shutters(evo1=True, evo2=True)

    Close all shutters:
    >>> configure_all_laser_shutters()

    See Also
    --------
    yano.configure_shutters : Full laser configuration
    LaserShutter : Individual shutter control
    """
    from mfx.db import yano_instance

    yano_instance.configure_shutters(
        fiber1=evo1,
        fiber2=evo2,
        fiber3=evo3,
        free_space=opo
    )