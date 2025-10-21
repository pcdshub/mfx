"""
Basic Lens object handling
"""
############
# Standard #
############
import logging
import re
import time

###############
# Third Party #
###############
import numpy as np
import prettytable
from ophyd import EpicsSignalRO, EpicsSignal, Component as Cpt, Device, FormattedComponent as FCpt
from pcdsdevices.inout import InOutPVStatePositioner
from pcdsdevices.pv_positioner import OnePVMotor

##########
# Module #
##########
import tfs.utils as ut

logger = logging.getLogger(__name__)

class OnePVMotorRetry(OnePVMotor):
    """OnePVMotor with a simple retry-to-tolerance move helper.

    Usage: motor.mv_retry(target, retries=3, tolerance=1e-3)
    """

    def mv_retry(self, position, *, retries=3, tolerance=1e-2, settle_time=0.2, timeout=None):
        """Move to position with verify-and-retry until within tolerance.

        Parameters
        ----------
        position : float
            Desired setpoint in engineering units.
        retries : int, optional
            Number of additional attempts after the first move, by default 3.
        tolerance : float, optional
            Allowed absolute error |RBV - SP|, by default 1e-2.
        settle_time : float, optional
            Seconds to wait after move completion before checking RBV, by default 0.2.
        timeout : float | None, optional
            Move timeout passed through to the underlying move call.
        """
        attempts = retries + 1
        last_readback = None
        for attempt_index in range(attempts):
            status = self.move(position, wait=True, timeout=timeout)
            if settle_time and settle_time > 0:
                time.sleep(settle_time)
            try:
                last_readback = self.position
            except Exception:
                last_readback = None
            if last_readback is not None and abs(last_readback - position) <= tolerance:
                return status
            logger.warning(
                "Motor %s missed target (attempt %d/%d): target=%s readback=%s tol=%s",
                getattr(self, 'name', repr(self)),
                attempt_index + 1,
                attempts,
                position,
                last_readback,
                tolerance,
            )

LENS_MOTOR_PVS = {
    2: {'x': 'MFX:TFS:MMS:03', 'y': 'MFX:TFS:MMS:04'},
    3: {'x': 'MFX:TFS:MMS:05', 'y': 'MFX:TFS:MMS:06'},
    4: {'x': 'MFX:TFS:MMS:07', 'y': 'MFX:TFS:MMS:08'},
    5: {'x': 'MFX:TFS:MMS:09', 'y': 'MFX:TFS:MMS:10'},
    6: {'x': 'MFX:TFS:MMS:11', 'y': 'MFX:TFS:MMS:12'},
    7: {'x': 'MFX:TFS:MMS:13', 'y': 'MFX:TFS:MMS:14'},
    8: {'x': 'MFX:TFS:MMS:15', 'y': 'MFX:TFS:MMS:16'},
    9: {'x': 'MFX:TFS:MMS:17', 'y': 'MFX:TFS:MMS:18'},
    10: {'x': 'MFX:TFS:MMS:19', 'y': 'MFX:TFS:MMS:20'},
}


def _parse_lens_number(prefix):
    """Parse the lens number from the device prefix.

    Strategy: find the last integer substring in the prefix and use it.
    """
    numbers = re.findall(r'(\d+)', prefix)
    if not numbers:
        raise ValueError(f"Cannot parse lens number from prefix {prefix}")
    return int(numbers[-1])


class LensTripLimits(Device):
    """Trip limits for a given pre-focus lens (or lack thereof)."""
    # _table_name = Cpt(EpicsSignalRO, ":STR", doc="Table name for trip information")
    low = Cpt(EpicsSignalRO, ":LOW", doc="Trip region low [um]", auto_monitor=False)
    high = Cpt(EpicsSignalRO, ":HIGH", doc="Trip region high [um]", auto_monitor=False)


class LensCalcMixin():
    def __init__(self, *args, **kwargs):
        """
        Mixin class to abstract focal length calculation from a variety of 
        lens devices.
        
        Relies on the following methods / attributes from the child class:
        - self.radius
        - self.z
        """
        return

    def focus(self, energy):
        return ut.focal_length(self.radius, energy)
    
    def image_from_obj(self, z_obj, energy):
        """
        Method calculates the image distance in meters along the beam pipeline
        from a point of origin given the focal length of the lens, location of
        lens, and location of object.

        Parameters
        ----------
        z_obj
            Location of object along the beamline in meters (m)

        Returns
        -------
        image
            Returns the distance z_im of the image along the beam pipeline from
            a point of origin in meters (m)
        Note
        ----
        If the location of the object (z_obj) is equal to the focal length of
        the lens, this function will return infinity.
        """
        # Find the object location for the lens
        obj = self.z - z_obj
        # Check if the lens object is at the focal length
        # If this happens, then the image location will be infinity.
        # Note, this should not effect the recursive calculations that occur
        # later in the code
        if obj == self.focus(energy):
            return np.inf
        # Calculate the location of the focal plane
        plane = 1/(1/self.focus(energy) - 1/obj)
        # Find the position in accelerator coordinates
        return plane + self.z


class MFXLens(InOutPVStatePositioner, LensCalcMixin):
    """
    Data structure for basic Lens object

    Parameters
    ----------
    prefix : str
        Name of the state record that controls the PV

    prefix_lens : str
        Prefix for the PVs that contain focusing information
    """
    # StatePositioner information
    _inserted = Cpt(EpicsSignalRO, ':STATE')
    _removed = Cpt(EpicsSignalRO, ":OUT")
    _insert = Cpt(EpicsSignal, ':INSERT')
    _remove = Cpt(EpicsSignal, ':REMOVE')
    _state_logic = {'_inserted': {0: 'defer',  1: 'IN'},
                    '_removed': {0: 'defer', 1: 'OUT'}}
    # Signals related to optical configuration
    _sig_radius = Cpt(EpicsSignalRO, ":RADIUS", auto_monitor=True)
    _sig_z = Cpt(EpicsSignalRO, ":Z", auto_monitor=True)
    _sig_focus = Cpt(EpicsSignalRO, ":FOCUS", auto_monitor=True)
    # Default configuration attributes. Read attributes are set correctly by
    # InOutRecordPositioner
    _default_configuration_attrs = ['_sig_radius', '_sig_z']
    # Signal for requested focus
    _req_focus = Cpt(EpicsSignal, ':REQ_FOCUS')
    
    # X/Y motors resolved from PV map based on lens number in prefix
    x = FCpt(OnePVMotorRetry, '{x_pv}', kind='normal')
    y = FCpt(OnePVMotorRetry, '{y_pv}', kind='normal')

    def __init__(self, prefix, **kwargs):
        if 'TFS' not in prefix:
            self.x_pv = None
            self.y_pv = None
        else:
            lens_num = _parse_lens_number(prefix)
            try:
                mapping = LENS_MOTOR_PVS[lens_num]
            except KeyError:
                raise ValueError(f"Unknown lens number {lens_num} parsed from prefix {prefix}")
            self.x_pv = mapping['x']
            self.y_pv = mapping['y']
        super().__init__(prefix, **kwargs)
        

    @property
    def radius(self):
        """
        Method converts the EPICS lens radius signal into a float that can be
        used for calculations.

        Returns
        -------
        float
            Returns the radius of the lens
        """
        return self._sig_radius.get()

    @property
    def z(self):
        """
        Method converts the z position EPICS signal into a float.

        Returns
        -------
        float
            Returns the z position of the lens in meters along the beamline
        """
        return self._sig_z.get()

    @property
    def sig_focus(self):
        """
        Method converts the EPICS focal length signal of the lens into a float

        Returns
        -------
        float
            Returns the focal length of the lens in meters
        """
        return self._sig_focus.get()

    def _do_move(self, state):
        if state.name == 'IN':
            self._insert.put(1)
        elif state.name == 'OUT':
            self._remove.put(1)
        # We shouldn't ever get to this line as most calls will have gone
        # through check_value first. Just in case this is here to not fail
        # silently
        else:
            raise ValueError("Invalid State {}".format(state))


class LensConnect:
    """
    Data structure for a basic system of lenses

    Parameters
    ----------
    args : Lens
        Lens objects
    """
    def __init__(self, *args):
        """
        Parameters
        ----------
        args
            Variable length argument list of the lenses in the system, their
            radii, z position, and focal length.
        """
        self.lenses = sorted(args, key=lambda lens: lens.z)

    @property
    def effective_radius(self):
        """
        Method calculates the effective radius of the lens array
        including prefocusing lens 

        Returns
        -------
        float
            returns the effective radius of the lens array.
        """
        if not self.lenses:
            return 0.0
        return 1/np.sum(np.reciprocal([float(l.radius) for l in self.lenses]))


    @property
    def tfs_radius(self):
        """
        Method calculates the effective radius of the lens array
        excluding prefocusing lens 

        Returns
        -------
        float
            returns the effective radius of the lens array.
        """
        if not self.lenses:
            return 0.0
        return 1/np.sum(np.reciprocal([float(l.radius) for l in self.lenses if 'TFS' in getattr(l, 'prefix', '')]))


    def image(self, z_obj, energy):
        """
        Method recursively calculates the z location of the image of a system
        of lenses and returns it in meters (m)

        Parameters
        ----------
        z_obj
            Location of the object along the beam pipline from a designated
            point of origin in meters (m)

        Returns
        -------
        float
            returns the location z of a system of lenses in meters (m).
        """
        # Set the initial image as the z object
        image = z_obj
        # Determine the final output by looping through lenses
        for lens in self.lenses:
            image = lens.image_from_obj(image, energy)
        return image

    @property
    def nlens(self):
        """
        Method calculates the total number of lenses in the Lens array.

        Returns
        -------
        int
            Returns the total number of lenses in the array.
        """
        return len(self.lenses)

    def _info(self):
        """
        Create a table with lens information
        """
        # Create initial table
        pt = prettytable.PrettyTable(['Prefix', 'Radius', 'Z'])
        # Adjust table settings
        pt.align = 'l'
        pt.float_format = '8.5'
        for lens in self.lenses:
            pt.add_row([lens.prefix, lens.radius, lens.z])
        return pt

    def show_info(self):
        """
        Show a table of information on the lens
        """
        print(self._info())

    @classmethod
    def connect(cls, array1, array2):
        """
        Create a new LensConnect from the combination of multiple
        """
        return cls(*array1.lenses, *array2.lenses)
