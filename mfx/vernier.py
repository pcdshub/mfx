class Vernier:
    def __init__(self):

    def scan(
            self,
            energy_scan_start_eV: float,
            energy_scan_end_eV: float,
            energy_scan_steps: int,
            events_per_step: int = 120,
            record: bool = False,
            mcc_pv: str = 'MFX:USER:MCC:EPHOT:SET1'):
        """Perform Vernier scan.

        Parameters:

            energy_scan_start_eV (float): Photon energy (in eV) to start the scan at.

            energy_scan_end_eV (float): Photon energy (in eV) to end the scan at.

            energy_scan_steps (int): Number of steps in scan.

            events_per_step (int): Number of events per step. Optional. Default: 120.

            record (bool): whether to record the scan or not. Optional. Default: False.

            mcc_pv (str): Vernier PV. Optional. Default: 'MFX:USER:MCC:EPHOT:SET1'.
        """
        from ophyd import EpicsSignal
        try:
            from mfx.db import RE
        except ImportError:
            RE = RunEngine({})
        RE(
            bp.daq_scan(
                [],
                EpicsSignal(mcc_pv, name='mcc'),
                energy_scan_start_eV,
                energy_scan_end_eV,
                energy_scan_steps,
                events=events_per_step,
                record=record))