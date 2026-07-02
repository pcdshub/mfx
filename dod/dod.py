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
        log_file="/tmp/dod.log" #"/cds/group/pcds/pyps/apps/hutch-python/mfx/dod/dod.log",
    ):
        from dod.ServerResponse import ServerResponse

        import time

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

        # Redirect dod.DropsDriver and dod.HTTPTransceiver log output to a file
        # so INFO messages do not appear on the console. propagate=False prevents
        # the records from also reaching the root (console) handler.
        _dod_log_fmt = logging.Formatter(
            "%(asctime)s  %(name)s  %(levelname)s  %(message)s"
        )
        for _log_name in ("dod.DropsDriver", "dod.HTTPTransceiver"):
            _lgr = logging.getLogger(_log_name)
            # Idempotency guard: avoid adding a duplicate FileHandler if DoD()
            # is instantiated more than once in the same session.
            if not any(isinstance(h, logging.FileHandler) for h in _lgr.handlers):
                _fh = logging.FileHandler(log_file)
                _fh.setFormatter(_dod_log_fmt)
                _lgr.addHandler(_fh)
            _lgr.propagate = False

        # Initializing the robot client that is used for communication
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

            self.codi = CoDI()

        # Timing section
        from pcdsdevices.evr import Trigger

        self.delay = None

        # Trigger objects
        self.trigger_Xray = Trigger(
            "MFX:LAS:EVR:01:TRIG7", name="trigger_X-ray_simulator"
        )
        self.trigger_nozzle_1 = Trigger("MFX:LAS:EVR:01:TRIG2", name="trigger_nozzle_1")
        self.trigger_nozzle_2 = Trigger("MFX:LAS:EVR:01:TRIG3", name="trigger_nozzle_2")
        self.trigger_LED = Trigger("MFX:LAS:EVR:01:TRIG1", name="trigger_LED_array")

        # Timing parameters
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
        if verbose == True:
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

        if verbose == True:
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
        if verbose == True:
            return r
        else:
            return r.RESULTS

    @_with_reconnect
    def busy_wait(self, timeout):
        """
        Block until the robot is no longer busy or the timeout is reached.

        Polls the robot status every 100 ms. Returns immediately if the robot
        is not busy.

        Parameters
        ----------
        timeout : float
            Maximum time to wait in seconds before returning.

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
        """
        import time

        start = time.time()
        r = self.client.get_status()
        delta = 0

        while r.STATUS["Status"] == "Busy":
            if delta > timeout:
                return True

            time.sleep(0.1)  # Wait 100 ms to avoid spamming the robot
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
        if verbose == True:
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
        if verbose == True:
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
        if verbose == True:
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
        if verbose == True:
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
            - ``'Triggered'`` — dispense on external trigger.
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

        >>> dod.set_nozzle_dispensing(mode='Triggered')

        Turn off dispensing on all nozzles:

        >>> dod.set_nozzle_dispensing(mode='Off')
        """
        rr = self.client.connect("Test")
        if mode == "Free":
            r = self.client.dispensing("Free")
        elif mode == "Triggered":
            r = self.client.dispensing("Triggered")
        else:
            # Turns active nozzles off. Safer if all nozzles would be turned off
            r = self.client.dispensing("Off")
            for i in [1, 2, 3, 4]:
                r = self.client.select_nozzle(i)
                r = self.client.dispensing("Off")

        rr = self.client.disconnect()
        if verbose == True:
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
        r = self.client.connect("Test")
        r = self.client.get_current_positions()
        current_real_position = r.RESULTS["PositionReal"]

        if safety_test == False:
            r = self.client.move(position)
        else:
            print("safety test of move has yet to be implemented")

        # Wait for movement to be done
        self.busy_wait(15)

        r = self.client.get_current_positions()
        new_real_position = r.RESULTS["PositionReal"]

        rr = self.client.disconnect()
        if verbose == True:
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
        x_current, y_current, z_current = current_real_position

        if safety_test == False:
            r = self.client.move_x(position_x)
        else:
            print("safety test of move has yet to be implemented")
            if self.test_forbidden_region(position_x, y_current):
                r = self.client.move_x(position_x)

        # Wait for movement to be done
        self.busy_wait(25)

        rr = self.client.disconnect()
        if verbose == True:
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
        x_current, y_current, z_current = current_real_position

        if safety_test == False:
            r = self.client.move_y(position_y)
        else:
            print("safety test of move has yet to be implemented")
            if self.test_forbidden_region(x_current, position_y):
                r = self.client.move_y(position_y)

        # Wait for movement to be done
        self.busy_wait(25)

        rr = self.client.disconnect()
        if verbose == True:
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
        x_current, y_current, z_current = current_real_position

        if safety_test == False:
            r = self.client.move_z(position_z)
        else:
            print("safety test of move has yet to be implemented")
            if self.test_forbidden_region(x_current, y_current):
                r = self.client.move_z(position_z)

        # Wait for movement to be done
        self.busy_wait(25)

        rr = self.client.disconnect()
        if verbose == True:
            return r
        else:
            return r.RESULTS

    @_with_reconnect
    def do_task(self, task_name, safety_check=False, verbose=False):
        """
        Execute a named task on the robot.

        Blocks until the task completes or until ``safety_abort`` is set to
        ``True``, in which case the task is stopped immediately.

        Parameters
        ----------
        task_name : str
            Name of the task to execute.
        safety_check : bool, optional
            If ``True``, perform a safety check before executing the task.
            Safety check is not yet implemented; passing ``True`` will print a
            warning. Default is ``False``.
        verbose : bool, optional
            If ``True``, return the full server response object. If ``False``,
            return only the results dict. Default is ``False``.

        Returns
        -------
        dict or ServerResponse
            Task result data. If ``verbose=False``, returns ``r.RESULTS``.
            If ``verbose=True``, returns the full ``ServerResponse`` object.

        Raises
        ------
        ConnectionError
            If the robot server cannot be reached.

        Examples
        --------
        Execute a task named ``'wash_nozzle'``:

        >>> dod.do_task('wash_nozzle')

        Execute a task and inspect the full response:

        >>> r = dod.do_task('wash_nozzle', verbose=True)
        >>> print(r.ERROR_CODE)
        """
        import time

        rr = self.client.connect("Test")
        if safety_check == False:
            r = self.client.execute_task(task_name)
        else:
            print("safety check needs to be implemented")

        # Wait for task to be done
        while r.STATUS["Status"] == "Busy":
            time.sleep(0.5)
            r = self.client.get_status()
            if self.safety_abort == True:
                r = self.client.stop_task()
                print("User aborted task execution")
                return r

        r = self.client.get_status()

        # Check if any error occurred
        if r.ERROR_CODE == 0:
            print("no error")
        else:
            print("error while performing task!")

        if verbose == True:
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
        from dod.codi import CoDI_base

        # Get current rotation state
        pos_rot_base = round(CoDI_base.wm(), 0)

        # Initialize safe flag (True = safe)
        flag_safe_endpoint = True

        # Select the relevant forbidden region list based on rotation state
        if pos_rot_base == 90:
            test_list_safety = self.forbidden_regions_vertical
        elif pos_rot_base == 0:
            test_list_safety = self.forbidden_regions_horizontal
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

    def set_timing_update(self):
        """
        Recalculate and apply all trigger delays based on current timing parameters.

        Updates nozzle 1, nozzle 2, and LED trigger delays using the stored
        absolute and relative timing values. If a calculated nozzle delay is
        negative, one full 120 Hz period (approximately 8.33 ms) is added.

        Returns
        -------
        None

        Raises
        ------
        ConnectionError
            If any EVR trigger PV cannot be written.

        Examples
        --------
        Apply updated timings after changing a delay parameter:

        >>> dod.timing_delay_reaction = 5000
        >>> dod.set_timing_update()
        """
        # Nozzle 1
        self.timing_nozzle_1 = (
            self.timing_Xray
            - self.timing_delay_nozzle_1
            - self.timing_delay_sciPulse
            - self.timing_delay_reaction
        )
        if self.timing_nozzle_1 < 0:
            self.timing_nozzle_1 = self.timing_nozzle_1 + 1 / 120 * 1000000000
        self.trigger_nozzle_1.ns_delay.put(self.timing_nozzle_1)

        # Nozzle 2
        self.timing_nozzle_2 = (
            self.timing_Xray
            - self.timing_delay_nozzle_2
            - self.timing_delay_sciPulse
            - self.timing_delay_reaction
        )
        if self.timing_nozzle_2 < 0:
            self.timing_nozzle_2 = self.timing_nozzle_2 + 1 / 120 * 1000000000
        self.trigger_nozzle_2.ns_delay.put(self.timing_nozzle_2)

        # LED
        self.timing_LED = self.timing_Xray + self.timing_delay_LED
        self.trigger_LED.ns_delay.put(self.timing_LED)

    def set_timing_zero_nozzle(self, nozzle, timing_rel):
        """
        Set the time-zero delay for a nozzle based on LED alignment.

        Sets the absolute reference delay for the specified nozzle as measured
        from the LED alignment procedure, then calls :meth:`set_timing_update`
        to apply the change.

        Parameters
        ----------
        nozzle : int
            Nozzle number to configure. Must be ``1`` or ``2``.
        timing_rel : float
            Relative delay in nanoseconds from the robot LED alignment.

        Returns
        -------
        None

        Raises
        ------
        ValueError
            Prints a warning if an invalid nozzle number is provided.

        Examples
        --------
        Set time zero for nozzle 1 based on alignment result:

        >>> dod.set_timing_zero_nozzle(1, 12500.0)
        """
        if nozzle == 1:
            self.timing_delay_nozzle_1 = timing_rel
        elif nozzle == 2:
            self.timing_delay_nozzle_2 = timing_rel
        else:
            print("no valid nozzle selected.")
            return

        # Update timings
        self.set_timing_update()

    def set_timing_rel_LED(self, timing_rel):
        """
        Set the relative timing of the LED with respect to the X-rays.

        Updates ``timing_delay_LED`` and calls :meth:`set_timing_update` to
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

        >>> dod.set_timing_rel_LED(1000.0)
        """
        self.timing_delay_LED = timing_rel

        # Update timings
        self.set_timing_update()

    def set_timing_rel_reaction(self, timing_rel):
        """
        Set the relative reaction delay with respect to the X-rays.

        Updates ``timing_delay_reaction`` and calls :meth:`set_timing_update`
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

        >>> dod.set_timing_rel_reaction(5000.0)
        """
        self.timing_delay_reaction = timing_rel

        # Update timings
        self.set_timing_update()

    def set_timing_abs_Xray(self, timing_abs):
        """
        Set the absolute X-ray timing used for nozzle delay calculations.

        Updates the stored X-ray timing reference and calls
        :meth:`set_timing_update` to recalculate and apply all dependent
        trigger delays. Does not directly write to the X-ray trigger PV.

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

        >>> dod.set_timing_abs_Xray(700000.0)
        """
        self.timing_Xray = timing_abs

        # Update timings
        self.set_timing_update()

    def set_timing_relative_nozzle(self, nozzle, timing_rel):
        """
        Adjust the timing of a nozzle by a relative offset.

        Increments the current delay of the specified nozzle by ``timing_rel``
        and calls :meth:`set_timing_update` to apply the change.

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
            Prints a warning if an invalid nozzle number is provided.

        Examples
        --------
        Advance nozzle 1 by 500 ns:

        >>> dod.set_timing_relative_nozzle(1, 500.0)

        Delay nozzle 2 by 200 ns:

        >>> dod.set_timing_relative_nozzle(2, -200.0)
        """
        if nozzle == 1:
            current_timing = self.timing_delay_nozzle_1
            self.timing_delay_nozzle_1 = self.timing_delay_nozzle_1 + timing_rel
        elif nozzle == 2:
            current_timing = self.timing_delay_nozzle_2
            self.timing_delay_nozzle_2 = self.timing_delay_nozzle_2 + timing_rel
        else:
            print("no valid nozzle selected.")
            return

        # Update timings
        self.set_timing_update()

    def logging_string(self):
        """
        Generate a formatted string for posting to the e-log.

        Collects the current CoDI position and all timing parameters and
        formats them into a human-readable string suitable for logging.

        Returns
        -------
        str
            Multi-line string containing CoDI position data and timing
            parameter values.

        Raises
        ------
        AttributeError
            If the ``codi`` module is not loaded (i.e. ``modules`` was not set
            to ``'codi'`` at initialisation).

        Examples
        --------
        Post current state to the e-log:

        >>> log_entry = dod.logging_string()
        >>> print(log_entry)
        """
        post_str = ""

        # Nozzle angles:
        position = self.codi.get_CoDI_pos()
        position_str = (
            "Codi Information: \n CoDI data: name: "
            + str(position[0])
            + "\n rot_base: "
            + str(position[1])
            + "\n rot_left: "
            + str(position[2])
            + "\n rot_right: "
            + str(position[3])
            + "\n z-transl: "
            + str(position[4])
        )
        post_str = post_str + position_str + " \n "

        # Timings:
        post_str = post_str + "Timing:" + " \n "
        post_str = post_str + "timing_Xray:" + str(self.timing_Xray) + " \n "
        post_str = post_str + "timing_nozzle_1:" + str(self.timing_nozzle_1) + " \n "
        post_str = post_str + "timing_nozzle_2:" + str(self.timing_nozzle_2) + " \n "
        post_str = post_str + "timing_LED:" + str(self.timing_LED) + " \n "
        post_str = post_str + "timing_delay_LED:" + str(self.timing_delay_LED) + " \n "
        post_str = (
            post_str
            + "timing_delay_reaction:"
            + str(self.timing_delay_reaction)
            + " \n "
        )
        post_str = (
            post_str
            + "timing_delay_nozzle_1:"
            + str(self.timing_delay_nozzle_1)
            + " \n "
        )
        post_str = (
            post_str
            + "timing_delay_nozzle_2:"
            + str(self.timing_delay_nozzle_2)
            + " \n "
        )

        return post_str
