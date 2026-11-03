"""
Connect to the PVs used by the HXU K scan and print value or NOT CONNECTED.

Run before the shift from any machine on the controls network:
    python scripts/undulator_pv_check.py
Add PVs to the list as the machine side confirms them.
"""

import sys

from epics import PV

PVS = [
    # K request and done flag
    ('MFX:USER:MCC:EPHOT:SET2', 'K request setpoint (eV)'),
    ('SIOC:SYS0:ML07:AO805', 'done PV, 0 moving / 1 done'),
    # undulator readbacks, first and last HXU segments
    ('USEG:UNDH:1850:GapAct', 'gap readback, seg 18'),
    ('USEG:UNDH:1850:KAct', 'K readback, seg 18'),
    ('USEG:UNDH:2050:GapAct', 'gap readback, seg 20'),
    ('USEG:UNDH:2050:KAct', 'K readback, seg 20'),
    ('USEG:UNDH:1850:DeviceActive', 'segment active, seg 18'),
    ('USEG:UNDH:1850:STATSUMY', 'status summary, seg 18'),
    # beam
    ('SIOC:SYS0:ML00:AO627', 'photon eV HXR'),
    ('BLD:SYS0:500:PHOTONENERGY', 'BLD photon energy'),
    ('GDET:FEE1:241:ENRC', 'gas detector (mJ)'),
    ('EVNT:SYS0:1:LCLSBEAMRATE', 'beam rate (Hz)'),
    # dccm state: insert() and remove() use different case
    ('SP1L0:DCCM:MMS:STATE:SET', 'DCCM state set, used by insert()'),
    ('SP1L0:DCCM:MMS:State:SET', 'DCCM state set, used by remove()'),
]


def main(timeout=2.0):
    pvs = [(PV(name, connection_timeout=timeout), desc) for name, desc in PVS]
    missing = 0
    for pv, desc in pvs:
        if pv.wait_for_connection(timeout=timeout):
            value = pv.get(as_string=True)
            print(f"ok   {pv.pvname:32s} {str(value):>16s}  {desc}")
        else:
            missing += 1
            print(f"NC   {pv.pvname:32s} {'NOT CONNECTED':>16s}  {desc}")
    print(f"\n{len(pvs) - missing}/{len(pvs)} connected")
    return 1 if missing else 0


if __name__ == '__main__':
    sys.exit(main())
