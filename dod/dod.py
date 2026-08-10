import logging
import time

from http.client import RemoteDisconnected
from dod.DropsDriver import myClient
from dod.JsonFileHandler import JsonFileHandler


def _with_reconnect(func):
    """
    Decorator that catches stale-connection errors and retries once after
    reconnecting.

    Handles ``RemoteDisconnected`` and ``ConnectionResetError``, both of which
    arise when the robot's HTTP server closes the TCP session between calls.
    A short sleep is inserted before the retry to allow the robot server time
    to become ready for a new connection. The decorated method is retried
    exactly once; if the retry also fails the exception propagates to the
    caller.
    """

    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except (RemoteDisconnected, ConnectionResetError, BrokenPipeError):
            time.sleep(1)
            self.reconnect()
            return func(self, *args, **kwargs)

    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


# ---------------------------------------------------------------------------
# Dry-run stubs — used when DoD(dryrun=True) is instantiated off-hutch.
# ---------------------------------------------------------------------------


class _MockServerResponse:
    """Minimal server-response stub for dry-run mode."""

    STATUS = "DRY_RUN"
    RESULTS = {
        "PositionReal": [0.0, 0.0, 0.0],
        "PositionName": "DRY_RUN",
        "Status": "DRY_RUN",
        "TaskNames": [],
        "PositionNames": [],
    }


class _MockClient:
    """
    No-op robot HTTP client for dry-run mode.

    Any method call returns a ``_MockServerResponse``.  A catch-all
    ``__getattr__`` means the mock is forward-compatible with new
    ``myClient`` methods without needing maintenance.
    """

    def __getattr__(self, name):
        def _noop(*args, **kw):
            return _MockServerResponse()

        return _noop


class _MockDelay:
    """No-op EVR channel-access delay attribute."""

    def get(self):
        return 0.0

    def put(self, value):
        pass


class _MockTrigger:
    """No-op EVR trigger for dry-run mode."""

    def __init__(self, pv="mock", name="mock"):
        self.ns_delay = _MockDelay()


# ---------------------------------------------------------------------------
# Module-level constant
# ---------------------------------------------------------------------------

# Period of the 120 Hz beam in nanoseconds; used in timing calculations.
_PERIOD_120HZ_NS = 1e9 / 120


class DoD:
    """
    Class definition of the DoD (Drop-on-Demand) robot.

    Provides an interface for controlling the DoD robot at MFX, including
    motion control, nozzle dispensing, safety region enforcement, and
    EVR timing management.

    Parameters
    ----------
    modules : str or None, optional
        Defines optional modules of the robot. Options: ``None``, ``'codi'``.
        Default is ``None``.
    ip : str, optional
        IP address of the robot server. Default is ``'172.21.39.172'``.
    port : int, optional
        Port of the robot server. Default is ``9999``.
    supported_json : str, optional
        Path to the supported endpoints JSON file. Default is
        ``'/cds/group/pcds/pyps/apps/hutch-python/mfx/dod/supported.json'``.
    log_file : str, optional
        Path to the log file for ``dod.DropsDriver`` and ``dod.HTTPTransceiver``
        INFO messages. Default is
        ``'/cds/group/pcds/pyps/apps/hutch-python/mfx/dod/dod.log'``.

    Attributes
    ----------
    client : myClient
        TCP client used for communication with the robot.
    ip : str
        IP address of the robot server.
    port : int
        Port of the robot server.
    supported_json : str
        Path to the supported endpoints JSON file.
    safety_abort : bool
        Flag used to abort task execution mid-run. Set to ``True`` to trigger
        an abort on the next polling cycle.
    y_min : int
        Minimum allowed y-position (hutch coordinates, micrometers).
    y_safety : int
        y-position above which only vertical robot configuration is allowed.
    y_max : int
        Maximum allowed y-position (hutch coordinates, micrometers).
    forbidden_regions_horizontal : list of tuple
        List of forbidden rectangular regions (x_start, x_stop, y_start, y_stop)
        active when the robot is in horizontal rotation state.
    forbidden_regions_vertical : list of tuple
        List of forbidden rectangular regions active when the robot is in
        vertical rotation state.
    trigger_Xray : Trigger
        EVR trigger object for the X-ray simulator.
    trigger_nozzle_1 : Trigger
        EVR trigger object for nozzle 1.
    trigger_nozzle_2 : Trigger
        EVR trigger object for nozzle 2.
    trigger_LED : Trigger
        EVR trigger object for the LED array.
    timing_Xray : float
        Absolute X-ray trigger delay in nanoseconds.
    timing_nozzle_1 : float
        Absolute nozzle 1 trigger delay in nanoseconds.
    timing_nozzle_2 : float
        Absolute nozzle 2 trigger delay in nanoseconds.
    timing_LED : float
        Absolute LED trigger delay in nanoseconds.
    timing_delay_sciPulse : float
        Fixed science pulse delay offset in nanoseconds.
    timing_delay_LED : float
        Relative delay of the LED with respect to X-ray timing in nanoseconds.
    timing_delay_reaction : float
        Relative reaction delay with respect to X-ray timing in nanoseconds.
    timing_delay_nozzle_1 : float
        Relative delay of nozzle 1 with respect to X-ray timing in nanoseconds.
    timing_delay_nozzle_2 : float
        Relative delay of nozzle 2 with respect to X-ray timing in nanoseconds.
    codi : CoDI, optional
        CoDI module object. Only present if ``modules='codi'``.

    Examples
    --------
    Instantiate the robot with default settings:

    >>> dod = DoD()

    Instantiate with the CoDI module enabled:

    >>> dod = DoD(modules='codi')

    Instantiate with a custom IP address:

    >>> dod = DoD(ip='172.21.72.187', port=9999)
    """

    def __init__(
        self,
        modules=None,
        ip="172.21.39.172",
        port=9999,
        supported_json="/cds/group/pcds/pyps/apps/hutch-python/mfx/dod/supported.json",
        log_file="/cds/group/pcds/pyps/apps/hutch-python/mfx/dod/dod.log",
        dryrun=False,
    ):
        self._dryrun = bool(dryrun)

        # User input parameters:
        # Safety parameters in hutch coordinate system.
        # Note: hutch (x,y,z) = robot (x,-z, y)
        #
        self.y_min = 10000  # minimum value in y.
        self.y_safety = 50000  # value in y, above which the robot can only be in vertical configuration
        self.y_max = 50000  # maximum value in y

        # Initialize safety regions for horizontal and vertical rotation:
        self.forbidden_regions_horizontal = []
        self.forbidden_regions_vertical = []
        # minimum region:
        self.set_forbidden_region(0, 300000, 0, self.y_min, rotation_state="both")
        # maximum region:
        self.set_forbidden_region(0, 300000, self.y_max, 500000, rotation_state="both")
        # region where horizontal rotation is forbidden:
        self.set_forbidden_region(
            0, 300000, self.y_safety, self.y_max, rotation_state="horizontal"
        )

        if dryrun:
            # Case A: off-hutch dry-run — mock all hardware connections
            self.client = _MockClient()
        else:
            # Redirect dod.DropsDriver and dod.HTTPTransceiver log output to a
            # file so INFO messages do not appear on the console.
            # propagate=False prevents the records from also reaching the root
            # (console) handler.
            _dod_log_fmt = logging.Formatter(
                "%(asctime)s  %(name)s  %(levelname)s  %(message)s"
            )
            for _log_name in ("dod.DropsDriver", "dod.HTTPTransceiver"):
                _lgr = logging.getLogger(_log_name)
                # Idempotency guard: avoid adding a duplicate FileHandler if
                # DoD() is instantiated more than once in the same session.
                if not any(isinstance(h, logging.FileHandler) for h in _lgr.handlers):
                    _fh = logging.FileHandler(log_file)
                    _fh.setFormatter(_dod_log_fmt)
                    _lgr.addHandler(_fh)
                _lgr.propagate = False

            # Initializing the robot client for communication
            self.client = myClient(
                ip=ip, port=port, supported_json=supported_json, reload=False
            )

            # create config parser handler
            json_handler = JsonFileHandler(supported_json)
            # load configs and launch web server
            json_handler.reload_endpoints()

        # Set parameters for reconnecting function
        self.ip = ip
        self.port = port
        self.supported_json = supported_json

        # Flag that can be used later on for safety aborts during task execution
        self.safety_abort = False
        if modules == "codi":
            from dod.codi import CoDI

            self.codi = CoDI(dryrun=self._dryrun)

        # Timing section — EVR trigger objects
        if dryrun:
            self.trigger_Xray = _MockTrigger(
                "MFX:LAS:EVR:01:TRIG7", name="trigger_X-ray_simulator"
            )
            self.trigger_nozzle_1 = _MockTrigger(
                "MFX:LAS:EVR:01:TRIG2", name="trigger_nozzle_1"
            )
            self.trigger_nozzle_2 = _MockTrigger(
                "MFX:LAS:EVR:01:TRIG3", name="trigger_nozzle_2"
            )
            self.trigger_LED = _MockTrigger(
                "MFX:LAS:EVR:01:TRIG1", name="trigger_LED_array"
            )
        else:
            from pcdsdevices.evr import Trigger

            self.trigger_Xray = Trigger(
                "MFX:LAS:EVR:01:TRIG7", name="trigger_X-ray_simulator"
            )
            self.trigger_nozzle_1 = Trigger(
                "MFX:LAS:EVR:01:TRIG2", name="trigger_nozzle_1"
            )
            self.trigger_nozzle_2 = Trigger(
                "MFX:LAS:EVR:01:TRIG3", name="trigger_nozzle_2"
            )
            self.trigger_LED = Trigger("MFX:LAS:EVR:01:TRIG1", name="trigger_LED_array")

        # Timing parameters — seeded from PVs on live hardware; 0.0 in dry-run
        self.timing_Xray = self.trigger_Xray.ns_delay.get()
        self.timing_nozzle_1 = self.trigger_nozzle_1.ns_delay.get()
        self.timing_nozzle_2 = self.trigger_nozzle_2.ns_delay.get()
        self.timing_LED = self.trigger_LED.ns_delay.get()
        self.timing_delay_sciPulse = 60600
        self.timing_delay_LED = 1000  # delay of LED relative to X-ray timing
        self.timing_delay_reaction = 0
        self.timing_delay_nozzle_1 = (
            self.timing_Xray
            - self.timing_nozzle_1
            - self.timing_delay_sciPulse
            - self.timing_delay_reaction
        )
        self.timing_delay_nozzle_2 = (
            self.timing_Xray
            - self.timing_nozzle_2
            - self.timing_delay_sciPulse
            - self.timing_delay_reaction
        )

    @property
    def dryrun(self):
        """bool: When ``True``, all hardware/network/file writes are suppressed."""
        return self._dryrun

    @dryrun.setter
    def dryrun(self, value):
        self._dryrun = bool(value)
        if hasattr(self, "codi"):
            self.codi.dryrun = self._dryrun

    @_with_reconnect
    def stop_task(self, verbose=True):
        """
        Stop a currently running robot task.

        Sends a stop command to the robot and resets the ``safety_abort`` flag.

        .. note::
            After calling this method the robot may remain in ``"BUSY"`` status.
            Call :meth:`clear_abort` to recover.

        Parameters
        ----------
        verbose : bool, optional
            If ``True``, return the full server response. Default is ``True``.

        Returns
        -------
        ServerResponse or None
            Full server response if ``verbose=True``, otherwise ``None``.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Stop a running task and inspect the response:

        >>> r = dod.stop_task(verbose=True)

        Stop a task without capturing the response:

        >>> dod.stop_task(verbose=False)
        """
        r = self.client.connect("Test")
        self.safety_abort = False
        r = self.client.stop_task()
        r = self.client.disconnect()
        if verbose:
            return r

    @_with_reconnect
    def clear_abort(self, verbose=True):
        """
        Clear the robot abort flag and refresh status.

        Reconnects to the robot, reads the current status, and resets the
        ``safety_abort`` flag.

        Parameters
        ----------
        verbose : bool, optional
            If ``True``, return the full server response. Default is ``True``.

        Returns
        -------
        ServerResponse or None
            Full server response if ``verbose=True``, otherwise ``None``.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Clear an abort and print the resulting status:

        >>> r = dod.clear_abort(verbose=True)
        >>> print(r)

        Clear an abort silently:

        >>> dod.clear_abort(verbose=False)
        """
        r = self.client.connect("Test")
        r = self.client.get_status()
        self.safety_abort = False
        rr = self.client.disconnect()

        if verbose:
            return r

    def reconnect(self, reload=False, verbose=False):
        """
        Attempt to reconnect to the robot after a timeout or connection loss.

        Re-instantiates the client and reloads the endpoint configuration.

        Parameters
        ----------
        reload : bool, optional
            If ``True``, reload the JSON endpoint configuration. Default is ``False``.
        verbose : bool, optional
            Reserved for future use; currently has no effect. Default is ``False``.

        Returns
        -------
        bool
            Always returns ``False``.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached at the stored IP and port.
        FileNotFoundError
            If the supported JSON file cannot be found.

        Examples
        --------
        Reconnect after a timeout:

        >>> dod.reconnect()

        Reconnect and reload the endpoint configuration:

        >>> dod.reconnect(reload=True)
        """
        # Initializing the robot client that is used for communication
        self.client = myClient(
            ip=self.ip,
            port=self.port,
            supported_json=self.supported_json,
            reload=reload,
        )
        # create config parser handler
        json_handler = JsonFileHandler(self.supported_json)
        # load configs and launch web server
        json_handler.reload_endpoints()

        return False

    @_with_reconnect
    def get_status(self, verbose=False):
        """
        Return the current robot state.

        Parameters
        ----------
        verbose : bool, optional
            If ``True``, return the full server response object. If ``False``,
            return only the results dict. Default is ``False``.

        Returns
        -------
        dict or ServerResponse
            If ``verbose=False``, returns a dict with robot state keys such as
            ``'Position'``, ``'RunningTask'``, ``'Dialog'``, ``'LastProbe'``,
            ``'Humidity'``, ``'Temperature'``, and ``'BathTemp'``.
            If ``verbose=True``, returns the full ``ServerResponse`` object.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Get a summary status dict:

        >>> status = dod.get_status()
        >>> print(status['Position'])

        Get the full response object:

        >>> r = dod.get_status(verbose=True)
        """
        rr = self.client.connect("Test")
        r = self.client.get_status()
        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    @_with_reconnect
    def busy_wait(self, timeout, poll_interval=2.0):
        """
        Block until the robot is no longer busy or the timeout is reached.

        Polls the robot status at ``poll_interval`` second intervals. Prints a
        message on each polling iteration so the caller can see the robot is
        still active. Returns immediately if the robot is not busy.

        Parameters
        ----------
        timeout : float
            Maximum time to wait in seconds before returning.
        poll_interval : float, optional
            Time in seconds between status polls. Default is ``2.0`` s.
            Increase this for long-running operations (e.g. probe uptake) to
            reduce HTTP traffic to the robot server.

        Returns
        -------
        bool
            ``True`` if the timeout was reached before the robot became idle,
            ``False`` if the robot became idle within the timeout.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached during polling.

        Examples
        --------
        Wait up to 30 seconds for the robot to finish a move:

        >>> timed_out = dod.busy_wait(30)
        >>> if timed_out:
        ...     print('Robot did not finish in time.')

        Wait for a long-running task, polling every 10 s:

        >>> timed_out = dod.busy_wait(120, poll_interval=10)
        """
        start = time.time()
        r = self.client.get_status()
        delta = 0

        while r.STATUS["Status"] == "Busy":
            if delta > timeout:
                return True

            print(f"[DoD] Robot busy — checking again in {poll_interval} s ...")
            time.sleep(poll_interval)
            r = self.client.get_status()
            delta = time.time() - start
        return False

    @_with_reconnect
    def get_task_details(self, task_name, verbose=False):
        """
        Retrieve the details of a named task from the robot.

        Parameters
        ----------
        task_name : str
            Name of the task to retrieve.
        verbose : bool, optional
            If ``True``, return the full server response object. If ``False``,
            return only the results dict. Default is ``False``.

        Returns
        -------
        dict or ServerResponse
            Task detail data. If ``verbose=False``, returns ``r.RESULTS``.
            If ``verbose=True``, returns the full ``ServerResponse`` object.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.
        KeyError
            If ``task_name`` does not exist on the robot.

        Examples
        --------
        Print the details of a task named ``'move_to_home'``:

        >>> details = dod.get_task_details('move_to_home')
        >>> print(details)
        """
        rr = self.client.connect("Test")
        r = self.client.get_task_details(task_name)
        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    @_with_reconnect
    def get_task_names(self, verbose=False):
        """
        Retrieve the names of all available tasks from the robot.

        Parameters
        ----------
        verbose : bool, optional
            If ``True``, return the full server response object. If ``False``,
            return only the results dict. Default is ``False``.

        Returns
        -------
        dict or ServerResponse
            Available task names. If ``verbose=False``, returns ``r.RESULTS``.
            If ``verbose=True``, returns the full ``ServerResponse`` object.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        List all available task names:

        >>> tasks = dod.get_task_names()
        >>> print(tasks)
        """
        rr = self.client.connect("Test")
        r = self.client.get_task_names()
        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    @_with_reconnect
    def get_position_names(self, verbose=False):
        """
        Retrieve the names of all available positions from the robot.

        Parameters
        ----------
        verbose : bool, optional
            If ``True``, return the full server response object.  If ``False``
            (default), return only the results dict.

        Returns
        -------
        list or ServerResponse
            Available position names.  If ``verbose=False``, returns
            ``r.RESULTS`` (expected to be a list of position name strings).
            If ``verbose=True``, returns the full ``ServerResponse`` object.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        List all available position names:

        >>> positions = dod.get_position_names()
        >>> print(positions)
        """
        rr = self.client.connect("Test")
        r = self.client.get_position_names()
        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    @_with_reconnect
    def get_current_position(self, verbose=False):
        """
        Return the current robot position.

        Returns the name and properties of the last selected position, together
        with the real current position coordinates.

        Parameters
        ----------
        verbose : bool, optional
            If ``True``, return the full server response object. If ``False``,
            return only the results dict. Default is ``False``.

        Returns
        -------
        dict or ServerResponse
            Position data with keys ``'CurrentPosition'``, ``'Position'``, and
            ``'PositionReal'``. If ``verbose=False``, returns ``r.RESULTS``.
            If ``verbose=True``, returns the full ``ServerResponse`` object.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Get the current position and print the real coordinates:

        >>> pos = dod.get_current_position()
        >>> print(pos['PositionReal'])
        """
        rr = self.client.connect("Test")
        r = self.client.get_current_positions()
        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    @_with_reconnect
    def get_nozzle_status(self, verbose=False):
        """
        Return the current nozzle parameters and state.

        Parameters
        ----------
        verbose : bool, optional
            If ``True``, return the full server response object. If ``False``,
            return only the results dict. Default is ``False``.

        Returns
        -------
        dict or ServerResponse
            Nozzle status data with keys ``'Activated Nozzles'``,
            ``'Selected Nozzles'``, ``'ID,Volt,Pulse,Freq,Volume'``, and
            ``'Dispensing'``. If ``verbose=False``, returns ``r.RESULTS``.
            If ``verbose=True``, returns the full ``ServerResponse`` object.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Print the dispensing state of all nozzles:

        >>> status = dod.get_nozzle_status()
        >>> print(status['Dispensing'])
        """
        rr = self.client.connect("Test")
        r = self.client.get_nozzle_status()
        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    # ------------------------------------------------------------------
    # Nozzle parameter helpers (private)
    # ------------------------------------------------------------------

    def _active_list_to_str(self, active_list):
        """
        Convert the 32-element ``'Activated Nozzles'`` boolean list to a
        comma-separated channel-number string suitable for the HTTP API.

        Parameters
        ----------
        active_list : list of bool
            32-element list as returned in
            ``get_nozzle_status()['Activated Nozzles']``.
            Index ``i`` corresponds to channel ``i + 1``.

        Returns
        -------
        str
            Comma-separated active channel numbers, e.g. ``'1,2,3'``.

        Examples
        --------
        >>> s = dod._active_list_to_str([True, True, False] + [False] * 29)
        >>> print(s)
        1,2
        """
        return ",".join(str(i + 1) for i, v in enumerate(active_list) if v)

    def _parse_nozzle_status(self, raw_status):
        """
        Parse the raw nozzle status dict into structured components.

        Converts the :meth:`get_nozzle_status` result into typed, per-nozzle
        parameter dicts ready for use in read-merge-write operations.

        Parameters
        ----------
        raw_status : dict
            Dict as returned by :meth:`get_nozzle_status`.

        Returns
        -------
        active_str : str
            Comma-separated active channel numbers, e.g. ``'1,2,3'``.
        selected_str : str
            Comma-separated selected channel numbers, e.g. ``'1'``.
        params : dict
            Mapping of channel number (int) to a parameter dict with keys:

            - ``'volt'`` (float)
            - ``'pulse'`` (str)
            - ``'freq'`` (int)
            - ``'volume'`` (float)

        Examples
        --------
        >>> raw = dod.get_nozzle_status()
        >>> active_str, selected_str, params = dod._parse_nozzle_status(raw)
        >>> print(params[1]['volt'])
        """
        active_str = self._active_list_to_str(raw_status["Activated Nozzles"])
        selected_str = ",".join(str(ch) for ch in raw_status["Selected Nozzles"])
        params = {}
        for row in raw_status["ID,Volt,Pulse,Freq,Volume"]:
            ch = int(row[0])
            params[ch] = {
                "volt": float(row[1]),
                "pulse": row[2],
                "freq": int(row[3]),
                "volume": float(row[4]),
            }
        return active_str, selected_str, params

    @_with_reconnect
    def _set_nozzle_parameters(
        self, active_str, selected_str, volt, pulse, freq, verbose=False, wait=False
    ):
        """
        Low-level wrapper for the ``SetNozzleParameters`` HTTP endpoint.

        Calls ``connect → SetNozzleParameters → disconnect`` in a single
        transaction.  All five fields are required by the robot API; callers
        are responsible for supplying current values for any field they do not
        intend to change (use :meth:`_parse_nozzle_status` to obtain them).

        .. note::
            ``Volt``, ``Pulse``, and ``Freq`` are applied to the nozzle(s)
            identified by ``selected_str``.  ``active_str`` sets the globally
            armed nozzle set.

        Parameters
        ----------
        active_str : str
            Comma-separated channel numbers of nozzles to arm, e.g. ``'1,2,3'``.
        selected_str : str
            Comma-separated channel numbers of nozzles to select, e.g. ``'2'``.
        volt : float
            Drive voltage for the selected nozzle(s).
        pulse : str
            Pulse shape name (sciPULSE channels 1–2) or numeric string (all
            other channels).
        freq : int
            Dispensing frequency in Hz for the selected nozzle(s).
        verbose : bool, optional
            If ``True``, return the full server response.  Default is ``False``.
        wait : bool, optional
            If ``True``, insert a 5 s sleep between ``SetNozzleParameters`` and
            ``disconnect``, keeping the TCP session open while the robot
            processes the command.  Use this when loading named sciPULSE
            waveforms on channels 1 or 2, which take up to 5 s to complete
            on the hardware.  Default is ``False``.

        Returns
        -------
        dict or ServerResponse
            Server response.  If ``verbose=False``, returns ``r.RESULTS``.
            If ``verbose=True``, returns the full ``ServerResponse`` object.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.
        """
        rr = self.client.connect("Test")
        # Note: myClient methods use *args only (middle_invocation_wrapper
        # does not forward **kwargs), so positional order must match
        # DropsDriver.set_nozzle_parameters: active, selected, volt, pulse, freq.
        r = self.client.set_nozzle_parameters(
            active_str,
            selected_str,
            volt,
            pulse,
            freq,
        )
        # When wait=True, block before disconnecting so the robot has time to
        # finish processing (e.g. loading a named sciPULSE waveform on ch 1/2)
        # while the TCP session is still open.
        if wait:
            time.sleep(5)
        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    # ------------------------------------------------------------------
    # Nozzle parameter public methods
    # ------------------------------------------------------------------

    def get_nozzle_parameters(self):
        """
        Return a structured per-nozzle parameter dictionary.

        Reads the current nozzle status and parses it into a dict keyed by
        channel number, with typed values for voltage, pulse shape, frequency,
        and volume.

        Returns
        -------
        dict
            Mapping of channel number (int) to a parameter dict with keys:

            - ``'volt'`` (float) — drive voltage.
            - ``'pulse'`` (str) — pulse shape name or numeric string.
            - ``'freq'`` (int) — dispensing frequency in Hz.
            - ``'volume'`` (float) — droplet volume in nL (read-only;
              not settable via ``SetNozzleParameters``).

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Print voltage for all active nozzles:

        >>> params = dod.get_nozzle_parameters()
        >>> for ch, p in params.items():
        ...     print(f'Nozzle {ch}: {p["volt"]} V, {p["pulse"]}, {p["freq"]} Hz')
        """
        raw = self.get_nozzle_status()
        _, _, params = self._parse_nozzle_status(raw)
        return params

    @_with_reconnect
    def get_pulse_names(self, verbose=False):
        """
        Return the list of available pulse shapes for the sciPULSE channels.

        Wraps ``GET /DoD/get/PulseNames``.  The exact structure of ``r.RESULTS``
        was not verified against a live robot response at the time of writing;
        the expected format is a list of pulse shape name strings (e.g.
        ``['sciPULSE_LV01', 'sciPULSE_LV02', ...]``).  Verify against a live
        robot response and update this docstring accordingly.

        Parameters
        ----------
        verbose : bool, optional
            If ``True``, return the full server response object.  If ``False``,
            return only the results.  Default is ``False``.

        Returns
        -------
        list or ServerResponse
            If ``verbose=False``, returns ``r.RESULTS`` — expected to be a list
            of pulse shape name strings for the sciPULSE channels.
            If ``verbose=True``, returns the full ``ServerResponse`` object.

            .. note::
                The exact ``RESULTS`` structure has not been verified against a
                live robot response.  Confirm the format before relying on the
                return value in application code.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Print available pulse shape names:

        >>> names = dod.get_pulse_names()
        >>> print(names)

        Inspect the full server response:

        >>> r = dod.get_pulse_names(verbose=True)
        >>> print(r.RESULTS)
        """
        rr = self.client.connect("Test")
        r = self.client.get_pulse_names()
        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    def set_nozzle_voltage(self, nozzle, volt, verbose=False):
        """
        Set the drive voltage for a specific nozzle.

        Reads the current nozzle status, merges the new voltage for the
        specified nozzle, and writes all parameters back in a single HTTP call.
        All other parameters (pulse shape, frequency, active set) are preserved.

        Parameters
        ----------
        nozzle : int
            Channel number of the nozzle to configure.
        volt : float
            Target drive voltage.
        verbose : bool, optional
            If ``True``, return the full server response.  Default is ``False``.

        Returns
        -------
        dict or ServerResponse
            Server response.  If ``verbose=False``, returns ``r.RESULTS``.
            If ``verbose=True``, returns the full ``ServerResponse`` object.

        Raises
        ------
        KeyError
            If ``nozzle`` is not currently in the active nozzle set.
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Set nozzle 2 to 60 V:

        >>> dod.set_nozzle_voltage(2, 60)

        Set nozzle 3 to 85 V and inspect the response:

        >>> r = dod.set_nozzle_voltage(3, 85, verbose=True)
        """
        raw = self.get_nozzle_status()
        active_str, _, params = self._parse_nozzle_status(raw)
        current = params[nozzle]
        return self._set_nozzle_parameters(
            active_str=active_str,
            selected_str=str(nozzle),
            volt=volt,
            pulse=current["pulse"],
            freq=current["freq"],
            verbose=verbose,
        )

    def set_nozzle_pulse(self, nozzle, pulse, verbose=False):
        """
        Set the pulse shape for a specific nozzle.

        Reads the current nozzle status, merges the new pulse shape for the
        specified nozzle, and writes all parameters back in a single HTTP call.
        All other parameters are preserved.

        .. note::
            Channels 1 and 2 accept named pulse shapes (e.g.
            ``'sciPULSE_LV01'``).  All other channels use a numeric string for
            the rectangular waveform duration (e.g. ``'48'``).  Passing the
            wrong format for a channel will be rejected by the robot.  Use
            ``dod.get_pulse_names()`` to retrieve the list of valid
            pulse shape names.

        .. note::
            For channels 1 and 2, the robot hardware takes up to 5 seconds to
            load the named waveform after acknowledging the HTTP command.  This
            method blocks for 5 s after the command is sent for those channels
            to ensure the waveform is ready before the next command is issued.

        Parameters
        ----------
        nozzle : int
            Channel number of the nozzle to configure.
        pulse : str
            Pulse shape name (channels 1–2) or numeric duration string (all
            other channels).
        verbose : bool, optional
            If ``True``, return the full server response.  Default is ``False``.

        Returns
        -------
        dict or ServerResponse
            Server response.  If ``verbose=False``, returns ``r.RESULTS``.
            If ``verbose=True``, returns the full ``ServerResponse`` object.

        Raises
        ------
        KeyError
            If ``nozzle`` is not currently in the active nozzle set.
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Set the pulse shape on nozzle 1 (sciPULSE channel; blocks ~5 s):

        >>> dod.set_nozzle_pulse(1, 'sciPULSE_LV02')

        Set the rectangular waveform duration on nozzle 3 (no wait):

        >>> dod.set_nozzle_pulse(3, '52')
        """
        raw = self.get_nozzle_status()
        active_str, _, params = self._parse_nozzle_status(raw)
        current = params[nozzle]
        # For channels 1 and 2, pass wait=True so _set_nozzle_parameters holds
        # the TCP session open for 5 s while the robot loads the sciPULSE
        # waveform before disconnecting.
        return self._set_nozzle_parameters(
            active_str=active_str,
            selected_str=str(nozzle),
            volt=current["volt"],
            pulse=pulse,
            freq=current["freq"],
            verbose=verbose,
            wait=nozzle in (1, 2),
        )

    def set_nozzle_freq(self, nozzle, freq, verbose=False):
        """
        Set the dispensing frequency for a specific nozzle.

        Reads the current nozzle status, merges the new frequency for the
        specified nozzle, and writes all parameters back in a single HTTP call.
        All other parameters are preserved.

        Parameters
        ----------
        nozzle : int
            Channel number of the nozzle to configure.
        freq : int
            Target dispensing frequency in Hz.
        verbose : bool, optional
            If ``True``, return the full server response.  Default is ``False``.

        Returns
        -------
        dict or ServerResponse
            Server response.  If ``verbose=False``, returns ``r.RESULTS``.
            If ``verbose=True``, returns the full ``ServerResponse`` object.

        Raises
        ------
        KeyError
            If ``nozzle`` is not currently in the active nozzle set.
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Set nozzle 2 to 100 Hz:

        >>> dod.set_nozzle_freq(2, 100)

        Set nozzle 1 to 60 Hz:

        >>> dod.set_nozzle_freq(1, 60)
        """
        raw = self.get_nozzle_status()
        active_str, _, params = self._parse_nozzle_status(raw)
        current = params[nozzle]
        return self._set_nozzle_parameters(
            active_str=active_str,
            selected_str=str(nozzle),
            volt=current["volt"],
            pulse=current["pulse"],
            freq=freq,
            verbose=verbose,
        )

    def set_nozzle_active(self, active_list, verbose=False):
        """
        Set which nozzles are armed (activated).

        Reads the current nozzle status, replaces the active nozzle set with
        ``active_list``, and writes back with the currently selected nozzle's
        parameters preserved via a read-merge-write.

        .. note::
            ``Volt``, ``Pulse``, and ``Freq`` in the HTTP call apply to the
            currently **selected** nozzle (unchanged by this method).  If a
            newly activated nozzle requires specific parameters, call
            :meth:`set_nozzle_voltage`, :meth:`set_nozzle_pulse`, or
            :meth:`set_nozzle_freq` after this method.

        Parameters
        ----------
        active_list : list of int
            Channel numbers to arm, e.g. ``[1, 2, 3]``.
        verbose : bool, optional
            If ``True``, return the full server response.  Default is ``False``.

        Returns
        -------
        dict or ServerResponse
            Server response.  If ``verbose=False``, returns ``r.RESULTS``.
            If ``verbose=True``, returns the full ``ServerResponse`` object.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Arm nozzles 1, 2, and 3:

        >>> dod.set_nozzle_active([1, 2, 3])

        Arm only nozzle 1:

        >>> dod.set_nozzle_active([1])
        """
        raw = self.get_nozzle_status()
        previous_mode = raw.get("Dispensing", "Off")
        _, selected_str, params = self._parse_nozzle_status(raw)
        new_active_str = ",".join(str(ch) for ch in sorted(active_list))

        # Use the currently selected nozzle's params for Volt/Pulse/Freq.
        # Falls back to the first active nozzle if selected is unavailable,
        # or to safe defaults if no nozzles are currently active.
        selected_ch = int(selected_str.split(",")[0]) if selected_str else None
        if selected_ch is not None and selected_ch in params:
            current = params[selected_ch]
        elif params:
            current = next(iter(params.values()))
        else:
            current = {"volt": 0, "pulse": "0", "freq": 120}

        # Changing the armed nozzle set while dispensing is active leaves the
        # robot in an undefined state; turn off first and restore afterwards.
        if previous_mode != "Off":
            self.set_nozzle_dispensing("Off")

        r = self._set_nozzle_parameters(
            active_str=new_active_str,
            selected_str=selected_str,
            volt=current["volt"],
            pulse=current["pulse"],
            freq=current["freq"],
            verbose=verbose,
        )

        if previous_mode != "Off":
            self.set_nozzle_dispensing(previous_mode)

        return r

    def set_nozzle_selected(self, nozzles, param_nozzle=None, verbose=False):
        """
        Select one or more nozzles for dispensing and task execution.

        For a single nozzle, sends a ``SelectNozzle`` command (fast path).
        For multiple nozzles, routes through ``SetNozzleParameters`` so that
        the robot's ``Selected`` field can carry a comma-separated list.  In
        the multi-nozzle case, ``Volt``, ``Pulse``, and ``Freq`` are taken from
        a single reference channel (``param_nozzle``) because
        ``SetNozzleParameters`` applies those fields to one channel at a time.

        .. note::
            All supplied channels must be in the currently activated (armed)
            set.  Use :meth:`get_nozzle_status` to check ``'Activated Nozzles'``
            or :meth:`set_nozzle_active` to arm additional channels first.

        .. note::
            ``SelectNozzle`` and ``SetNozzleParameters`` interact — each
            overwrites the other's ``Selected`` value.  If you call
            :meth:`set_nozzle_voltage` (or any other parameter setter) after
            this method, the selected nozzle will be updated to the one passed
            to that setter.

        Parameters
        ----------
        nozzles : int or list of int
            Channel number(s) to select, e.g. ``2`` or ``[1, 2, 3]``.
        param_nozzle : int or None, optional
            The single channel whose current ``Volt``/``Pulse``/``Freq`` values
            are used in the ``SetNozzleParameters`` call (multi-nozzle path
            only).  If ``None`` (default), the first channel in ``nozzles`` is
            used.  Must be in the armed set.  Ignored when only one nozzle is
            supplied.
        verbose : bool, optional
            If ``True``, return the full server response.  Default is ``False``.

        Returns
        -------
        dict or ServerResponse
            Server response.  If ``verbose=False``, returns ``r.RESULTS``.
            If ``verbose=True``, returns the full ``ServerResponse`` object.

        Raises
        ------
        ValueError
            If any channel in ``nozzles`` (or ``param_nozzle``) is not in the
            currently activated nozzle set.
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Select a single nozzle (fast path, unchanged behaviour):

        >>> dod.set_nozzle_selected(2)

        Select nozzles 1 and 2, using nozzle 1's parameters:

        >>> dod.set_nozzle_selected([1, 2])

        Select nozzles 1 and 2, but send nozzle 2's Volt/Pulse/Freq:

        >>> dod.set_nozzle_selected([1, 2], param_nozzle=2)

        Inspect the full server response:

        >>> r = dod.set_nozzle_selected(1, verbose=True)
        """
        # Normalise to list
        if isinstance(nozzles, int):
            nozzle_list = [nozzles]
        else:
            nozzle_list = list(nozzles)

        # Read current nozzle status once
        raw = self.get_nozzle_status()
        active_str, _, params = self._parse_nozzle_status(raw)
        active_channels = [int(ch) for ch in active_str.split(",") if ch]

        # Validate all requested channels are armed
        for ch in nozzle_list:
            if ch not in active_channels:
                raise ValueError(
                    f"Nozzle {ch} is not in the active nozzle set {active_channels}. "
                    f"Use set_nozzle_active() to arm it first."
                )

        # --- Single-nozzle fast path ---
        if len(nozzle_list) == 1:
            rr = self.client.connect("Test")
            r = self.client.select_nozzle(nozzle_list[0])
            rr = self.client.disconnect()
            if verbose:
                return r
            else:
                return r.RESULTS

        # --- Multi-nozzle path via SetNozzleParameters ---
        # Resolve which channel's Volt/Pulse/Freq to use
        ref_ch = param_nozzle if param_nozzle is not None else nozzle_list[0]
        if ref_ch not in active_channels:
            raise ValueError(
                f"param_nozzle {ref_ch} is not in the active nozzle set "
                f"{active_channels}. Use set_nozzle_active() to arm it first."
            )
        current = params[ref_ch]
        selected_str = ",".join(str(ch) for ch in sorted(nozzle_list))
        return self._set_nozzle_parameters(
            active_str=active_str,
            selected_str=selected_str,
            volt=current["volt"],
            pulse=current["pulse"],
            freq=current["freq"],
            verbose=verbose,
        )

    @_with_reconnect
    def take_probe(
        self, channel, well, volume, check_task=True, timeout=None, verbose=False
    ):
        """
        Aspirate a probe sample from a well plate using the specified nozzle.

        Sends a ``TakeProbe`` command to the robot, which moves the selected
        nozzle to the named well and aspirates the requested volume.  The
        ``channel`` parameter simultaneously selects the nozzle (equivalent to
        calling :meth:`set_nozzle_selected`), so the selected nozzle after this
        call will be ``channel``.

        .. note::
            This endpoint requires the task ``'ProbeUptake'`` to be present on
            the robot.  If that task is absent the robot **silently does
            nothing** — no reject, no error message.  By default
            (``check_task=True``) this method calls :meth:`get_task_names`
            before sending and raises ``RuntimeError`` if ``'ProbeUptake'`` is
            missing, making the failure explicit.  Pass ``check_task=False`` to
            skip this pre-flight check (e.g. when performance is critical and
            the task is known to be present).

        .. note::
            The robot returns ``'Rejected'`` (visible in ``r.RESULTS``) if:
            ``channel`` is not in the active nozzle set, ``volume`` > 250 µL,
            or ``well`` is not a valid well for that nozzle's configuration.
            The first two conditions are also caught client-side before the
            command is sent.

        Parameters
        ----------
        channel : int
            Nozzle channel to use for aspiration.  Must be one of the currently
            activated (armed) channels.  This also has the side effect of
            selecting this nozzle for subsequent dispensing commands.
        well : str
            Well identifier in plate notation, e.g. ``'A1'``, ``'B3'``.  Valid
            wells depend on the nozzle configuration defined in the
            ``ProbeUptake`` task; the robot rejects invalid well strings.
        volume : float
            Aspiration volume in microlitres.  Must be ≤ 250 µL; raises
            ``ValueError`` if exceeded before the command is sent.
        check_task : bool, optional
            If ``True`` (default), call :meth:`get_task_names` before sending
            and raise ``RuntimeError`` if ``'ProbeUptake'`` is not present.
            Set to ``False`` to skip this round-trip when the task is known to
            be present.
        timeout : float or None, optional
            Maximum number of seconds to wait for the robot to finish the
            uptake move.  If ``None`` (default), the timeout is computed as
            ``max(30, int(volume))``: a 30 s floor for the physical movement
            plus 1 s per µL at the assumed syringe flow rate of 1 µL/s.
            Pass an explicit value to override.
        verbose : bool, optional
            If ``True``, return the full server response object.  If ``False``,
            return only the results dict.  Default is ``False``.

        Returns
        -------
        dict or ServerResponse
            Server response after the uptake command.  If ``verbose=False``,
            returns ``r.RESULTS`` (``'Accepted'`` or ``'Rejected'``).  If
            ``verbose=True``, returns the full ``ServerResponse`` object.

        Raises
        ------
        ValueError
            If ``volume`` > 250 µL, or if ``channel`` is not in the currently
            active nozzle set.
        RuntimeError
            If ``check_task=True`` and ``'ProbeUptake'`` is not present on the
            robot.
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Aspirate 50 µL from well A1 using nozzle 1:

        >>> dod.take_probe(1, 'A1', 50)

        Aspirate with a custom timeout (e.g. fast pump at known flow rate):

        >>> dod.take_probe(2, 'B3', 100, timeout=45)

        Skip the ProbeUptake presence check for speed:

        >>> dod.take_probe(1, 'A1', 50, check_task=False)

        Inspect the full server response:

        >>> r = dod.take_probe(1, 'A1', 50, verbose=True)
        >>> print(r.RESULTS)
        """
        # --- Client-side validation ---
        if volume > 250:
            raise ValueError(f"Volume {volume} µL exceeds the maximum of 250 µL.")

        raw = self.get_nozzle_status()
        active_str, _, _ = self._parse_nozzle_status(raw)
        active_channels = [int(ch) for ch in active_str.split(",") if ch]
        if channel not in active_channels:
            raise ValueError(
                f"Channel {channel} is not in the active nozzle set "
                f"{active_channels}. Use set_nozzle_active() to arm it first."
            )

        # --- ProbeUptake task presence check ---
        if check_task:
            task_names = self.get_task_names()
            if "ProbeUptake" not in task_names:
                raise RuntimeError(
                    "Task 'ProbeUptake' is not present on the robot. "
                    "The TakeProbe endpoint will silently do nothing without it. "
                    "Pass check_task=False to suppress this check."
                )

        # --- Compute effective timeout ---
        # Default: 30 s floor for physical movement + 1 s per µL (1 µL/s assumed
        # syringe flow rate).
        effective_timeout = timeout if timeout is not None else max(30, int(volume))

        # --- Issue command ---
        rr = self.client.connect("Test")
        r = self.client.take_probe(channel, well, volume)

        # Block until the robot finishes the uptake move.
        # Poll every 10 s — uptake operations are long-running and do not
        # benefit from rapid polling.
        self.busy_wait(effective_timeout, poll_interval=10)

        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    @_with_reconnect
    def set_nozzle_dispensing(self, mode="Off", verbose=False):
        """
        Set the nozzle dispensing mode.

        Parameters
        ----------
        mode : str, optional
            Dispensing mode to set. Options are:

            - ``'Free'`` — continuous dispensing.
            - ``'Trigger'`` — dispense on external trigger.
            - ``'Off'`` — stop dispensing on all nozzles (default).

        verbose : bool, optional
            If ``True``, return the full server response object. If ``False``,
            return only the results dict. Default is ``False``.

        Returns
        -------
        dict or ServerResponse
            Server response from the dispensing command. If ``verbose=False``,
            returns ``r.RESULTS``. If ``verbose=True``, returns the full
            ``ServerResponse`` object.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Enable triggered dispensing:

        >>> dod.set_nozzle_dispensing(mode='Trigger')

        Turn off dispensing on all nozzles:

        >>> dod.set_nozzle_dispensing(mode='Off')
        """
        rr = self.client.connect("Test")
        # Read activated nozzles so 'Off' iterates only over armed channels.
        ns = self.client.get_nozzle_status()
        active_str, _, _ = self._parse_nozzle_status(ns.RESULTS)
        active_channels = [int(ch) for ch in active_str.split(",") if ch]
        current_mode = ns.RESULTS.get("Dispensing", "Off")

        if mode in ("Free", "Trigger"):
            # Firmware requires all active-to-active mode transitions to pass
            # through Off; direct transitions are silently ignored.
            if current_mode != "Off":
                r = self.client.dispensing("Off")
                time.sleep(0.5)
                for ch in active_channels:
                    r = self.client.select_nozzle(ch)
                    time.sleep(0.5)
                    r = self.client.dispensing("Off")
                    time.sleep(0.5)
            r = self.client.dispensing(mode)
        else:
            # Turn off each activated nozzle individually to ensure all are off.
            # A short wait after each command gives the robot time to process
            # before the next command arrives.
            r = self.client.dispensing("Off")
            time.sleep(0.5)
            for ch in active_channels:
                r = self.client.select_nozzle(ch)
                time.sleep(0.5)
                r = self.client.dispensing("Off")
                time.sleep(0.5)

        self.client.disconnect()
        return self.get_nozzle_status(verbose=verbose)

    @_with_reconnect
    def set_led(self, duration, delay, verbose=False):
        """
        Set the strobe LED pulse duration and delay.

        Sends ``GET /DoD/do/SetLED?Duration={duration}&Delay={delay}`` to the
        robot server.  Both parameters are applied atomically in a single HTTP
        call.  The robot returns a reject if either value is out of the
        supported range; this method performs a client-side range check first
        and raises ``ValueError`` before sending the request.

        Parameters
        ----------
        duration : int
            Strobe pulse width in microseconds.  Must be in the range
            ``[1, 65000]``.
        delay : int
            Strobe internal delay in microseconds.  Must be in the range
            ``[0, 6500]``.
        verbose : bool, optional
            If ``True``, return the full server response object.  If ``False``
            (default), return only the results dict.

        Returns
        -------
        dict or ServerResponse
            Server response after the command.  If ``verbose=False``, returns
            ``r.RESULTS``; if ``verbose=True``, returns the full
            ``ServerResponse`` object.

        Raises
        ------
        ValueError
            If ``duration`` is not in ``[1, 65000]`` or ``delay`` is not in
            ``[0, 6500]``.
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Set duration to 500 µs and delay to 100 µs:

        >>> dod.set_led(500, 100)

        Set duration to 1000 µs with no delay, inspect the full response:

        >>> r = dod.set_led(1000, 0, verbose=True)
        >>> print(r.RESULTS)
        """
        if not (1 <= duration <= 65000):
            raise ValueError(f"duration must be in [1, 65000]; got {duration!r}.")
        if not (0 <= delay <= 6500):
            raise ValueError(f"delay must be in [0, 6500]; got {delay!r}.")
        rr = self.client.connect("Test")
        r = self.client.setLED(duration, delay)
        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    @_with_reconnect
    def set_led_per_nozzle(self, nozzle, duration, delay, verbose=False):
        """
        Set the strobe LED pulse duration and delay for a specific nozzle.

        Selects the specified nozzle via ``SelectNozzle``, waits 0.5 s, then
        calls ``SetLED`` to apply the strobe parameters.  All three operations
        are performed within a single ``connect``–``disconnect`` transaction.

        The nozzle must be in the active (armed) set; this method raises
        ``ValueError`` if it is not, consistent with :meth:`set_nozzle_selected`.

        Parameters
        ----------
        nozzle : int
            Channel number of the nozzle to configure.  Must be in the
            currently active (armed) nozzle set.
        duration : int
            Strobe pulse width in microseconds.  Must be in the range
            ``[1, 65000]``.
        delay : int
            Strobe internal delay in microseconds.  Must be in the range
            ``[0, 6500]``.
        verbose : bool, optional
            If ``True``, return the full server response object from the
            ``SetLED`` call.  If ``False`` (default), return only the results
            dict.

        Returns
        -------
        dict or ServerResponse
            Server response from the ``SetLED`` call.  If ``verbose=False``,
            returns ``r.RESULTS``; if ``verbose=True``, returns the full
            ``ServerResponse`` object.

        Raises
        ------
        ValueError
            If ``nozzle`` is not in the active nozzle set, or if ``duration``
            is not in ``[1, 65000]``, or if ``delay`` is not in ``[0, 6500]``.
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Set nozzle 1 strobe to 300 µs duration, 50 µs delay:

        >>> dod.set_led_per_nozzle(1, 300, 50)

        Set nozzle 2 strobe to 800 µs duration, 0 µs delay:

        >>> dod.set_led_per_nozzle(2, 800, 0)
        """
        # Validate ranges before touching the robot.
        if not (1 <= duration <= 65000):
            raise ValueError(f"duration must be in [1, 65000]; got {duration!r}.")
        if not (0 <= delay <= 6500):
            raise ValueError(f"delay must be in [0, 6500]; got {delay!r}.")

        # Guard: nozzle must be in the active set.
        raw_status = self.get_nozzle_status()
        _, _, params = self._parse_nozzle_status(raw_status)
        active_channels = list(params.keys())
        if nozzle not in active_channels:
            raise ValueError(
                f"nozzle {nozzle!r} is not in the active set "
                f"{active_channels}. Arm it first with set_nozzle_active()."
            )

        rr = self.client.connect("Test")
        r = self.client.select_nozzle(nozzle)
        time.sleep(0.5)
        r = self.client.setLED(duration, delay)
        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    @_with_reconnect
    def set_humidity(self, value, verbose=False):
        """
        Set the target relative humidity.

        Sends ``GET /DoD/do/SetHumidity?rH={value}`` to the robot server.
        A client-side range check is performed before the request is sent.

        Parameters
        ----------
        value : int
            Target relative humidity in percent (%rH).  Must be in the range
            ``[0, 100]``.
        verbose : bool, optional
            If ``True``, return the full server response object.  If ``False``
            (default), return only the results dict.

        Returns
        -------
        dict or ServerResponse
            Server response after the command.  If ``verbose=False``, returns
            ``r.RESULTS``; if ``verbose=True``, returns the full
            ``ServerResponse`` object.

        Raises
        ------
        ValueError
            If ``value`` is not in ``[0, 100]``.
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Set target humidity to 60 %rH:

        >>> dod.set_humidity(60)
        """
        if not (0 <= value <= 100):
            raise ValueError(f"value must be in [0, 100] %rH; got {value!r}.")
        rr = self.client.connect("Test")
        r = self.client.set_humidity(value)
        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    @_with_reconnect
    def set_cooling_temp(self, temp, verbose=False):
        """
        Set the cooling device temperature.

        Sends ``GET /DoD/do/SetCoolingTemp?Temp={temp}`` to the robot server.
        ``temp`` may be a numeric value (°C) or the string ``'dewpoint'`` to
        enable automatic dewpoint-based adjustment.  A client-side type check
        is performed before the request is sent.

        Parameters
        ----------
        temp : float or str
            Target temperature in degrees Celsius (float or int), or the
            string ``'dewpoint'`` to enable automatic adjustment.
        verbose : bool, optional
            If ``True``, return the full server response object.  If ``False``
            (default), return only the results dict.

        Returns
        -------
        dict or ServerResponse
            Server response after the command.  If ``verbose=False``, returns
            ``r.RESULTS``; if ``verbose=True``, returns the full
            ``ServerResponse`` object.

        Raises
        ------
        ValueError
            If ``temp`` is neither a numeric value nor the string
            ``'dewpoint'``.
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Set cooling to 10 °C:

        >>> dod.set_cooling_temp(10.0)

        Enable automatic dewpoint tracking:

        >>> dod.set_cooling_temp('dewpoint')
        """
        if not (isinstance(temp, (int, float)) or temp == "dewpoint"):
            raise ValueError(
                f"temp must be a numeric value (°C) or the string "
                f"'dewpoint'; got {temp!r}."
            )
        rr = self.client.connect("Test")
        r = self.client.set_cooling_temp(temp)
        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    @_with_reconnect
    def get_drive_range(self, verbose=False):
        """
        Retrieve the maximum range of each axis.

        Sends ``GET /DoD/get/DriveRange`` and returns the maximum allowed
        coordinate for each axis in micrometers.

        Parameters
        ----------
        verbose : bool, optional
            If ``True``, return the full server response object.  If ``False``
            (default), return only the results dict.

        Returns
        -------
        dict or ServerResponse
            If ``verbose=False``, returns ``r.RESULTS`` — expected to be a
            dict of the form ``{"X": max_um, "Y": max_um, "Z": max_um}``.
            If ``verbose=True``, returns the full ``ServerResponse`` object.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Print the axis limits:

        >>> limits = dod.get_drive_range()
        >>> print(limits)
        """
        rr = self.client.connect("Test")
        r = self.client.get_drive_range()
        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    @_with_reconnect
    def do_move(self, position, safety_test=False, verbose=False):
        """
        Move the robot to a named position.

        Parameters
        ----------
        position : str
            Name of the target position as defined in the robot configuration.
        safety_test : bool, optional
            If ``True``, perform a forbidden-region check before moving.
            Safety test is not yet implemented; passing ``True`` will print a
            warning but still execute the move. Default is ``False``.
        verbose : bool, optional
            If ``True``, return the full server response object. If ``False``,
            return only the results dict. Default is ``False``.

        Returns
        -------
        dict or ServerResponse
            Position data after the move completes. If ``verbose=False``,
            returns ``r.RESULTS``. If ``verbose=True``, returns the full
            ``ServerResponse`` object.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Move the robot to a named home position:

        >>> dod.do_move('home')

        Move with verbose output:

        >>> r = dod.do_move('sample_position', verbose=True)
        >>> print(r)
        """
        if self._dryrun:
            print(
                f"[DRY RUN] do_move: move not sent to DAQ server (position='{position}')"
            )
            return None

        r = self.client.connect("Test")
        r = self.client.get_current_positions()
        current_real_position = r.RESULTS["PositionReal"]

        if not safety_test:
            r = self.client.move(position)
        else:
            print("safety test of move has yet to be implemented")

        # Wait for movement to be done
        self.busy_wait(15)

        r = self.client.get_current_positions()
        new_real_position = r.RESULTS["PositionReal"]

        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    @_with_reconnect
    def move_x_abs(self, position_x, safety_test=False, verbose=False):
        """
        Move the robot to an absolute x position (robot coordinate system).

        Parameters
        ----------
        position_x : int
            Absolute target x-position in micrometers.
        safety_test : bool, optional
            If ``True``, perform a forbidden-region check before moving.
            Safety test is not yet fully implemented; passing ``True`` will
            attempt the check but may not fully block unsafe moves. Default is
            ``False``.
        verbose : bool, optional
            If ``True``, return the full server response object. If ``False``,
            return only the results dict. Default is ``False``.

        Returns
        -------
        dict or ServerResponse
            Position data after the move command is issued. If ``verbose=False``,
            returns ``r.RESULTS``. If ``verbose=True``, returns the full
            ``ServerResponse`` object.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Move to x = 150000 micrometers:

        >>> dod.move_x_abs(150000)

        Move with a safety check:

        >>> dod.move_x_abs(150000, safety_test=True)
        """
        r = self.client.connect("Test")
        r = self.client.get_current_positions()
        current_real_position = r.RESULTS["PositionReal"]
        x_current = current_real_position["X"]
        y_current = current_real_position["Y"]
        z_current = current_real_position["Z"]

        if not safety_test:
            r = self.client.move_x(position_x)
        else:
            print("safety test of move has yet to be implemented")
            if self.test_forbidden_region(position_x, y_current):
                r = self.client.move_x(position_x)

        # Wait for movement to be done
        self.busy_wait(25)

        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    @_with_reconnect
    def move_y_abs(self, position_y, safety_test=False, verbose=False):
        """
        Move the robot to an absolute y position (robot coordinate system).

        Parameters
        ----------
        position_y : int
            Absolute target y-position in micrometers.
        safety_test : bool, optional
            If ``True``, perform a forbidden-region check before moving.
            Safety test is not yet fully implemented; passing ``True`` will
            attempt the check but may not fully block unsafe moves. Default is
            ``False``.
        verbose : bool, optional
            If ``True``, return the full server response object. If ``False``,
            return only the results dict. Default is ``False``.

        Returns
        -------
        dict or ServerResponse
            Position data after the move command is issued. If ``verbose=False``,
            returns ``r.RESULTS``. If ``verbose=True``, returns the full
            ``ServerResponse`` object.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Move to y = 30000 micrometers:

        >>> dod.move_y_abs(30000)

        Move with a safety check:

        >>> dod.move_y_abs(30000, safety_test=True)
        """
        r = self.client.connect("Test")
        r = self.client.get_current_positions()
        current_real_position = r.RESULTS["PositionReal"]
        x_current = current_real_position["X"]
        y_current = current_real_position["Y"]
        z_current = current_real_position["Z"]

        if not safety_test:
            r = self.client.move_y(position_y)
        else:
            print("safety test of move has yet to be implemented")
            if self.test_forbidden_region(x_current, position_y):
                r = self.client.move_y(position_y)

        # Wait for movement to be done
        self.busy_wait(25)

        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    @_with_reconnect
    def move_z_abs(self, position_z, safety_test=False, verbose=False):
        """
        Move the robot to an absolute z position (robot coordinate system).

        Parameters
        ----------
        position_z : int
            Absolute target z-position in micrometers.
        safety_test : bool, optional
            If ``True``, perform a forbidden-region check before moving.
            Safety test is not yet fully implemented; passing ``True`` will
            attempt the check but may not fully block unsafe moves. Default is
            ``False``.
        verbose : bool, optional
            If ``True``, return the full server response object. If ``False``,
            return only the results dict. Default is ``False``.

        Returns
        -------
        dict or ServerResponse
            Position data after the move command is issued. If ``verbose=False``,
            returns ``r.RESULTS``. If ``verbose=True``, returns the full
            ``ServerResponse`` object.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Move to z = 20000 micrometers:

        >>> dod.move_z_abs(20000)

        Move with a safety check:

        >>> dod.move_z_abs(20000, safety_test=True)
        """
        r = self.client.connect("Test")
        r = self.client.get_current_positions()
        current_real_position = r.RESULTS["PositionReal"]
        x_current = current_real_position["X"]
        y_current = current_real_position["Y"]
        z_current = current_real_position["Z"]

        if not safety_test:
            r = self.client.move_z(position_z)
        else:
            print("safety test of move has yet to be implemented")
            if self.test_forbidden_region(x_current, y_current):
                r = self.client.move_z(position_z)

        # Wait for movement to be done
        self.busy_wait(25)

        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    @_with_reconnect
    def move_x_rel(self, delta_x, safety_test=False, verbose=False, wait=True):
        """
        Move the robot by a relative offset along the x axis (robot coordinate
        system).

        Reads the current x position and moves to ``x_current + delta_x``.

        Parameters
        ----------
        delta_x : int
            Relative displacement along x in micrometers. Positive values move
            in the positive x direction; negative values move in the negative
            direction.
        safety_test : bool, optional
            If ``True``, perform a forbidden-region check before moving.
            Safety test is not yet fully implemented; passing ``True`` will
            attempt the check but may not fully block unsafe moves. Default is
            ``False``.
        verbose : bool, optional
            If ``True``, return the full server response object. If ``False``,
            return only the results dict. Default is ``False``.
        wait : bool, optional
            If ``True`` (default), block until the move is complete via
            :meth:`busy_wait`. Set to ``False`` to return immediately after
            the move command is acknowledged, without waiting for motion to
            finish. Used by :meth:`move_rel` with ``parallel=True`` to fire
            multiple axes before waiting.

        Returns
        -------
        dict or ServerResponse
            Position data after the move command is issued. If ``verbose=False``,
            returns ``r.RESULTS``. If ``verbose=True``, returns the full
            ``ServerResponse`` object.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Move 5000 µm in the positive x direction:

        >>> dod.move_x_rel(5000)

        Move 2000 µm in the negative x direction:

        >>> dod.move_x_rel(-2000)

        Fire the move without blocking (caller is responsible for waiting):

        >>> dod.move_x_rel(5000, wait=False)
        """
        r = self.client.connect("Test")
        r = self.client.get_current_positions()
        current_real_position = r.RESULTS["PositionReal"]
        x_current = current_real_position["X"]
        y_current = current_real_position["Y"]
        z_current = current_real_position["Z"]

        target_x = x_current + delta_x

        if not safety_test:
            r = self.client.move_x(target_x)
        else:
            print("safety test of move has yet to be implemented")
            if self.test_forbidden_region(target_x, y_current):
                r = self.client.move_x(target_x)

        # Wait for movement to be done (skipped when wait=False)
        if wait:
            self.busy_wait(25)

        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    @_with_reconnect
    def move_y_rel(self, delta_y, safety_test=False, verbose=False, wait=True):
        """
        Move the robot by a relative offset along the y axis (robot coordinate
        system).

        Reads the current y position and moves to ``y_current + delta_y``.

        Parameters
        ----------
        delta_y : int
            Relative displacement along y in micrometers. Positive values move
            in the positive y direction; negative values move in the negative
            direction.
        safety_test : bool, optional
            If ``True``, perform a forbidden-region check before moving.
            Safety test is not yet fully implemented; passing ``True`` will
            attempt the check but may not fully block unsafe moves. Default is
            ``False``.
        verbose : bool, optional
            If ``True``, return the full server response object. If ``False``,
            return only the results dict. Default is ``False``.
        wait : bool, optional
            If ``True`` (default), block until the move is complete via
            :meth:`busy_wait`. Set to ``False`` to return immediately after
            the move command is acknowledged, without waiting for motion to
            finish. Used by :meth:`move_rel` with ``parallel=True`` to fire
            multiple axes before waiting.

        Returns
        -------
        dict or ServerResponse
            Position data after the move command is issued. If ``verbose=False``,
            returns ``r.RESULTS``. If ``verbose=True``, returns the full
            ``ServerResponse`` object.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Move 3000 µm in the positive y direction:

        >>> dod.move_y_rel(3000)

        Move 1500 µm in the negative y direction:

        >>> dod.move_y_rel(-1500)

        Fire the move without blocking (caller is responsible for waiting):

        >>> dod.move_y_rel(3000, wait=False)
        """
        r = self.client.connect("Test")
        r = self.client.get_current_positions()
        current_real_position = r.RESULTS["PositionReal"]
        x_current = current_real_position["X"]
        y_current = current_real_position["Y"]
        z_current = current_real_position["Z"]

        target_y = y_current + delta_y

        if not safety_test:
            r = self.client.move_y(target_y)
        else:
            print("safety test of move has yet to be implemented")
            if self.test_forbidden_region(x_current, target_y):
                r = self.client.move_y(target_y)

        # Wait for movement to be done (skipped when wait=False)
        if wait:
            self.busy_wait(25)

        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    @_with_reconnect
    def move_z_rel(self, delta_z, safety_test=False, verbose=False, wait=True):
        """
        Move the robot by a relative offset along the z axis (robot coordinate
        system).

        Reads the current z position and moves to ``z_current + delta_z``.

        Parameters
        ----------
        delta_z : int
            Relative displacement along z in micrometers. Positive values move
            in the positive z direction; negative values move in the negative
            direction.
        safety_test : bool, optional
            If ``True``, perform a forbidden-region check before moving.
            Safety test is not yet fully implemented; passing ``True`` will
            attempt the check but may not fully block unsafe moves. Default is
            ``False``.
        verbose : bool, optional
            If ``True``, return the full server response object. If ``False``,
            return only the results dict. Default is ``False``.
        wait : bool, optional
            If ``True`` (default), block until the move is complete via
            :meth:`busy_wait`. Set to ``False`` to return immediately after
            the move command is acknowledged, without waiting for motion to
            finish. Used by :meth:`move_rel` with ``parallel=True`` to fire
            multiple axes before waiting.

        Returns
        -------
        dict or ServerResponse
            Position data after the move command is issued. If ``verbose=False``,
            returns ``r.RESULTS``. If ``verbose=True``, returns the full
            ``ServerResponse`` object.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Move 1000 µm in the positive z direction:

        >>> dod.move_z_rel(1000)

        Move 500 µm in the negative z direction:

        >>> dod.move_z_rel(-500)

        Fire the move without blocking (caller is responsible for waiting):

        >>> dod.move_z_rel(1000, wait=False)
        """
        r = self.client.connect("Test")
        r = self.client.get_current_positions()
        current_real_position = r.RESULTS["PositionReal"]
        x_current = current_real_position["X"]
        y_current = current_real_position["Y"]
        z_current = current_real_position["Z"]

        target_z = z_current + delta_z

        if not safety_test:
            r = self.client.move_z(target_z)
        else:
            print("safety test of move has yet to be implemented")
            if self.test_forbidden_region(x_current, y_current):
                r = self.client.move_z(target_z)

        # Wait for movement to be done (skipped when wait=False)
        if wait:
            self.busy_wait(25)

        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    def move_rel(
        self, dx=0, dy=0, dz=0, coordinates="robot", safety_test=False, verbose=False
    ):
        """
        Move the robot by relative offsets in x, y, and z.

        Delegates to :meth:`move_x_rel`, :meth:`move_y_rel`, and
        :meth:`move_z_rel` in sequence for each non-zero delta. Axes with a
        zero delta are skipped entirely, so passing only ``dx`` issues a single
        x move.

        .. note::
            The robot HTTP server rejects any ``do`` command received while a
            move is already in progress (``STATUS == "Busy"``). True parallel
            multi-axis motion is therefore not achievable via this API; axes
            always move sequentially. The only path to simultaneous multi-axis
            motion is :meth:`do_move` with a pre-defined named position.

        Parameters
        ----------
        dx : int, optional
            Relative displacement in micrometers along x. Default is ``0``.
        dy : int, optional
            Relative displacement in micrometers along y. Default is ``0``.
        dz : int, optional
            Relative displacement in micrometers along z. Default is ``0``.
        coordinates : str, optional
            Coordinate system for the supplied deltas:

            - ``'robot'`` (default) — deltas are in the robot frame, identical
              to the convention used by :meth:`move_x_abs`, :meth:`move_y_abs`,
              and :meth:`move_z_abs`.
            - ``'hutch'`` — deltas are in the hutch frame.  The mapping
              ``hutch(x, y, z) = robot(x, −z, y)`` is applied internally before
              the move commands are issued, so the caller works in hutch
              coordinates throughout.

        safety_test : bool, optional
            If ``True``, pass a forbidden-region check to each single-axis move.
            Not yet fully implemented. Default is ``False``.
        verbose : bool, optional
            If ``True``, return the full ``ServerResponse`` of the last axis
            moved. If ``False``, return the results dict of the last axis moved.
            Default is ``False``.

        Returns
        -------
        dict or ServerResponse or None
            Result from the last non-zero axis move, or ``None`` if all deltas
            are zero.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached during any single-axis move.

        Examples
        --------
        Move 5000 µm in x and −2000 µm in z (robot frame):

        >>> dod.move_rel(dx=5000, dz=-2000)

        Move 1000 µm along the hutch y axis:

        >>> dod.move_rel(dy=1000, coordinates='hutch')

        Move in all three hutch axes (sequentially):

        >>> dod.move_rel(dx=500, dy=1000, dz=-300, coordinates='hutch')
        """
        # Convert hutch deltas to robot deltas if requested.
        # hutch(x, y, z) = robot(x, −z, y)
        # ⟹  robot_x = hutch_x,  robot_y = hutch_z,  robot_z = −hutch_y
        if coordinates == "hutch":
            dx_robot = dx
            dy_robot = dz
            dz_robot = -dy
        else:
            dx_robot = dx
            dy_robot = dy
            dz_robot = dz

        # Sequential: each axis waits for completion before the next starts.
        # The robot rejects do-commands issued while Busy, so parallel motion
        # is not possible via this HTTP API.
        r = None
        if dx_robot != 0:
            r = self.move_x_rel(dx_robot, safety_test=safety_test, verbose=verbose)
        if dy_robot != 0:
            r = self.move_y_rel(dy_robot, safety_test=safety_test, verbose=verbose)
        if dz_robot != 0:
            r = self.move_z_rel(dz_robot, safety_test=safety_test, verbose=verbose)
        return r

    @_with_reconnect
    def do_task(
        self,
        task_name,
        handle_dialog="raise",
        verbose=False,
        poll_interval=2.0,
    ):
        """
        Execute a named task on the robot.

         Blocks until the task completes, ``safety_abort`` is set to ``True``,
         or a robot dialog requires operator attention.  If a dialog appears
         during execution, behaviour is controlled by ``handle_dialog``.

         Parameters
         ----------
         task_name : str
             Name of the task to execute.
         handle_dialog : str, optional
            Controls how robot dialogs (``Status == "Dialog"``) are handled
            during task execution.  The dialog reference, message, and button
            labels are always printed to the console regardless of this setting.
            Options:

            - ``'raise'`` (default) — surface the dialog, print its content,
              and return a dict describing the paused state.  The robot holds
              the task open; call :meth:`close_dialog` manually to dismiss it,
              then continue or stop as appropriate.
            - ``'auto_1'`` — automatically close all dialogs with selection
              ``1`` (Button1) and continue waiting for task completion.
            - ``'auto_2'`` — automatically close all dialogs with selection
              ``2`` (Button2) and continue waiting for task completion.
            - ``'auto_ok'`` — automatically close single-button dialogs
              (Button2 empty) with selection ``1``; surface two-button dialogs
              as per ``'raise'``.

        verbose : bool, optional
            If ``True``, return the full server response object. If ``False``,
            return only the results dict. Default is ``False``.
        poll_interval : float, optional
            Time in seconds between status polls while the robot is busy.
            Default is ``2.0`` s.  Reduce for short tasks where tighter
            completion latency is needed.

        Returns
        -------
        dict or ServerResponse
            Task result data on normal completion.  If ``verbose=False``,
            returns ``r.RESULTS``; if ``verbose=True``, returns the full
            ``ServerResponse`` object.

            If ``handle_dialog`` causes a dialog to be surfaced, returns a
            dict of the form::

                {
                    "status": "dialog_paused",
                    "reference": <int>,
                    "message": <str>,
                    "button1": <str>,
                    "button2": <str>,
                }

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Execute a task, surfacing any dialogs for manual handling (default):

        >>> dod.do_task('wash_nozzle')

        Execute a task and auto-close single-button dialogs silently:

        >>> dod.do_task('MoveToProbe_96WP', handle_dialog='auto_ok')

        Execute a task and auto-close all dialogs with Button1:

        >>> dod.do_task('MoveToProbe_96WP', handle_dialog='auto_1')

        Execute a task and inspect the full response:

        >>> r = dod.do_task('wash_nozzle', verbose=True)
        >>> print(r.ERROR_CODE)
        """
        if self._dryrun:
            print(f"[DRY RUN] do_task: task '{task_name}' not executed on DAQ server")
            return None

        rr = self.client.connect("Test")
        r = self.client.execute_task(task_name)

        # Wait for task to be done; also handle Dialog state mid-task.
        while r.STATUS["Status"] in ("Busy", "Dialog"):
            if r.STATUS["Status"] == "Dialog":
                # Extract dialog content from RESULTS.
                dialog = r.RESULTS.get("Dialog", {})
                ref = dialog.get("Reference", "?")
                msg = dialog.get("Message", "")
                btn1 = dialog.get("Button1", "OK")
                btn2 = dialog.get("Button2", "")

                # Always print the dialog so there is a console record.
                print(f"\n[DoD] Dialog (ref={ref}):")
                print(f"      {msg}")
                if btn2:
                    print(f"      Buttons: [1] {btn1}  [2] {btn2}")
                else:
                    print(f"      Buttons: [1] {btn1}")

                is_single_button = btn2 == ""

                # Determine whether to auto-close or surface.
                auto_select = None
                if handle_dialog == "auto_1":
                    auto_select = 1
                elif handle_dialog == "auto_2":
                    auto_select = 2
                elif handle_dialog == "auto_ok" and is_single_button:
                    auto_select = 1

                if auto_select is not None:
                    print(f"      Auto-closing with selection {auto_select}.")
                    self.client.close_dialog(ref, str(auto_select))
                    time.sleep(0.5)
                    r = self.client.get_status()
                    continue
                else:
                    # Surface the dialog — return paused-state dict.
                    if btn2:
                        print(
                            f"      → To close: dod.close_current_dialog(1)  "
                            f"or  dod.close_current_dialog(2)"
                        )
                    else:
                        print(f"      → To close: dod.close_current_dialog(1)")
                    print(f"      Task paused.")
                    return {
                        "status": "dialog_paused",
                        "reference": ref,
                        "message": msg,
                        "button1": btn1,
                        "button2": btn2,
                    }

            print(f"[DoD] Robot busy — checking again in {poll_interval} s ...")
            time.sleep(poll_interval)
            r = self.client.get_status()
            if self.safety_abort:
                r = self.client.stop_task()
                print("User aborted task execution")
                return r

        r = self.client.get_status()

        # Check if any error occurred
        if r.ERROR_CODE == 0:
            print("no error")
        else:
            print("error while performing task!")

        if verbose:
            return r
        else:
            return r.RESULTS

    @_with_reconnect
    def close_dialog(self, reference, selection, verbose=False):
        """
        Close an open robot dialog by specifying its reference and button selection.

        When the robot status is ``"Dialog"``, task execution is paused and the
        robot waits for a button acknowledgement.  Call :meth:`get_status` first
        to read the dialog reference integer and the available button labels, then
        call this method to dismiss the dialog and allow the task to resume.

        .. note::
            If more than one dialog is open, :meth:`get_status` reports the
            **last** (most recent) dialog, which is typically the **first** to
            be closed (LIFO order).  Call :meth:`close_dialog` once per dialog
            and re-poll :meth:`get_status` after each call to check whether
            further dialogs remain.

        Parameters
        ----------
        reference : int
            The dialog reference integer as reported in
            ``get_status()['Dialog']['Reference']``.  The robot assigns an
            incrementing integer to each dialog occurrence, starting at ``1``
            when the device is initialised.
        selection : int
            Button to press: ``1`` for Button1 (typically ``'OK'`` or
            ``'Yes'``), ``2`` for Button2 (typically ``'Abort'`` or ``'No'``).
            If only one button is available (Button2 is empty), use ``1``.
        verbose : bool, optional
            If ``True``, return the full server response object.  If ``False``,
            return only the results dict.  Default is ``False``.

        Returns
        -------
        dict or ServerResponse
            Server response after closing the dialog.  If ``verbose=False``,
            returns ``r.RESULTS``.  If ``verbose=True``, returns the full
            ``ServerResponse`` object.

        Raises
        ------
        ValueError
            If ``selection`` is not ``1`` or ``2``.
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Read the current dialog and close it with Button1:

        >>> status = dod.get_status()
        >>> ref = status['Dialog']['Reference']
        >>> print(status['Dialog']['Message'])
        >>> print(status['Dialog']['Button1'], '/', status['Dialog'].get('Button2', ''))
        >>> dod.close_dialog(ref, 1)

        Close a two-button dialog with Button2 (e.g. 'Abort'):

        >>> dod.close_dialog(ref, 2)
        """
        if selection not in (1, 2):
            raise ValueError(f"selection must be 1 or 2, got {selection!r}.")
        rr = self.client.connect("Test")
        r = self.client.close_dialog(reference, str(selection))
        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    def close_current_dialog(self, selection, verbose=False):
        """
        Close the currently active robot dialog in a single call.

        Convenience wrapper around :meth:`get_status` and :meth:`close_dialog`.
        Reads the active dialog reference automatically so the operator does not
        need to extract it manually.  The dialog message and button labels are
        printed to the console before the dialog is closed.

        If no dialog is currently open (``Status != "Dialog"``), a warning is
        printed and the method returns ``None``.

        Parameters
        ----------
        selection : int
            Button to press: ``1`` for Button1 (typically ``'OK'`` or
            ``'Yes'``), ``2`` for Button2 (typically ``'Abort'`` or ``'No'``).
        verbose : bool, optional
            If ``True``, return the full server response from
            :meth:`close_dialog`.  If ``False``, return only the results dict.
            Default is ``False``.

        Returns
        -------
        dict or ServerResponse or None
            Result of :meth:`close_dialog` on success.  ``None`` if no dialog
            was active.

        Raises
        ------
        ValueError
            If ``selection`` is not ``1`` or ``2``.

        Examples
        --------
        Close the current dialog with Button1 (OK):

        >>> dod.close_current_dialog(1)

        Close the current dialog with Button2 (Abort):

        >>> dod.close_current_dialog(2)
        """
        r = self.get_status(verbose=True)
        if r.STATUS.get("Status") != "Dialog":
            print(
                f"[DoD] close_current_dialog: no dialog is active "
                f"(current Status = {r.STATUS.get('Status')!r})."
            )
            return None

        dialog = r.RESULTS.get("Dialog", {})
        ref = dialog.get("Reference", "?")
        msg = dialog.get("Message", "")
        btn1 = dialog.get("Button1", "OK")
        btn2 = dialog.get("Button2", "")

        print(f"[DoD] Dialog (ref={ref}):")
        print(f"      {msg}")
        if btn2:
            print(f"      Buttons: [1] {btn1}  [2] {btn2}")
        else:
            print(f"      Buttons: [1] {btn1}")
        print(f"      Closing with selection {selection}.")

        return self.close_dialog(ref, selection, verbose=verbose)

    @_with_reconnect
    def reset_error(self, verbose=False):
        """
        Reset a persistent robot ``"Error"`` status after all dialogs are closed.

        After closing all error dialogs via :meth:`close_dialog`, the robot may
        remain in ``"Error"`` state with a non-``'NA'`` ``ErrorMessage``.  Call
        this method to clear the error and return the robot to ``"Idle"``.

        .. note::
            Only call this method after all open dialogs have been dismissed.
            Check :meth:`get_status` first — if ``Status`` is still ``"Dialog"``
            there are dialogs remaining that must be closed before calling this
            method.

        Parameters
        ----------
        verbose : bool, optional
            If ``True``, return the full server response object.  If ``False``,
            return only the results dict.  Default is ``False``.

        Returns
        -------
        dict or ServerResponse
            Server response after the reset command.  If ``verbose=False``,
            returns ``r.RESULTS``.  If ``verbose=True``, returns the full
            ``ServerResponse`` object.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Close all dialogs and then reset error state:

        >>> dod.close_dialog(ref, 1)
        >>> dod.reset_error()

        Check status after reset:

        >>> print(dod.get_status()['Status'])
        """
        rr = self.client.connect("Test")
        r = self.client.reset_error()
        rr = self.client.disconnect()
        if verbose:
            return r
        else:
            return r.RESULTS

    def get_forbidden_region(self, rotation_state="both"):
        """
        Return the list of forbidden regions for a given rotation state.

        Forbidden regions are defined as rectangles in the robot x-y plane.
        The returned list depends on the current rotation state of the robot.

        Parameters
        ----------
        rotation_state : str, optional
            Rotation state for which to retrieve forbidden regions. Options are:

            - ``'horizontal'`` — nozzle sideways, base at 90 degrees.
            - ``'vertical'`` — nozzle vertical, base at 0 degrees.
            - ``'both'`` — combined list for both states (default).

        Returns
        -------
        list of tuple
            List of forbidden region tuples of the form
            ``(x_start, x_stop, y_start, y_stop)``.

        Examples
        --------
        Get forbidden regions for the horizontal rotation state:

        >>> regions = dod.get_forbidden_region(rotation_state='horizontal')
        >>> print(regions)

        Get all forbidden regions:

        >>> all_regions = dod.get_forbidden_region()
        """
        if rotation_state == "vertical":
            test_list_safety = self.forbidden_regions_vertical
        elif rotation_state == "horizontal":
            test_list_safety = self.forbidden_regions_horizontal
        else:
            test_list_safety = (
                self.forbidden_regions_horizontal + self.forbidden_regions_vertical
            )

        return test_list_safety

    def set_forbidden_region(
        self, x_start, x_stop, y_start, y_stop, rotation_state="both"
    ):
        """
        Define a forbidden region in the robot x-y plane.

        Forbidden regions are rectangles within which robot end-point motion is
        not allowed. Only the endpoint is checked; path safety is not enforced.

        Parameters
        ----------
        x_start : float
            Starting x-coordinate of the forbidden rectangle (micrometers).
        x_stop : float
            Ending x-coordinate of the forbidden rectangle (micrometers).
        y_start : float
            Starting y-coordinate of the forbidden rectangle (micrometers).
        y_stop : float
            Ending y-coordinate of the forbidden rectangle (micrometers).
        rotation_state : str, optional
            Rotation state for which this region applies. Options are:

            - ``'horizontal'`` — applies only in horizontal rotation.
            - ``'vertical'`` — applies only in vertical rotation.
            - ``'both'`` — applies in both rotation states (default).

        Raises
        ------
        None
            Prints a warning if an invalid ``rotation_state`` is provided.

        Examples
        --------
        Forbid the full x-range at low y-values for all rotation states:

        >>> dod.set_forbidden_region(0, 300000, 0, 10000, rotation_state='both')

        Add a region forbidden only in horizontal rotation:

        >>> dod.set_forbidden_region(0, 300000, 50000, 100000, rotation_state='horizontal')
        """
        region_tuple = (
            min(x_start, x_stop),
            max(x_start, x_stop),
            min(y_start, y_stop),
            max(y_start, y_stop),
        )
        if rotation_state == "horizontal":
            self.forbidden_regions_horizontal.append(region_tuple)
        elif rotation_state == "vertical":
            self.forbidden_regions_vertical.append(region_tuple)
        elif rotation_state == "both":
            self.forbidden_regions_vertical.append(region_tuple)
            self.forbidden_regions_horizontal.append(region_tuple)
        else:
            print("invalid input of rotation state")

    def test_forbidden_region(self, x_test, y_test):
        """
        Test whether a target endpoint is inside a forbidden region.

        Checks the given (x, y) coordinates against the list of forbidden
        regions appropriate for the current base rotation state. Only the
        endpoint is tested; the motion path is not checked.

        Parameters
        ----------
        x_test : float
            x-coordinate of the target endpoint to test (micrometers).
        y_test : float
            y-coordinate of the target endpoint to test (micrometers).

        Returns
        -------
        bool
            ``True`` if the endpoint is safe (not in any forbidden region),
            ``False`` if the endpoint is inside a forbidden region.

        Raises
        ------
        ConnectionError
            If the CoDI base position cannot be read.

        Examples
        --------
        Check if a target position is safe before moving:

        >>> safe = dod.test_forbidden_region(150000, 30000)
        >>> if not safe:
        ...     print('Target position is forbidden.')
        """
        # Get current rotation state
        pos_rot_base = round(self.codi.CoDI_rot_base.wm(), 0)

        # Initialize safe flag (True = safe)
        flag_safe_endpoint = True

        # Select the relevant forbidden region list based on rotation state
        if pos_rot_base == 90:
            test_list_safety = self.forbidden_regions_horizontal
        elif pos_rot_base == 0:
            test_list_safety = self.forbidden_regions_vertical
        else:
            test_list_safety = (
                self.forbidden_regions_horizontal + self.forbidden_regions_vertical
            )

        # Test each region
        for tuple_current in test_list_safety:
            x_start, x_stop, y_start, y_stop = tuple_current
            if (
                (x_start < x_test)
                and (x_stop > x_test)
                and (y_start < y_test)
                and (y_stop > y_test)
            ):
                flag_safe_endpoint = flag_safe_endpoint and False
            else:
                flag_safe_endpoint = flag_safe_endpoint and True

        return flag_safe_endpoint

    def _timing_update(self):
        """
        Recalculate and apply all trigger delays based on current timing parameters.

        Private worker — called by all public timing setters after updating a
        stored parameter.  Updates nozzle 1, nozzle 2, and LED trigger delays
        using the stored absolute and relative timing values.  If a calculated
        nozzle delay is negative, one full 120 Hz period
        (``_PERIOD_120HZ_NS`` ≈ 8.33 ms) is added.

        Returns
        -------
        None

        Raises
        ------
        ConnectionError
            If any EVR trigger PV cannot be written.
        """
        # Nozzle 1
        self.timing_nozzle_1 = (
            self.timing_Xray
            - self.timing_delay_nozzle_1
            - self.timing_delay_sciPulse
            - self.timing_delay_reaction
        )
        if self.timing_nozzle_1 < 0:
            self.timing_nozzle_1 = self.timing_nozzle_1 + _PERIOD_120HZ_NS

        # Nozzle 2
        self.timing_nozzle_2 = (
            self.timing_Xray
            - self.timing_delay_nozzle_2
            - self.timing_delay_sciPulse
            - self.timing_delay_reaction
        )
        if self.timing_nozzle_2 < 0:
            self.timing_nozzle_2 = self.timing_nozzle_2 + _PERIOD_120HZ_NS

        # LED
        self.timing_LED = self.timing_Xray + self.timing_delay_LED

        if self._dryrun:
            if not getattr(self, "_dryrun_quiet", False):
                print(
                    f"[DRY RUN] _timing_update: timing PVs not written "
                    f"(nozzle_1={self.timing_nozzle_1:.0f} ns, "
                    f"nozzle_2={self.timing_nozzle_2:.0f} ns, "
                    f"LED={self.timing_LED:.0f} ns)"
                )
            return

        self.trigger_nozzle_1.ns_delay.put(self.timing_nozzle_1)
        self.trigger_nozzle_2.ns_delay.put(self.timing_nozzle_2)
        self.trigger_LED.ns_delay.put(self.timing_LED)

    def set_nozzle_timing_zero(self, nozzle, timing):
        """
        Set the time-zero delay for a nozzle based on LED alignment.

        Sets the absolute reference delay for the specified nozzle as measured
        from the LED alignment procedure, then calls :meth:`_timing_update`
        to apply the change.

        Parameters
        ----------
        nozzle : int
            Nozzle number to configure. Must be ``1`` or ``2``.
        timing : float
            Absolute delay in nanoseconds from the robot LED alignment.

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If ``nozzle`` is not ``1`` or ``2``.

        Examples
        --------
        Set time zero for nozzle 1 based on alignment result:

        >>> dod.set_nozzle_timing_zero(1, 12500.0)
        """
        if nozzle == 1:
            self.timing_delay_nozzle_1 = timing
        elif nozzle == 2:
            self.timing_delay_nozzle_2 = timing
        else:
            raise ValueError(f"Invalid nozzle {nozzle!r}: must be 1 or 2.")

        # Update timings
        self._timing_update()

    def set_led_timing_rel(self, timing_rel):
        """
        Set the relative timing of the LED with respect to the X-rays.

        Updates ``timing_delay_LED`` and calls :meth:`_timing_update` to
        apply the change to the EVR trigger.

        Parameters
        ----------
        timing_rel : float
            Desired LED delay relative to X-ray timing in nanoseconds.

        Returns
        -------
        None

        Raises
        ------
        ConnectionError
            If the LED trigger PV cannot be written.

        Examples
        --------
        Set the LED to fire 1000 ns after the X-ray pulse:

        >>> dod.set_led_timing_rel(1000.0)
        """
        self.timing_delay_LED = timing_rel

        # Update timings
        self._timing_update()

    def set_reaction_timing_rel(self, timing_rel):
        """
        Set the relative reaction delay with respect to the X-rays.

        Updates ``timing_delay_reaction`` and calls :meth:`_timing_update`
        to propagate the change to all nozzle triggers.

        Parameters
        ----------
        timing_rel : float
            Desired reaction delay relative to X-ray timing in nanoseconds.

        Returns
        -------
        None

        Raises
        ------
        ConnectionError
            If any nozzle trigger PV cannot be written.

        Examples
        --------
        Set a 5000 ns reaction delay:

        >>> dod.set_reaction_timing_rel(5000.0)
        """
        self.timing_delay_reaction = timing_rel

        # Update timings
        self._timing_update()

    def set_xray_timing_ref(self, timing_abs):
        """
        Set the absolute X-ray timing reference used for nozzle delay calculations.

        Updates the stored X-ray timing reference and calls
        :meth:`_timing_update` to recalculate and apply all dependent
        trigger delays.  Does not directly write to the X-ray trigger PV;
        ``timing_abs`` is a local reference value used in nozzle delay math.

        Parameters
        ----------
        timing_abs : float
            Absolute X-ray trigger delay in nanoseconds.

        Returns
        -------
        None

        Raises
        ------
        ConnectionError
            If any dependent trigger PV cannot be written.

        Examples
        --------
        Update the X-ray timing reference to 700000 ns:

        >>> dod.set_xray_timing_ref(700000.0)
        """
        self.timing_Xray = timing_abs

        # Update timings
        self._timing_update()

    def set_nozzle_timing_rel(self, nozzle, timing_rel):
        """
        Adjust the timing of a nozzle by a relative offset.

        Increments the current delay of the specified nozzle by ``timing_rel``
        and calls :meth:`_timing_update` to apply the change.

        Parameters
        ----------
        nozzle : int
            Nozzle number to adjust. Must be ``1`` or ``2``.
        timing_rel : float
            Amount to add to the current nozzle delay in nanoseconds.
            Use a negative value to decrease the delay.

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If ``nozzle`` is not ``1`` or ``2``.

        Examples
        --------
        Advance nozzle 1 by 500 ns:

        >>> dod.set_nozzle_timing_rel(1, 500.0)

        Delay nozzle 2 by 200 ns:

        >>> dod.set_nozzle_timing_rel(2, -200.0)
        """
        if nozzle == 1:
            self.timing_delay_nozzle_1 = self.timing_delay_nozzle_1 + timing_rel
        elif nozzle == 2:
            self.timing_delay_nozzle_2 = self.timing_delay_nozzle_2 + timing_rel
        else:
            raise ValueError(f"Invalid nozzle {nozzle!r}: must be 1 or 2.")

        # Update timings
        self._timing_update()

    def set_nozzle_timing_abs(self, nozzle, timing_abs):
        """
        Set the absolute EVR delay for a nozzle directly.

        Assigns ``timing_abs`` to the stored nozzle delay and calls
        :meth:`_timing_update` to apply the change.  This is the direct
        operational setter for in-run adjustments; use
        :meth:`set_nozzle_timing_zero` for the LED-calibration step.

        Parameters
        ----------
        nozzle : int
            Nozzle number to configure. Must be ``1`` or ``2``.
        timing_abs : float
            Absolute nozzle delay in nanoseconds.

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If ``nozzle`` is not ``1`` or ``2``.

        Examples
        --------
        Set nozzle 1 delay to 15000 ns:

        >>> dod.set_nozzle_timing_abs(1, 15000.0)
        """
        if nozzle == 1:
            self.timing_delay_nozzle_1 = timing_abs
        elif nozzle == 2:
            self.timing_delay_nozzle_2 = timing_abs
        else:
            raise ValueError(f"Invalid nozzle {nozzle!r}: must be 1 or 2.")

        # Update timings
        self._timing_update()

    def _format_timing(self):
        """
        Format all timing parameters as a multi-line string.

        All values are displayed in **µs** (``raw_ns / 1000``).  This is the
        single source of truth for timing display used by :meth:`print_timing`
        and :meth:`logging_string`.

        Returns
        -------
        str
            Formatted multi-line string with all timing values in µs.
        """
        lines = [
            "Timing parameters (all values in µs):",
            f"  timing_Xray ref:       {self.timing_Xray / 1000:.3f} µs",
            f"  timing_delay_reaction: {self.timing_delay_reaction / 1000:.3f} µs",
            f"  timing_delay_nozzle_1: {self.timing_delay_nozzle_1 / 1000:.3f} µs",
            f"  timing_delay_nozzle_2: {self.timing_delay_nozzle_2 / 1000:.3f} µs",
            f"  timing_delay_LED:      {self.timing_delay_LED / 1000:.3f} µs",
            "  ---",
            f"  timing_nozzle_1 (abs): {self.timing_nozzle_1 / 1000:.3f} µs",
            f"  timing_nozzle_2 (abs): {self.timing_nozzle_2 / 1000:.3f} µs",
            f"  timing_LED (abs):      {self.timing_LED / 1000:.3f} µs",
        ]
        return "\n".join(lines)

    def print_timing(self):
        """
        Print all current timing parameters to the console.

        Calls :meth:`_format_timing` and prints the result.  Convenience
        method for interactive use in a hutch-python session.

        Examples
        --------
        >>> dod.print_timing()
        """
        print(self._format_timing())

    def logging_string(self, post_elog=False, tag="DoD", run_number=None):
        """
        Generate a formatted string for posting to the e-log.

        Collects the current CoDI position and all timing parameters and
        formats them into a human-readable string suitable for logging.
        Timing values are displayed in µs via :meth:`_format_timing`.

        Parameters
        ----------
        post_elog : bool, optional
            If ``True``, post the string to the MFX e-log in addition to
            returning it.  Default is ``False``.  The ``mfx.db.elog`` import
            is guarded inside this branch so the method remains usable
            off-hutch.
        tag : str, optional
            Tag applied to the e-log post when ``post_elog=True``.
            Default is ``'DoD'``.
        run_number : int or None, optional
            Run number to associate with the e-log post.  Passed through to
            ``elog.post(run=run_number)``.  Default is ``None``.

        Returns
        -------
        str
            Multi-line string containing CoDI position data and timing
            parameter values.  Always returned regardless of ``post_elog``.

        Examples
        --------
        Return the log string without posting:

        >>> log_entry = dod.logging_string()
        >>> print(log_entry)

        Return and post to the e-log with the default tag:

        >>> dod.logging_string(post_elog=True)

        Post with a custom tag and run number:

        >>> dod.logging_string(post_elog=True, tag='CoDI', run_number=42)
        """
        post_str = ""

        # CoDI angles (only available when DoD was instantiated with modules='codi'):
        if hasattr(self, "codi"):
            position = self.codi.get_pos()
            position_str = (
                "CoDI Information:\n"
                f"  name:      {position[0]}\n"
                f"  rot_base:  {position[1]}\n"
                f"  rot_left:  {position[2]}\n"
                f"  rot_right: {position[3]}\n"
                f"  z-transl:  {position[4]}"
            )
        else:
            position_str = "CoDI not loaded (DoD instantiated without modules='codi')"
        post_str = post_str + position_str + "\n\n"

        # Timings:
        post_str = post_str + self._format_timing() + "\n"

        if post_elog:
            if self._dryrun:
                print(
                    "[DRY RUN] logging_string: elog post suppressed — message that would be posted:"
                )
                print(post_str)
            else:
                from mfx.db import elog

                elog.post(msg=post_str, tags=tag, run=run_number)

        return post_str
