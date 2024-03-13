def attenuator_scan_separate_runs(
        events: int =240,
        record: bool =False,
        transmissions: list = [0.01,0.02,0.03],
        use_daq: bool = True
) -> None:
    """
    Runs through attenuator conditions and records each as an individual run

    Parameters
    ----------
    events: int, optional
        number of events. default 240

    record: bool, optional
        set True to record

    transmissions: list of floats, optional
        list of transmissions to run through. default [0.01,0.02,0.03]

    use_daq: bool, optional
        Whether to include the DAQ or not. Default: True. If False can run the
        scans while using the DAQ elsewhere.

    Operations
    ----------

    """
    from time import sleep
    from mfx.db import att, pp
    if use_daq:
        from mfx.db import daq

    pp.open()
    for i in transmissions:
        att(i)
        sleep(3)
        if use_daq:
            daq.begin(events=events,record=record,wait=True, use_l3t=False)
            daq.end_run()
    pp.close()
    if use_daq:
        daq.disconnect()


def attenuator_scan_single_run(
        events: int = 240,
        record: bool = False,
        transmissions: list = [0.01,0.02,0.03],
        use_daq: bool = True
) -> None:
    """
    Runs through attenuator conditions and records them all as one continuous run

    Parameters
    ----------
    events: int, optional
        number of events. default 240

    record: bool, optional
        set True to record

    transmissions: list of floats, optional
        list of transmissions to run through. default [0.01,0.02,0.03]

    use_daq: bool, optional
        Whether to include the DAQ or not. Default: True. If False can run the
        scans while using the DAQ elsewhere.

    Operations
    ----------

    """
    from time import sleep
    from mfx.db import att, pp

    if use_daq:
        from mfx.db import daq
        daq.end_run()
        daq.disconnect()

    try:
        pp.open()
        if use_daq:
            daq.configure(record=record)
        sleep(3)
        for i in transmissions:
            att(i,wait=True)
            sleep(3)
            if use_daq:
                daq.begin(events=events,record=record,wait=True, use_l3t=False)
    finally:
        if use_daq:
            daq.end_run()
            daq.disconnect()
        pp.close()
