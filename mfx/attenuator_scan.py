def attenuator_scan_separate_runs(
    duration: int = None,
    record: bool = False,
    transmissions: list = [0.01, 0.02, 0.03],
    use_daq: bool = True,
    **kwargs
) -> None:
    """
    Runs through attenuator conditions and records each as an individual run

    Parameters
    ----------
    duration: int, optional
        When using the DAQ this corresponds to the number of events. If not
        using the DAQ, it corresponds to the number of seconds to wait at ech
        attenuator step. Default is 240 events (with DAQ), or 3 seconds (no DAQ).

    record: bool, optional
        set True to record

    transmissions: list of floats, optional
        list of transmissions to run through. default [0.01,0.02,0.03]

    use_daq: bool, optional
        Whether to include the DAQ or not. Default: True. If False can run the
        scans while using the DAQ elsewhere.

    **kwargs - Additional optional keyword arguments
        events: int
            Provided for backwards compatibility. When using the DAQ, if this
            keyword argument is passed, and `duration` is not, it will be used
            as the number of events.

    Operations
    ----------

    """
    from time import sleep
    from mfx.db import att, pp

    if use_daq:
        from mfx.db import daq

    evts = kwargs.get("events")
    if duration is None:
        if use_daq:
            duration = evts if evts else 240
        else:
            duration = 3
            if evts is not None:
                print("`events` parameter ignored when not using DAQ! Use `duration`!")

    pp.open()
    for i in transmissions:
        att(i)
        if use_daq:
            sleep(3)
            daq.begin(events=duration, record=record, wait=True, use_l3t=False)
            daq.end_run()
        else:
            sleep(duration)
    pp.close()
    if use_daq:
        daq.disconnect()


def attenuator_scan_single_run(
    duration: int = None,
    record: bool = False,
    transmissions: list = [0.01, 0.02, 0.03],
    use_daq: bool = True,
    **kwargs
) -> None:
    """
    Runs through attenuator conditions and records them all as one continuous run

    Parameters
    ----------
    duration: int, optional
        When using the DAQ this corresponds to the number of events. If not
        using the DAQ, it corresponds to the number of seconds to wait at ech
        attenuator step. Default is 240 events (with DAQ), or 3 seconds (no DAQ).

    record: bool, optional
        set True to record

    transmissions: list of floats, optional
        list of transmissions to run through. default [0.01,0.02,0.03]

    use_daq: bool, optional
        Whether to include the DAQ or not. Default: True. If False can run the
        scans while using the DAQ elsewhere.

    **kwargs - Additional optional keyword arguments
        events: int
            Provided for backwards compatibility. When using the DAQ, if this
            keyword argument is passed, and `duration` is not, it will be used
            as the number of events. It is ignored when not using the DAQ.

    Operations
    ----------

    """
    from time import sleep
    from mfx.db import att, pp

    if use_daq:
        from mfx.db import daq

        daq.end_run()
        daq.disconnect()

    evts = kwargs.get("events")
    if duration is None:
        if use_daq:
            duration = evts if evts else 240
        else:
            duration = 3
            if evts is not None:
                print("`events` parameter ignored when not using DAQ! Use `duration`!")

    try:
        pp.open()
        if use_daq:
            daq.configure(record=record)
            sleep(3)
        for i in transmissions:
            att(i, wait=True)
            if use_daq:
                sleep(3)
                daq.begin(events=duration, record=record, wait=True, use_l3t=False)
            else:
                sleep(duration)
    finally:
        if use_daq:
            daq.end_run()
            daq.disconnect()
        pp.close()
