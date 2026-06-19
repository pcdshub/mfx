from pcdsdevices.epics_motor import SmarAct

sa_x = SmarAct('MFX:CHAPMAN:saX', name='sa_z')
sa_y = SmarAct('MFX:CHAPMAN:saY', name='sa_y')
sa_z = SmarAct('MFX:CHAPMAN:saZ', name='sa_z')
