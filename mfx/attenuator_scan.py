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
    sample: str ='?',
    tag: str =None,
    duration: int = None,
    record: bool = False,
    transmissions: list = [0.01, 0.02, 0.03],
    use_daq: bool = True,
    runs: int = 1, 
    inspire: bool =False, 
    daq_delay: int = 5, 
    picker: str =None,
    daq_num: int =2):
    """
    Runs through attenuator conditions and records them all as one continuous run

    Parameters
    ----------
    sample: str, optional
        Sample Name

    tag: str, optional
        Run group tag

    duration: int, optional
        Number of seconds to record at each transmission.
        Default is 10 seconds.

    record: bool, optional
        set True to record

    transmissions: list of floats, optional
        list of transmissions to run through. default [0.01,0.02,0.03]

    use_daq: bool, optional
        Whether to include the DAQ or not. Default: True. If False can run the
        scans while using the DAQ elsewhere.

    runs: int, optional
        number of runs 5 is default

    inspire: bool, optional
        Set false by default because it makes Sandra sad. Set True to inspire

    daq_delay: int, optional
        delay time between runs. Default is 5 second but increase is the DAQ is being slow.

    picker: str, optional
        If 'open' it opens pp before run starts. If 'flip' it flipflops before run starts

    daq_num: int, optional
        Switch between daq 1 and 2. Default 2

    Operations
    ----------

    """
    import logging
    from time import sleep
    from mfx.db import att, pp
    from mfx.autorun import quote, post
    from mfx.macros import get_run

    logger = logging.getLogger(__name__)

    if use_daq:
        from mfx.db import daq

    if sample.lower()=='water' or sample.lower()=='h2o':
        inspire=True

    if tag is None:
        tag = sample

    if picker=='open':
        pp.open()
    if picker=='flip':
        pp.flipflop()

    for i in range(runs):
        logger.info(f"Run Number {get_run(station=1) + 1} Running {sample}......{quote()['quote']}")
        run_number = get_run(station=1) + 1
        if use_daq:
            if daq_num == 2:
                daq.control.setState("configured")
                while daq.control.getState() != "configured":
                    ...
                if record:
                    daq.control.setRecord(True)
                else:
                    daq.control.setRecord(False)
                daq.control.setState("running")
                while daq.control.getState() != "running":
                    ...

            if daq_num == 1:
                daq1.configure(record=record)
                sleep(3)
        for i in transmissions:
            att(i, wait=True)
            if use_daq and daq_num == 1:
                    sleep(3)
                    daq1.begin(duration=duration, record=record, wait=True, use_l3t=False)
            else:
                sleep(duration)

    if use_daq:
        if daq_num == 2:
            daq.control.setState("configured")
            while daq.control.getState() != "configured":
                ...
            daq.control.setRecord(False)
            daq.control.setState("running")
        if daq_num == 1:
            daq1.end_run()
            daq1.disconnect()

        if record:
            sample_transmission=f"{sample} \n transmissions: {transmissions}"
            post(
                sample=sample, 
                tag=tag, 
                run_number=run_number, 
                post=record, 
                inspire=inspire,
                daq_num=daq_num)
        pp.close()
