"""
Basic Lens object handling
"""
############
# Standard #
############
import logging

###############
# Third Party #
###############
import numpy as np
import prettytable
from ophyd import EpicsSignalRO, EpicsSignal, Component as Cpt, Device
from pcdsdevices.inout import InOutPVStatePositioner

##########
# Module #
##########
import tfs.utils as ut

logger = logging.getLogger(__name__)


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

    def __init__(self, prefix, **kwargs):
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

        Returns
        -------
        float
            returns the effective radius of the lens array.
        """
        if not self.lenses:
            return 0.0
        return 1/np.sum(np.reciprocal([float(l.radius) for l in self.lenses]))

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
