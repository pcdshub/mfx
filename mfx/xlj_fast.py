"""
XLJ (X-ray Liquid Jet) fast motor control with interactive keyboard interface.

Provides real-time keyboard control for liquid jet positioning with support
for translational (X, Y, Z) and rotational (RX, RY, RZ) axes.
"""

import logging
import sys
import tty
import termios
from typing import List, Tuple, Dict

from ophyd import Component as Cpt
from ophyd.signal import EpicsSignal
from pcdsdevices.epics_motor import IMS
from pcdsdevices.pv_positioner import PVPositionerDone
from pcdsdevices.jet import BeckhoffJet

logger = logging.getLogger(__name__)


# Key code constants for arrow keys and special keys
KEYS = {
    'up': "\x1b[A",
    'down': "\x1b[B",
    'right': "\x1b[C",
    'left': "\x1b[D",
    'shift_up': "\x1b[1;2A",
    'shift_down': "\x1b[1;2B",
    'shift_right': "\x1b[1;2C",
    'shift_left': "\x1b[1;2D",
    'plus': "+",
    'equal': "=",
    'minus': "-",
    'under': "_",
}


class BypassPositionCheck(PVPositionerDone):
    """
    PV positioner with position check bypass for fast movements.

    Extends PVPositionerDone to skip position verification,
    allowing faster continuous motion for interactive control.

    Components
    ----------
    setpoint : EpicsSignal
        Target position PV
    actuate : EpicsSignal
        Move command trigger

    Notes
    -----
    Bypassing Position Check:
    - Standard positioners wait for position reached
    - Interactive control needs immediate response
    - This class starts move and returns immediately
    - Position tracking happens asynchronously

    Use Cases:
    - Interactive jogging
    - Continuous motion
    - Fast scanning
    - Real-time adjustments

    Warnings
    --------
    - No verification that position reached
    - Responsibility on user to monitor
    - Not suitable for precision positioning

    Examples
    --------
    >>> motor = BypassPositionCheck('MFX:LJH:JET:X', name='xlj_x')
    >>> motor.move(10.0)  # Returns immediately
    """

    setpoint = Cpt(EpicsSignal, ":PLC:fPosition")
    actuate = Cpt(EpicsSignal, ":PLC:bMoveCmd")


class XLJController:
    """
    Interactive keyboard controller for XLJ motors.

    Provides real-time keyboard-based control with visual feedback
    and configurable step sizes.

    Attributes
    ----------
    motors : List
        List of motor objects to control
    orientation : str
        Camera view orientation: 'horizontal' or 'vertical'
    scale : float
        Current step size for movements
    mode : str
        Control mode: 'translation', 'rotation', or '6axis'
    xlj : BeckhoffJet
        Full XLJ device for status monitoring

    Methods
    -------
    run()
        Start interactive control loop
    print_help()
        Display control instructions
    process_key(key)
        Handle keyboard input
    update_scale(factor)
        Adjust step size

    Notes
    -----
    Control Modes:

    Translation (X, Y, Z):
    - Arrow keys: Move X and Y
    - Shift+Up/Down: Move Z
    - Direct spatial control
    - Units: mm

    Rotation (RX, RY, RZ):
    - Arrow keys: Rotate RX and RY
    - Shift+Up/Down: Rotate RZ
    - Angular adjustments
    - Units: degrees

    6-Axis (X, Y, Z, RX, RY, RZ):
    - Arrow keys: Move X and Y
    - Shift+Up/Down: Move Z
    - W/S: Rotate RY (horizontal) or RX (vertical)
    - A/D: Rotate RX (horizontal) or RY (vertical)
    - Shift+W/S: Rotate RZ
    - Full control of all DOF

    Orientation:
    - Horizontal: Standard camera view
    - Vertical: 90° rotated camera
    - Affects arrow key mapping
    - Matches visual feedback

    Step Size Control:
    - +/=: Double current step
    - -/_: Halve current step
    - Shift+Right: Double step
    - Shift+Left: Halve step
    - Dynamic adjustment during use

    Visual Feedback:
    - Current positions displayed
    - Step size shown
    - Motor names labeled
    - Updates after each move

    Examples
    --------
    Create controller:
    >>> from xlj_fast import XLJController
    >>> motors = [xlj_x, xlj_y, xlj_z]
    >>> ctrl = XLJController(motors, 'horizontal', 0.1, 'translation')
    >>> ctrl.run()

    See Also
    --------
    xlj_fast : Translation control function
    xlj_fast_rot : Rotation control function
    xlj_6axis : Full 6-axis control function
    """

    def __init__(
            self,
            motors: List,
            orientation: str = 'horizontal',
            scale: float = 0.1,
            mode: str = 'translation'):
        """
        Initialize XLJ controller.

        Parameters
        ----------
        motors : List
            Motor objects to control
        orientation : str, optional
            Camera orientation. Default is 'horizontal'.
        scale : float, optional
            Initial step size. Default is 0.1.
        mode : str, optional
            Control mode. Default is 'translation'.
        """
        self.motors = motors
        self.orientation = orientation.lower()
        self.scale = scale
        self.mode = mode.lower()
        self.xlj = None  # Set by caller if needed

        # Setup key mappings based on mode
        if mode == 'translation':
            self._setup_translation_keys()
        elif mode == 'rotation':
            self._setup_rotation_keys()
        elif mode == '6axis':
            self._setup_6axis_keys()
        else:
            raise ValueError(f"Unknown mode: {mode}")

        logger.info(f"XLJ Controller initialized: {mode} mode")

    def _setup_translation_keys(self):
        """Setup key mappings for translation mode (X, Y, Z)."""
        if self.orientation == 'horizontal':
            self.move_map = {
                KEYS['left']: ('x', -1),
                KEYS['right']: ('x', 1),
                KEYS['down']: ('y', -1),
                KEYS['up']: ('y', 1),
                KEYS['shift_up']: ('z', -1),
                KEYS['shift_down']: ('z', 1),
            }
        else:  # vertical
            self.move_map = {
                KEYS['right']: ('x', -1),
                KEYS['left']: ('x', 1),
                KEYS['down']: ('y', 1),
                KEYS['up']: ('y', -1),
                KEYS['shift_up']: ('z', -1),
                KEYS['shift_down']: ('z', 1),
            }

        self.move_keys = tuple(self.move_map.keys())
        self.motor_names = ['X', 'Y', 'Z']

    def _setup_rotation_keys(self):
        """Setup key mappings for rotation mode (RX, RY, RZ)."""
        if self.orientation == 'horizontal':
            self.move_map = {
                KEYS['left']: ('rx', -1),
                KEYS['right']: ('rx', 1),
                KEYS['down']: ('ry', -1),
                KEYS['up']: ('ry', 1),
                KEYS['shift_up']: ('rz', -1),
                KEYS['shift_down']: ('rz', 1),
            }
        else:  # vertical
            self.move_map = {
                KEYS['right']: ('rx', -1),
                KEYS['left']: ('rx', 1),
                KEYS['down']: ('ry', 1),
                KEYS['up']: ('ry', -1),
                KEYS['shift_up']: ('rz', -1),
                KEYS['shift_down']: ('rz', 1),
            }

        self.move_keys = tuple(self.move_map.keys())
        self.motor_names = ['RX', 'RY', 'RZ']

    def _setup_6axis_keys(self):
        """Setup key mappings for 6-axis mode (X, Y, Z, RX, RY, RZ)."""
        if self.orientation == 'horizontal':
            self.move_map = {
                KEYS['left']: ('x', -1),
                KEYS['right']: ('x', 1),
                KEYS['down']: ('y', -1),
                KEYS['up']: ('y', 1),
                KEYS['shift_up']: ('z', -1),
                KEYS['shift_down']: ('z', 1),
                'w': ('ry', 1),
                's': ('ry', -1),
                'd': ('rx', 1),
                'a': ('rx', -1),
                'W': ('rz', -1),
                'S': ('rz', 1),
            }
        else:  # vertical
            self.move_map = {
                KEYS['right']: ('x', -1),
                KEYS['left']: ('x', 1),
                KEYS['down']: ('y', 1),
                KEYS['up']: ('y', -1),
                KEYS['shift_up']: ('z', -1),
                KEYS['shift_down']: ('z', 1),
                'w': ('rx', -1),
                's': ('rx', 1),
                'd': ('ry', -1),
                'a': ('ry', 1),
                'W': ('rz', -1),
                'S': ('rz', 1),
            }

        self.move_keys = tuple(self.move_map.keys())
        self.motor_names = ['X', 'Y', 'Z', 'RX', 'RY', 'RZ']

    @property
    def scale_keys(self):
        """Return tuple of scale adjustment keys."""
        return (
            KEYS['plus'], KEYS['minus'], KEYS['equal'], KEYS['under'],
            KEYS['shift_right'], KEYS['shift_left']
        )

    def print_help(self):
        """Display control instructions."""
        print("\n" + "="*60)
        print(f"XLJ {self.mode.upper()} MODE CONTROL")
        print("="*60)

        if self.mode == 'translation':
            print("Arrow Keys:")
            print("  ← → : Move X axis")
            print("  ↑ ↓ : Move Y axis")
            print(" Shift+↑ ↓ : Move Z axis upstream/downstream")

        elif self.mode == 'rotation':
            print("Arrow Keys:")
            print("  ← → : Rotate RX axis")
            print("  ↑ ↓ : Rotate RY axis")
            print("  Shift+↑ ↓ : Rotate RZ axis")

        elif self.mode == '6axis':
            print("Translation:")
            print("  ← → : Move X axis")
            print("  ↑ ↓ : Move Y axis")
            print("  Shift+↑ ↓ : Move Z axis")
            print("\nRotation (horizontal camera):")
            print("  W/S : Rotate RY axis")
            print("  A/D : Rotate RX axis")
            print("  Shift+W/S : Rotate RZ axis")
            print("\nRotation (vertical camera):")
            print("  W/S : Rotate RX axis")
            print("  A/D : Rotate RY axis")
            print("  Shift+W/S : Rotate RZ axis")

        print("\nStep Size:")
        print("  + or = : Double step size")
        print("  - or _ : Halve step size")
        print("  Shift+→ : Double step size")
        print("  Shift+← : Halve step size")

        print("\nOther:")
        print("  h : Show this help")
        print("  q : Quit")
        print("="*60)

    def print_status(self):
        """Display current motor positions and step size."""
        print("\n" + "-"*60)
        print(f"Step size: {self.scale:.6f}")

        for i, motor in enumerate(self.motors):
            try:
                pos = motor.position
                name = self.motor_names[i] if i < len(
                    self.motor_names
                ) else motor.name
                print(f"{name:8s}: {pos:10.4f}")
            except Exception as e:
                print(f"{motor.name}: Error reading position ({e})")

        print("-"*60)

    def update_scale(self, factor: float):
        """
        Update step size by multiplication factor.

        Parameters
        ----------
        factor : float
            Multiplication factor (e.g., 2.0 to double, 0.5 to halve)
        """
        self.scale *= factor
        logger.info(f"Step size: {self.scale:.6f}")
        print(f"Step size: {self.scale:.6f}")

    def execute_move(self, motor, direction: int):
        """
        Execute relative motor move.

        Parameters
        ----------
        motor
            Motor object to move
        direction : int
            Direction multiplier: +1 or -1
        """
        movement = self.scale * direction

        try:
            motor.mvr(movement)
            logger.debug(f"Moved {motor.name} by {movement:.6f}")
        except Exception as e:
            logger.error(f"Error moving {motor.name}: {e}")
            print(f"Error: {e}")

    def run(self):
        """
        Run interactive control loop.

        Captures keyboard input and controls motors until
        user quits with 'q'.
        """
        # Print initial status
        self.print_help()
        self.print_status()

        # Save terminal settings
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)

        try:
            # Set terminal to raw mode for character capture
            tty.setraw(sys.stdin.fileno())

            while True:
                # Read one character/sequence
                char = sys.stdin.read(1)

                # Handle escape sequences (arrow keys)
                if char == '\x1b':
                    char += sys.stdin.read(2)  # Read rest of sequence
                    # Check for shift modifier
                    if char == '\x1b[1':
                        char += sys.stdin.read(3)  # Read full shift sequence

                # Process input
                if char == 'q':
                    break

                elif char == 'h':
                    self.print_help()
                    self.print_status()

                elif char in self.move_keys:
                    # Execute motor move
                    axis, direction = self.move_map[char]
                    motor_idx = self.motor_names.index(axis.upper())
                    self.execute_move(self.motors[motor_idx], direction)

                elif char in self.scale_keys:
                    # Adjust step size
                    if char in (KEYS['plus'], KEYS['equal'],
                                KEYS['shift_right']):
                        self.update_scale(2.0)
                    elif char in (KEYS['minus'], KEYS['under'],
                                  KEYS['shift_left']):
                        self.update_scale(0.5)

                else:
                    print(f"Unknown key. Press 'h' for help.")

        finally:
            # Restore terminal settings
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            print("\nControl loop exited")


# High-level control functions

def xlj_fast(orientation: str = 'horizontal', scale: float = 0.1):
    """
    Interactive XLJ translation control (X, Y, Z).

    Provides keyboard-based control for liquid jet X, Y, and Z
    positioning.

    Parameters
    ----------
    orientation : str, optional
        Camera view: 'horizontal' or 'vertical'.
        Default is 'horizontal'.
    scale : float, optional
        Initial step size in mm.
        Default is 0.1.

    Returns
    -------
    None

    Notes
    -----
    Controls:
    - Arrow keys: Move X and Y
    - Shift+↑ ↓ : Move Z upstream/downstream
    - +/- : Adjust step size
    - h : Help
    - q : Quit

    Examples
    --------
    >>> xlj_fast()  # Horizontal orientation
    >>> xlj_fast('vertical', 0.05)  # Vertical, smaller steps

    See Also
    --------
    xlj_fast_rot : Rotation control
    xlj_6axis : Full 6-axis control
    """
    xlj_x = BypassPositionCheck("MFX:LJH:JET:X", name="xlj_x")
    xlj_y = BypassPositionCheck("MFX:LJH:JET:Y", name="xlj_y")
    xlj_z = BypassPositionCheck("MFX:LJH:JET:Z", name="xlj_z")

    motors = [xlj_x, xlj_y, xlj_z]
    ctrl = XLJController(motors, orientation, scale, 'translation')
    ctrl.xlj = BeckhoffJet('MFX:LJH', name='xlj')

    logger.info("Starting XLJ translation control")
    ctrl.run()


def xlj_fast_rot(orientation: str = 'horizontal', scale: float = 0.1):
    """
    Interactive XLJ rotation control (RX, RY, RZ).

    Provides keyboard-based control for liquid jet rotation axes.

    Parameters
    ----------
    orientation : str, optional
        Camera view. Default is 'horizontal'.
    scale : float, optional
        Initial step size in degrees.
        Default is 0.1.

    Returns
    -------
    None

    Notes
    -----
    Controls:
    - Arrow keys: Rotate RX and RY
    - Shift+↑ ↓ : Rotate RZ
    - +/- : Adjust step size
    - h : Help
    - q : Quit

    Examples
    --------
    >>> xlj_fast_rot()
    >>> xlj_fast_rot('vertical', 0.05)

    See Also
    --------
    xlj_fast : Translation control
    xlj_6axis : Full 6-axis control
    """
    xlj_rx = IMS("MFX:HRA:MMS:02", name="xlj_rx")
    xlj_ry = IMS("MFX:HRA:MMS:04", name="xlj_ry")
    xlj_rz = IMS("MFX:HRA:MMS:03", name="xlj_rz")

    motors = [xlj_rx, xlj_ry, xlj_rz]
    ctrl = XLJController(motors, orientation, scale, 'rotation')

    logger.info("Starting XLJ rotation control")
    ctrl.run()


def xlj_6axis(orientation: str = 'horizontal', scale: float = 0.1):
    """
    Interactive XLJ 6-axis control (X, Y, Z, RX, RY, RZ).

    Provides complete keyboard-based control for all liquid jet
    degrees of freedom.

    Parameters
    ----------
    orientation : str, optional
        Camera view. Default is 'horizontal'.
    scale : float, optional
        Initial step size (mm for translation, deg for rotation).
        Default is 0.1.

    Returns
    -------
    None

    Notes
    -----
    Controls:
    - Arrow keys: Move X and Y
    - Shift+↑ ↓ : Move Z
    - W/S: Rotate RY (horizontal) or RX (vertical)
    - A/D: Rotate RX (horizontal) or RY (vertical)
    - Shift+W/S: Rotate RZ
    - +/- : Adjust step size
    - h : Help
    - q : Quit

    Examples
    --------
    >>> xlj_6axis()
    >>> xlj_6axis('vertical', 0.05)

    See Also
    --------
    xlj_fast : Translation only
    xlj_fast_rot : Rotation only
    """
    xlj_x = BypassPositionCheck("MFX:LJH:JET:X", name="xlj_x")
    xlj_y = BypassPositionCheck("MFX:LJH:JET:Y", name="xlj_y")
    xlj_z = BypassPositionCheck("MFX:LJH:JET:Z", name="xlj_z")
    xlj_rx = IMS("MFX:HRA:MMS:02", name="xlj_rx")
    xlj_ry = IMS("MFX:HRA:MMS:04", name="xlj_ry")
    xlj_rz = IMS("MFX:HRA:MMS:03", name="xlj_rz")

    motors = [xlj_x, xlj_y, xlj_z, xlj_rx, xlj_ry, xlj_rz]
    ctrl = XLJController(motors, orientation, scale, '6axis')
    ctrl.xlj = BeckhoffJet('MFX:LJH', name='xlj')

    logger.info("Starting XLJ 6-axis control")
    ctrl.run()


logger.info("XLJ fast control utilities loaded and ready")