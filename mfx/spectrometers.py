# import logging
# from ophyd.device import Component as Cpt
# from pcdsdevices.epics_motor import BeckhoffAxis
# from pcdsdevices.interface import BaseInterface
# from pcdsdevices.device import GroupDevice
# from pcdsdevices.spectrometer import VonHamosCrystal_2

# logger = logging.getLogger(__name__)


# class Crystal6(BaseInterface, GroupDevice):
#     """ MFX 6-crystal VonHamos spectrometer """
#     tab_component_names = True

#     c1 = Cpt(VonHamosCrystal_2, ':C1', kind='normal')
#     c2 = Cpt(VonHamosCrystal_2, ':C2', kind='normal')
#     c3 = Cpt(VonHamosCrystal_2, ':C3', kind='normal')
#     c4 = Cpt(VonHamosCrystal_2, ':C4', kind='normal')
#     c5 = Cpt(VonHamosCrystal_2, ':C5', kind='normal')
#     c6 = Cpt(VonHamosCrystal_2, ':C6', kind='normal')

#     rot = Cpt(BeckhoffAxis, ':ROT', kind='normal')
#     y = Cpt(BeckhoffAxis, ':T1', kind='normal')
#     x_bottom = Cpt(BeckhoffAxis, ':T2', kind='normal')
#     x_top = Cpt(BeckhoffAxis, ':T3', kind='normal')


import logging
from mfx.db import mfx_von_hamos_6crystal as mvh6

logger = logging.getLogger(__name__)


class VonHamos6Crystal:
    def __init__(self):
        pass

    class c1:
        def __init__(self):
            pass

        def trans():
            return mvh6.c1.x()

        def yaw():
            return mvh6.c1.rot()

        def pitch():
            return mvh6.c1.tilt()
