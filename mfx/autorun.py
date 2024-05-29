def post(sample='?', run_number=None, post=False, inspire=False, add_note=''):
    """
    Posts a message to the elog

    Parameters
    ----------
    sample: str, optional
        Sample Name

    run_number: int, optional
        Run Number. By default this is read off of the DAQ

    post: bool, optional
        set True to record/post message to elog

    inspire: bool, optional
        Set false by default because it makes Sandra sad. Set True to inspire

    add_note: string, optional
        adds additional note to elog message 
    """
    from mfx.db import daq, elog
    if add_note!='':
        add_note = '\n' + add_note
    if inspire:
        comment = f"Running {sample}\n{quote()['quote']}{add_note}"
    else:
        comment = f"Running {sample}{add_note}"
    if run_number is None:
        run_number = daq.run_number()
    info = [run_number, comment]
    post_msg = post_template.format(*info)
    print('\n' + post_msg + '\n')
    if post:
        elog.post(msg=post_msg, run=(run_number))
    return post_msg


def begin(events=None, duration=300,
          record=False, use_l3t=None, controls=None,
          wait=False, end_run=False):
    """
    Start the daq and block until the daq has begun acquiring data.

    Optionally block with ``wait=True`` until the daq has finished aquiring
    data. If blocking, a ``ctrl+c`` will end the run and clean up.

    If omitted, any argument that is shared with `configure`
    will fall back to the configured value.

    Internally, this calls `kickoff` and manages its ``Status`` object.

    Parameters
    ----------
    events: ``int``, optional
        Number events to take in the daq.

    duration: ``int``, optional
        Time to run the daq in seconds, if ``events`` was not provided.

    record: ``bool``, optional
        If ``True``, we'll configure the daq to record data before this
        run.

    use_l3t: ``bool``, optional
        If ``True``, we'll run with the level 3 trigger. This means that
        if we specified a number of events, we will wait for that many
        "good" events as determined by the daq.

    controls: ``dict{name: device}`` or ``list[device...]``, optional
        If provided, values from these will make it into the DAQ data
        stream as variables. We will check ``device.position`` and
        ``device.value`` for quantities to use and we will update these
        values each time begin is called. To provide a list, all devices
        must have a ``name`` attribute.

    wait: ``bool``, optional
        If ``True``, wait for the daq to finish aquiring data. A
        ``KeyboardInterrupt`` (``ctrl+c``) during this wait will end the
        run and clean up.

    end_run: ``bool``, optional
        If ``True``, we'll end the run after the daq has stopped.
    """
    import logging
    from time import sleep
    from mfx.db import daq
    logger = logging.getLogger(__name__)

    logger.debug(('Daq.begin(events=%s, duration=%s, record=%s, '
                    'use_l3t=%s, controls=%s, wait=%s)'),
                    events, duration, record, use_l3t, controls, wait)
    status = True
    try:
        if record is not None and record != daq.record:
            old_record = daq.record
            daq.preconfig(record=record, show_queued_cfg=False)
        begin_status = daq.kickoff(events=events, duration=duration,
                                    use_l3t=use_l3t, controls=controls)
        try:
            begin_status.wait(timeout=daq._begin_timeout)
        except (StatusTimeoutError, WaitTimeoutError):
            msg = (f'Timeout after {daq._begin_timeout} seconds waiting '
                    'for daq to begin.')
            raise DaqTimeoutError(msg) from None

        # In some daq configurations the begin status returns very early,
        # so we allow the user to configure an emperically derived extra
        # sleep.
        sleep(daq.config['begin_sleep'])
        if wait:
            daq.wait()
            if end_run:
                daq.end_run()
        if end_run and not wait:
            threading.Thread(target=daq._ender_thread, args=()).start()
        return status
    except KeyboardInterrupt:
            status = False
            return status
        

def quote():
    import json,random
    from os import path
    _path = path.dirname(__file__)
    _path = path.join(_path,"/cds/home/d/djr/scripts/quotes.json")
    _quotes = json.loads(open(_path, 'rb').read())
    _quote = _quotes[random.randint(0,len(_quotes)-1)]
    _res = {'quote':_quote['text'],"author":_quote['from']}
    return _res


def autorun(sample='?', run_length=300, record=True, runs=5, inspire=False, delay=5, picker=None):
    """
    Automate runs.... With optional quotes

    Parameters
    ----------
    sample: str, optional
        Sample Name

    run_length: int, optional
        number of seconds for run 300 is default

    record: bool, optional
        set True to record

    runs: int, optional
        number of runs 5 is default

    inspire: bool, optional
        Set false by default because it makes Sandra sad. Set True to inspire

    delay: int, optional
        delay time between runs. Default is 5 second but increase is the DAQ is being slow.

    picker: str, optional
        If 'open' it opens pp before run starts. If 'flip' it flipflops before run starts

    Operations
    ----------

    """
    import logging
    from time import sleep
    from mfx.db import daq, pp
    logger = logging.getLogger(__name__)

    if sample.lower()=='water' or sample.lower()=='h2o':
        inspire=True
    if picker=='open':
        pp.open()
    if picker=='flip':
        pp.flipflop()

    for i in range(runs):
        logger.info(f"Run Number {daq.run_number() + 1} Running {sample}......{quote()['quote']}")
        run_number = daq.run_number() + 1
        status = begin(duration = run_length, record = record, wait = True, end_run = True)
        if status is False:
            pp.close()
            post(sample, run_number, record, inspire, 'Run ended prematurely. Probably sample delivery problem')
            logger.warning("[*] Stopping Run and exiting???...")
            sleep(5)
            daq.stop()
            daq.disconnect()
            logger.warning('Run ended prematurely. Probably sample delivery problem')
            break

        post(sample, run_number, record, inspire)
        try:
            sleep(daq_delay)
        except KeyboardInterrupt:
            pp.close()
            logger.warning("[*] Stopping Run and exiting???...")
            sleep(5)
            daq.disconnect()
            status = False
            if status is False:
                logger.warning('Run ended prematurely. Probably sample delivery problem')
                break
    if status:
        pp.close()
        daq.end_run()
        daq.disconnect()
        logger.warning('Finished with all runs thank you for choosing the MFX beamline!\n')


post_template = """\
Run Number {}: {}
"""