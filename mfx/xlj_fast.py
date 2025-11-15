"""
XLJ Fast Motor Control Module

This module provides interactive keyboard-based control for the XLJ (X-ray Liquid Jet)
positioning system, supporting both translational (X, Y, Z) and rotational (RX, RY, RZ)
axes.
"""

import logging
from ophyd.device import Component as Cpt
from ophyd.signal import EpicsSignal
from pcdsdevices.epics_motor import IMS
from pcdsdevices.pv_positioner import PVPositionerDone
from pcdsdevices import utils
from pcdsdevices.jet import BeckhoffJet

logger = logging.getLogger(__name__)


class BypassPositionCheck(PVPositionerDone):
    """PV Positioner with position check bypass for fast movements."""
    setpoint = Cpt(EpicsSignal, ":PLC:fPosition")
    actuate = Cpt(EpicsSignal, ":PLC:bMoveCmd")


# Key mapping constants
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


class XLJController:
    """
    Controller class for XLJ motor movements.

    Attributes
    ----------
    motors : list
        List of motor objects to control
    orientation : str
        Camera orientation ('horizontal' or 'vertical')
    scale : float
        Current step size for movements
    """

    def __init__(self, motors, orientation='horizontal', scale=0.1, mode='translation'):
        """
        Initialize the XLJ controller.

        Parameters
        ----------
        motors : list
            List of motor objects to control
        orientation : str, optional
            Camera orientation, either 'horizontal' or 'vertical' (default: 'horizontal')
        scale : float, optional
            Initial step size for movements (default: 0.1)
        mode : str, optional
            Control mode: 'translation', 'rotation', or '6axis' (default: 'translation')
        """
        self.motors = motors
        self.orientation = orientation.lower()
        self.scale = scale
        self.mode = mode
        self._setup_key_mappings()

    def _setup_key_mappings(self):
        """Configure key mappings based on orientation and mode."""
        if self.mode == 'translation':
            self._setup_translation_keys()
        elif self.mode == 'rotation':
            self._setup_rotation_keys()
        elif self.mode == '6axis':
            self._setup_6axis_keys()
        else:
            raise ValueError(f"Invalid mode: {self.mode}. Use 'translation', 'rotation', or '6axis'")

    def _setup_translation_keys(self):
        """Set up key mappings for translation mode (X, Y, Z)."""
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

    def _setup_rotation_keys(self):
        """Set up key mappings for rotation mode (RX, RY, RZ)."""
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
                KEYS['up']: ('rx', -1),
                KEYS['down']: ('rx', 1),
                KEYS['right']: ('ry', -1),
                KEYS['left']: ('ry', 1),
                KEYS['shift_up']: ('rz', -1),
                KEYS['shift_down']: ('rz', 1),
            }
        self.move_keys = tuple(self.move_map.keys())

    def _setup_6axis_keys(self):
        """Set up key mappings for 6-axis mode (X, Y, Z, RX, RY, RZ)."""
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

    @property
    def scale_keys(self):
        """Return tuple of scale adjustment keys."""
        return (KEYS['plus'], KEYS['minus'], KEYS['equal'], KEYS['under'],
                KEYS['shift_right'], KEYS['shift_left'])

    def show_status(self):
        """Display current motor positions and scale."""
        template = '{}: {:.4f}' if self.scale >= 0.0001 else '{}: {:.4e}'
        text = [template.format(mot.name, mot.wm()) for mot in self.motors]
        text.append(f'scale: {self.scale}')
        print('\x1b[2K\r' + ', '.join(text), end='')

    def show_usage(self):
        """Display usage instructions."""
        print()
        if self.mode == 'translation':
            print(" Arrow keys: Move X and Y")
            print(" Shift+Up/Down: Move Z upstream/downstream")
        elif self.mode == 'rotation':
            print(" Arrow keys: Rotate RX and RY")
            print(" Shift+Up/Down: Rotate RZ")
        else:  # 6axis
            print(" Arrow keys: Move X and Y")
            print(" Shift+Up/Down: Move Z upstream/downstream")
            print(" W/S: Rotate RY (horizontal) or RX (vertical)")
            print(" A/D: Rotate RX (horizontal) or RY (vertical)")
            print(" Shift+W/S: Rotate RZ")
        print(" +/Shift+Right: Double scale")
        print(" -/Shift+Left: Halve scale")
        print(" h: Show this help")
        print(" q: Quit")
        print()

    def adjust_scale(self, direction):
        """
        Adjust the movement scale.

        Parameters
        ----------
        direction : str
            Key input for scale adjustment

        Returns
        -------
        float
            Updated scale value
        """
        if direction in (KEYS['shift_right'], KEYS['plus'], KEYS['equal']):
            self.scale *= 2
        elif direction in (KEYS['shift_left'], KEYS['minus'], KEYS['under']):
            self.scale /= 2
        return self.scale

    def execute_movement(self, inp):
        """
        Execute motor movement based on key input.

        Parameters
        ----------
        inp : str
            Key input for movement direction
        """
        if inp not in self.move_map:
            return

        axis, direction = self.move_map[inp]
        motor_index = {'x': 0, 'y': 1, 'z': 2, 'rx': 3, 'ry': 4, 'rz': 5}

        if axis in motor_index and motor_index[axis] < len(self.motors):
            motor = self.motors[motor_index[axis]]
            movement = self.scale * direction

            try:
                # Special handling for Z axis with jet position check
                if axis == 'z' and hasattr(self, 'xlj'):
                    if round(self.xlj.jet.z(), 2) != round(motor(), 2):
                        logger.error(f'xlj.jet.z = {self.xlj.jet.z()}, '
                                   f'{motor.name} = {motor()}')
                        motor.umv(self.xlj.jet.z())

                motor.umvr(movement, log=False, newline=False)
            except Exception as exc:
                logger.error('Error in tweak move: %s', exc)
                logger.debug('', exc_info=True)

    def run(self):
        """Run the interactive control loop."""
        start_text = [f'{mot.name} at {mot.wm():.4f}' for mot in self.motors]
        logger.info('Started tweak of ' + ', '.join(start_text))
        self.show_usage()

        is_input = True
        while is_input:
            self.show_status()
            inp = utils.get_input()

            if inp == 'q':
                is_input = False
            elif inp in self.move_keys:
                self.execute_movement(inp)
            elif inp in self.scale_keys:
                self.adjust_scale(inp)
            elif inp == 'h':
                self.show_usage()
            else:
                logger.error('Invalid input. Press "h" for help.')

        print()
        logger.info('Tweak complete')


def xlj_fast_xyz(orientation='horizontal', scale=0.1):
    """
    Interactive keyboard control for XLJ translation axes (X, Y, Z).

    Parameters
    ----------
    orientation : str, optional
        Camera orientation: 'horizontal' or 'vertical' (default: 'horizontal')
    scale : float, optional
        Initial step size for movements (default: 0.1)

    Controls
    --------
    - Arrow keys: Move X and Y axes
    - Shift+Up/Down: Move Z axis upstream/downstream
    - +/- or Shift+Right/Left: Double/halve step size
    - h: Display help
    - q: Quit
    """
    xlj_fast_x = BypassPositionCheck("MFX:LJH:JET:X", name="xlj_fast_x")
    xlj_fast_y = BypassPositionCheck("MFX:LJH:JET:Y", name="xlj_fast_y")
    xlj_fast_z = BypassPositionCheck("MFX:LJH:JET:Z", name="xlj_fast_z")

    motors = [xlj_fast_x, xlj_fast_y, xlj_fast_z]
    controller = XLJController(motors, orientation, scale, mode='translation')
    controller.xlj = BeckhoffJet('MFX:LJH', name='xlj')
    controller.run()


def xlj_fast_rot(orientation='horizontal', scale=0.1):
    """
    Interactive keyboard control for XLJ rotation axes (RX, RY, RZ).

    Parameters
    ----------
    orientation : str, optional
        Camera orientation: 'horizontal' or 'vertical' (default: 'horizontal')
    scale : float, optional
        Initial step size for rotations (default: 0.1)

    Controls
    --------
    - Arrow keys: Rotate RX and RY axes
    - Shift+Up/Down: Rotate RZ axis
    - +/- or Shift+Right/Left: Double/halve step size
    - h: Display help
    - q: Quit
    """
    xlj_fast_rx = IMS("MFX:HRA:MMS:02", name="xlj_fast_rx")
    xlj_fast_ry = IMS("MFX:HRA:MMS:04", name="xlj_fast_ry")
    xlj_fast_rz = IMS("MFX:HRA:MMS:03", name="xlj_fast_rz")

    motors = [xlj_fast_rx, xlj_fast_ry, xlj_fast_rz]
    controller = XLJController(motors, orientation, scale, mode='rotation')
    controller.run()


def xlj_6axis(orientation='horizontal', scale=0.1):
    """
    Interactive keyboard control for all XLJ axes (X, Y, Z, RX, RY, RZ).

    Parameters
    ----------
    orientation : str, optional
        Camera orientation: 'horizontal' or 'vertical' (default: 'horizontal')
    scale : float, optional
        Initial step size for movements (default: 0.1)

    Controls
    --------
    - Arrow keys: Move X and Y axes
    - Shift+Up/Down: Move Z axis upstream/downstream
    - W/S: Rotate RY (horizontal) or RX (vertical)
    - A/D: Rotate RX (horizontal) or RY (vertical)
    - Shift+W/S: Rotate RZ
    - +/- or Shift+Right/Left: Double/halve step size
    - h: Display help
    - q: Quit
    """
    xlj_fast_x = BypassPositionCheck("MFX:LJH:JET:X", name="xlj_fast_x")
    xlj_fast_y = BypassPositionCheck("MFX:LJH:JET:Y", name="xlj_fast_y")
    xlj_fast_z = BypassPositionCheck("MFX:LJH:JET:Z", name="xlj_fast_z")
    xlj_fast_rx = IMS("MFX:HRA:MMS:02", name="xlj_fast_rx")
    xlj_fast_ry = IMS("MFX:HRA:MMS:04", name="xlj_fast_ry")
    xlj_fast_rz = IMS("MFX:HRA:MMS:03", name="xlj_fast_rz")

    motors = [xlj_fast_x, xlj_fast_y, xlj_fast_z, xlj_fast_rx, xlj_fast_ry, xlj_fast_rz]
    controller = XLJController(motors, orientation, scale, mode='6axis')
    controller.xlj = BeckhoffJet('MFX:LJH', name='xlj')
    controller.run()