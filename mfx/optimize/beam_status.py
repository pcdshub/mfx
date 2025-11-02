import logging
from ophyd.device import Component as Cpt
from ophyd.device import Device
from ophyd.signal import EpicsSignalRO
from pcdsdevices.interface import BaseInterface
from pcdsdevices.signal import AvgSignal

logger = logging.getLogger(__name__)

class BeamCheck(BaseInterface, Device):
    ev = Cpt(EpicsSignalRO, 'BLD:SYS0:500:PHOTONENERGY', kind='normal',
            doc='Photon Energy [eV]')
    mj1 = Cpt(EpicsSignalRO, 'GDET:FEE1:241:ENRC', kind='hinted',
            doc='Pulse energy [mJ]')
    mj2 = Cpt(EpicsSignalRO, 'GDET:FEE1:242:ENRC', kind='hinted',
            doc='Pulse energy [mJ]')
    mj3 = Cpt(EpicsSignalRO, 'GDET:FEE1:361:ENRC', kind='hinted',
            doc='Pulse energy [mJ]')
    mj4 = Cpt(EpicsSignalRO, 'GDET:FEE1:362:ENRC', kind='hinted',
            doc='Pulse energy [mJ]')
    mj_avg1 = Cpt(AvgSignal, 'mj1', averages=120, kind='normal')
    mj_avg2 = Cpt(AvgSignal, 'mj2', averages=120, kind='normal')
    mj_avg3 = Cpt(AvgSignal, 'mj3', averages=120, kind='normal')
    mj_avg4 = Cpt(AvgSignal, 'mj4', averages=120, kind='normal')

    tab_component_names = True

    def __init__(self, prefix='', name='beam_status', **kwargs):
        super().__init__(prefix=prefix, name=name, **kwargs)

    def gdet_ave(self, threashold=0.1):
        mj_avg_list = [self.mj_avg1.get(), self.mj_avg2.get(),
                    self.mj_avg3.get(), self.mj_avg4.get()]
        for mj_avg in mj_avg_list:
            if mj_avg > threashold:
                var_value = True
            else:
                var_value = False
            log_level = logger.info if var_value else logger.error
            log_level(
                f"Detector:{'ON' if var_value else 'OFF'} - Average Pulse Energy: {mj_avg:.2f} mJ")
        mj_avg_list = [mj_avg for mj_avg in mj_avg_list if mj_avg > threashold]
        if not mj_avg_list:
            logger.error("All GDET detectors are OFF!")
            return 0.0

        all_avg = sum(mj_avg for mj_avg in mj_avg_list) / len(mj_avg_list)
        logger.warning(f"Average Pulse Energy from ON detectors: {all_avg:.2f} mJ")
        return all_avg