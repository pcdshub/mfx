import logging
from ophyd.device import Component as Cpt
from ophyd.signal import EpicsSignal
from pcdsdevices.pv_positioner import PVPositionerDone
from pcdsdevices import utils
from pcdsdevices.jet import BeckhoffJet

logger = logging.getLogger(__name__)


class BypassPositionCheck(PVPositionerDone):
    setpoint = Cpt(EpicsSignal, ":PLC:fPosition")
    actuate = Cpt(EpicsSignal, ":PLC:bMoveCmd")


def xlj_fast_xyz(orientation='horizontal', scale=0.1):
    """
    Parameters
    ----------
    orientation: str, optional
        set orientation to change the x and y axis. horizontal by default
        use only 'horizontal' of 'vertical'

    scale: float, optional
        starting scale for the step size

    Operations
    ----------
    Base function to control motors with the arrow keys.

    With three motors, you can use the right and left arrow keys to move right 
    and left, up and down arrow keys to move up and down, and Shift+up and 
    shift+down to move z in and out

    The scale for the tweak can be doubled by pressing + and halved by pressing
    -. Shift+right and shift+left can also be used, and the up and down keys will
    also adjust the scaling in one motor mode. The starting scale can be set
    with the keyword argument `scale`.

    Ctrl+c will stop an ongoing move during a tweak without exiting the tweak.
    Both q and ctrl+c will quit the tweak between moves.
    """

    if orientation == str('horizontal').lower():
        xlj_fast_x = BypassPositionCheck("MFX:LJH:JET:X", name="xlj_fast_x")
        xlj_fast_y = BypassPositionCheck("MFX:LJH:JET:Y", name="xlj_fast_y")

    if orientation == str('vertical').lower():
        xlj_fast_y = BypassPositionCheck("MFX:LJH:JET:X", name="xlj_fast_x")
        xlj_fast_x = BypassPositionCheck("MFX:LJH:JET:Y", name="xlj_fast_y")

    xlj_fast_z = BypassPositionCheck("MFX:LJH:JET:Z", name="xlj_fast_z")

    xlj = BeckhoffJet('MFX:LJH', name='xlj')

    up = "\x1b[A"
    down = "\x1b[B"
    right = "\x1b[C"
    left = "\x1b[D"
    shift_up = "\x1b[1;2A"
    shift_down = "\x1b[1;2B"
    shift_right = "\x1b[1;2C"
    shift_left = "\x1b[1;2D"
    alt_up = "\x1b[1;3A"
    alt_down = "\x1b[1;3B"
    alt_right = "\x1b[1;3C"
    alt_left = "\x1b[1;3D"
    ctrl_up = "\x1b[1;5A"
    ctrl_down = "\x1b[1;5B"
    ctrl_right = "\x1b[1;5C"
    ctrl_left = "\x1b[1;5D"
    plus = "+"
    equal = "="
    minus = "-"
    under = "_"

    abs_status = '{}: {:.4f}'
    exp_status = '{}: {:.4e}'

    move_keys = (left, right, up, down, shift_up, shift_down)
    scale_keys = (plus, minus, equal, under, shift_right, shift_left)
    motors = [xlj_fast_x, xlj_fast_y, xlj_fast_z]


    def show_status():
        if scale >= 0.0001:
            template = abs_status
        else:
            template = exp_status
        text = [template.format(mot.name, mot.wm()) for mot in motors]
        text.append(f'scale: {scale}')
        print('\x1b[2K\r' + ', '.join(text), end='')


    def usage():
        print()  # Newline
        print(" Left: move x motor left")
        print(" Right: move x motor right")
        print(" Down: move y motor down")
        print(" Up: move y motor up")
        print(" shift+up: Z upstream")
        print(" shift+down: Z downstream")
        print(" + or shift+right: scale*2")
        print(" - or shift+left: scale/2")
        print(" Press q to quit."
              " Press any other key to display this message.")
        print()  # Newline


    def edit_scale(scale, direction):
        """Function used to change the scale."""
        if direction in (up, shift_right, plus, equal):
            scale = scale*2
        elif direction in (down, shift_left, minus, under):
            scale = scale/2
        return scale


    def movement(scale, direction):
        """Function used to know when and the direction to move the motor."""
        try:
            if direction == left:
                if round(xlj.jet.x(), 2) != round(xlj_fast_x(), 2):
                    logger.error(f'xlj.jet.x = {xlj.jet.x()}, xlj_fast_x = {xlj_fast_x()}')
                    xlj_fast_x.umv(xlj.jet.x())
                xlj_fast_x.umvr(-scale, log=False, newline=False)
            elif direction == right:
                if round(xlj.jet.x(), 2) != round(xlj_fast_x(), 2):
                    logger.error(f'xlj.jet.x = {xlj.jet.x()}, xlj_fast_x = {xlj_fast_x()}')
                    xlj_fast_x.umv(xlj.jet.x())
                xlj_fast_x.umvr(scale, log=False, newline=False)
            elif direction == up:
                if round(xlj.jet.y(), 2) != round(xlj_fast_y(), 2):
                    logger.error(f'xlj.jet.y = {xlj.jet.y()}, xlj_fast_y = {xlj_fast_y()}')
                    xlj_fast_y.umv(xlj.jet.y())
                xlj_fast_y.umvr(scale, log=False, newline=False)
            elif direction == down:
                if round(xlj.jet.y(), 2) != round(xlj_fast_y(), 2):
                    logger.error(f'xlj.jet.y = {xlj.jet.y()}, xlj_fast_y = {xlj_fast_y()}')
                    xlj_fast_y.umv(xlj.jet.y())
                xlj_fast_y.umvr(-scale, log=False, newline=False)
            elif direction == shift_up:
                if round(xlj.jet.z(), 2) != round(xlj_fast_z(), 2):
                    logger.error(f'xlj.jet.z = {xlj.jet.z()}, xlj_fast_z = {xlj_fast_z()}')
                    xlj_fast_z.umv(xlj.jet.z())
                xlj_fast_z.umvr(-scale, log=False, newline=False)
            elif direction == shift_down:
                if round(xlj.jet.z(), 2) != round(xlj_fast_z(), 2):
                    logger.error(f'xlj.jet.z = {xlj.jet.z()}, xlj_fast_z = {xlj_fast_z()}')
                    xlj_fast_z.umv(xlj.jet.z())
                xlj_fast_z.umvr(scale, log=False, newline=False)
        except Exception as exc:
            logger.error('Error in tweak move: %s', exc)
            logger.debug('', exc_info=True)

    start_text = [f'{mot.name} at {mot.wm():.4f}' for mot in motors]
    logger.info('Started tweak of ' + ', '.join(start_text))
    usage()

    # Loop takes in user key input and stops when 'q' is pressed
    is_input = True
    while is_input is True:
        show_status()
        inp = utils.get_input()
        if inp in ('q'):
            is_input = False
        elif inp in move_keys:
            movement(scale, inp)
        elif inp in scale_keys:
            scale = edit_scale(scale, inp)
        elif inp in ('h'):
            usage()
        else:
            logger.error('Not the way to use this. Press "h" to see how.')
    print()
    logger.info('Tweak complete')