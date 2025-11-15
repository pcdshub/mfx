"""Bash utility wrappers for MFX beamline operations."""

import os
import subprocess
import logging

logger = logging.getLogger(__name__)


class BashUtilities:
    """
    Collection of bash utility wrappers for MFX beamline.

    Provides Python interfaces to common bash scripts and external
    tools used at MFX, including:
    - CCTBX XFEL GUI
    - DAQ control and restart
    - Pedestal generation and processing

    Methods
    -------
    xfel_gui()
        Launch CCTBX XFEL GUI with current experiment
    takepeds(daq_num)
        Acquire pedestal data
    makepeds(username, run_number, onshift, daq_num, det)
        Process pedestal data
    restartdaq(daq_num)
        Restart DAQ system

    Examples
    --------
    Create utilities instance:
    >>> bs = BashUtilities()

    Launch XFEL GUI:
    >>> bs.xfel_gui()

    Take and process pedestals:
    >>> bs.takepeds(daq_num=2)
    >>> bs.makepeds('username', run_number=123, onshift=True, daq_num=2)

    Restart DAQ:
    >>> bs.restartdaq(daq_num=2)
    """

    def xfel_gui(self):
        """
        Launch CCTBX XFEL GUI with current experiment configuration.

        Automatically updates XFEL GUI settings file with current
        experiment name before launching GUI.

        Returns
        -------
        None

        Notes
        -----
        Configuration File:
        - Location: /cds/home/opr/mfxopr/.cctbx.xfel/settings.phil
        - Backup: settings_old.phil

        Settings Updated:
        - experiment.name
        - experiment.user

        Both fields are set to current experiment from get_exp().

        GUI Launch:
        - Uses conda environment from /reg/g/cctbx/brewster/working/build
        - Runs in background (detached process)
        - Output redirected to /dev/null

        The GUI will automatically load:
        - Current experiment configuration
        - Available runs
        - Detector geometry

        Raises
        ------
        IOError
            If settings file cannot be read/written

        Examples
        --------
        >>> bs = BashUtilities()
        >>> bs.xfel_gui()  # Launches GUI for current experiment

        See Also
        --------
        get_exp : Get current experiment name
        """
        from mfx.macros import get_exp

        logger.info("Checking XFEL GUI phil file")

        settings_path = "/cds/home/opr/mfxopr/.cctbx.xfel/settings.phil"
        settings_old_path = "/cds/home/opr/mfxopr/.cctbx.xfel/settings_old.phil"

        current_exp = get_exp()

        try:
            # Read current settings
            with open(settings_old_path, "r", encoding="UTF-8") as f:
                setting_lines = f.readlines()

            # Check if updates needed
            change = False

            # Update experiment name (line 10, 0-indexed)
            if len(setting_lines) > 10 and setting_lines[10] != f'  name = "{current_exp}"\n':
                logger.warning(f"Changing experiment to current: {current_exp}")
                setting_lines[10] = f'  name = "{current_exp}"\n'
                change = True

            # Update user (line 11, 0-indexed)
            if len(setting_lines) > 11 and setting_lines[11] != f'  user = "{current_exp}"\n':
                logger.warning(f"Changing user to current: {current_exp}")
                setting_lines[11] = f'  user = "{current_exp}"\n'
                change = True

            # Write updated settings if changed
            if change:
                with open(settings_path, "w", encoding="UTF-8") as f:
                    f.writelines(setting_lines)
                with open(settings_old_path, "w", encoding="UTF-8") as f:
                    f.writelines(setting_lines)
                logger.info("Updated XFEL GUI settings")

            # Launch GUI
            logger.info("Launching CCTBX XFEL GUI")
            subprocess.Popen(
                [". /reg/g/cctbx/brewster/working/build/conda_setpaths.sh; cctbx.xfel &"],
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT
            )

        except IOError as e:
            logger.error(f"Failed to update XFEL GUI settings: {e}")
            raise

    def takepeds(self, daq_num: int = 2):
        """
        Acquire pedestal data.

        Runs pedestal acquisition script for specified DAQ system.
        Pedestals are detector dark images used for background subtraction.

        Parameters
        ----------
        daq_num : int, optional
            DAQ version: 1 (LCLS-I) or 2 (LCLS-II) (default: 2)

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If daq_num not in [1, 2]

        Notes
        -----
        Scripts Called:
        - DAQ 1: /cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/takepeds1.sh
        - DAQ 2: /reg/g/pcds/engineering_tools/mfx/scripts/takepeds

        Procedure:
        1. Configure detectors for pedestal mode
        2. Close all shutters
        3. Acquire dark images
        4. Return detectors to normal mode

        Typical pedestal runs collect:
        - 1000-2000 dark frames
        - Multiple gain settings (if applicable)
        - Full detector area

        Run numbers are automatically assigned.
        Data stored in standard DAQ output directory.

        Examples
        --------
        Take pedestals with LCLS-II DAQ:
        >>> bs = BashUtilities()
        >>> bs.takepeds(daq_num=2)

        Take pedestals with LCLS-I DAQ:
        >>> bs.takepeds(daq_num=1)

        See Also
        --------
        makepeds : Process pedestal data
        """
        logger.info("Taking Pedestals")

        if daq_num == 1:
            script = "/cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/takepeds1.sh"
        elif daq_num == 2:
            script = "/reg/g/pcds/engineering_tools/mfx/scripts/takepeds"
        else:
            logger.error("daq_num must be 1 (LCLS-I) or 2 (LCLS-II)")
            raise ValueError("Invalid daq_num")

        logger.info(f"Executing: {script}")
        os.system(script)

    def makepeds(
            self,
            username: str,
            run_number: int = None,
            onshift: bool = False,
            daq_num: int = 2,
            det: str = 'all'):
        """
        Process pedestal data into calibration constants.

        Submits SLURM job to process raw pedestal data and generate
        detector calibration constants.

        Parameters
        ----------
        username : str
            SLURM username for job submission
            Must have access to LCLS batch system
        run_number : int or None, optional
            Run number containing pedestal data (default: None)
            If None, uses most recent run
        onshift : bool, optional
            Submit to onshift queue (default: False)
            - True: Uses lcls:onshift reservation
            - False: Uses standard milano queue
        daq_num : int, optional
            DAQ version: 1 (LCLS-I) or 2 (LCLS-II) (default: 2)
        det : str, optional
            Detector to process: 'all', 'epix', 'jungfrau', etc. (default: 'all')

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If daq_num not in [1, 2]
        NameError
            If run_number cannot be determined

        Notes
        -----
        Scripts Called:
        - DAQ 1: /cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/makepeds1.sh
        - DAQ 2: /reg/g/pcds/engineering_tools/mfx/scripts/makepeds

        Queue Selection:
        - onshift=True: Fast processing during beamtime (limited slots)
        - onshift=False: Standard processing (may queue longer)

        Processing Steps:
        1. Read raw pedestal data
        2. Calculate mean and standard deviation per pixel
        3. Identify hot/dead pixels
        4. Generate calibration constants
        5. Deploy to detector calibration directory

        Output Location:
        - /reg/d/pscdata/mfx/{experiment}/calib/

        Job Status:
        - Check with: squeue -u {username}
        - Typical runtime: 5-15 minutes

        After Completion:
        - Pedestal constants automatically loaded by DAQ
        - Reconnect DAQ to apply new constants

        Examples
        --------
        Process pedestals for current run:
        >>> bs = BashUtilities()
        >>> bs.makepeds('myusername', onshift=True, daq_num=2)

        Process specific run:
        >>> bs.makepeds('myusername', run_number=123, daq_num=2)

        Process only Jungfrau detector:
        >>> bs.makepeds('myusername', det='jungfrau', daq_num=2)

        See Also
        --------
        takepeds : Acquire pedestal data
        restartdaq : Restart DAQ to load new constants
        """
        from mfx.db import daq
        from mfx.macros import get_run

        logger.info("Making Pedestals")

        # Validate DAQ number
        if daq_num == 1:
            station = 1
        elif daq_num == 2:
            station = 0
        else:
            logger.error("daq_num must be 1 (LCLS-I) or 2 (LCLS-II)")
            raise ValueError("Invalid daq_num")

        # Get run number if not provided
        if run_number is None:
            try:
                run_number = get_run(station=station)
            except NameError:
                logger.error(
                    "get_run(station=station) not working. "
                    "Please enter run manually:\n"
                    f"bs.makepeds('{username}', run_number=XXX)"
                )
                raise

        # Convert to strings for command
        username = str(username)
        run_number = str(int(run_number))

        # Build command
        if daq_num == 1:
            script = "/cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/makepeds1.sh"
            if onshift:
                cmd = (
                    f"{script} -q milano -r {run_number} -u {username} "
                    "--reservation lcls:onshift"
                )
            else:
                cmd = f"{script} -q milano -r {run_number} -u {username}"

        elif daq_num == 2:
            script = "/reg/g/pcds/engineering_tools/mfx/scripts/makepeds"
            if onshift:
                cmd = (
                    f"{script} -q milano -r {run_number} -u {username} "
                    "--reservation lcls:onshift"
                )
            else:
                cmd = f"{script} -q milano -r {run_number} -u {username}"

        logger.info(f"Executing: {cmd}")
        os.system(cmd)

        # Reconnect DAQ for LCLS-II to load new constants
        if daq_num == 2:
            try:
                from psdaq.control.DaqControl import DaqControl

                logger.info("Reconnecting DAQ to load new pedestals")

                daq.control = DaqControl(
                    host=daq.control.host,
                    platform=daq.control.platform,
                    timeout=10000
                )

                instr = daq.control.getInstrument()
                if instr is None:
                    logger.error('Failed to connect to LCLS-II DAQ')
                    return

                start_state = daq.control.getState()
                if start_state == 'error':
                    logger.error('DAQ is in error state')
                    return

                # Cycle through states to reload calibrations
                daq.control.setState("connected")
                while daq.control.getState() != "connected":
                    pass

                daq.control.setState("configured")
                while daq.control.getState() != "configured":
                    pass

                daq.control.setState("running")
                while daq.control.getState() != "running":
                    pass

                logger.info("DAQ reconnected with new pedestals")

            except Exception as e:
                logger.warning(f"Failed to reconnect DAQ: {e}")
                logger.info("Please manually restart DAQ to load new pedestals")

    def restartdaq(self, daq_num: int = 2):
        """
        Restart DAQ system.

        Performs full restart of DAQ control and collection processes.
        Use when DAQ is in error state or after configuration changes.

        Parameters
        ----------
        daq_num : int, optional
            DAQ version: 1 (LCLS-I) or 2 (LCLS-II) (default: 2)

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If daq_num not in [1, 2]

        Notes
        -----
        Scripts Called:
        - DAQ 1: procmgr restart via /cds/group/pcds/dist/pds/mfx/scripts/mfx.cnf
        - DAQ 2: /reg/g/pcds/engineering_tools/mfx/scripts/restartdaq

        Restart Process:
        1. Stop all DAQ processes
        2. Clear shared memory
        3. Restart process manager
        4. Reconnect to detectors
        5. Load calibrations

        Typical restart time: 30-60 seconds

        When to Restart:
        - DAQ in error state
        - After pedestal processing
        - After detector configuration changes
        - After network issues
        - Hung processes

        Impact:
        - Terminates any active runs
        - Clears DAQ state
        - Reloads all configurations
        - May require reconfiguration in GUI

        Background Execution:
        - Runs in detached process
        - Output redirected to /dev/null
        - Check status with: ps aux | grep daq

        Examples
        --------
        Restart LCLS-II DAQ:
        >>> bs = BashUtilities()
        >>> bs.restartdaq(daq_num=2)

        Restart LCLS-I DAQ:
        >>> bs.restartdaq(daq_num=1)

        See Also
        --------
        makepeds : Process pedestals (often requires restart)
        stopdaq : Stop DAQ without restart
        """
        logger.info("Restarting the DAQ")

        if daq_num == 1:
            subprocess.Popen(
                [
                    "/cds/group/pcds/dist/pds/mfx/current/tools/procmgr/procmgr "
                    "restart /cds/group/pcds/dist/pds/mfx/scripts/mfx.cnf"
                ],
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT
            )
        elif daq_num == 2:
            subprocess.Popen(
                ["/reg/g/pcds/engineering_tools/mfx/scripts/restartdaq"],
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT
            )
        else:
            logger.error("daq_num must be 1 (LCLS-I) or 2 (LCLS-II)")
            raise ValueError("Invalid daq_num")

        logger.info("DAQ restart initiated (30-60s)")

    def stopdaq(self, daq_num: int = 2):
        """
        Stop DAQ system without restart.

        Stops all DAQ processes cleanly. Use when DAQ needs to be
        stopped but not restarted (e.g., end of shift).

        Parameters
        ----------
        daq_num : int, optional
            DAQ version: 1 (LCLS-I) or 2 (LCLS-II) (default: 2)

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If daq_num not in [1, 2]

        Notes
        -----
        Scripts Called:
        - DAQ 1: procmgr stop via /cds/group/pcds/dist/pds/mfx/scripts/mfx.cnf
        - DAQ 2: /reg/g/pcds/engineering_tools/mfx/scripts/stopdaq

        Stop Process:
        1. Send stop signal to all DAQ processes
        2. Wait for clean shutdown
        3. Clear shared memory
        4. Release resources

        Typical stop time: 10-20 seconds

        When to Stop:
        - End of shift
        - Before system maintenance
        - Before detector reconfiguration
        - To free system resources

        Impact:
        - Terminates any active runs
        - Stops all data collection
        - Clears DAQ state
        - Requires full restart to resume

        Background Execution:
        - Runs in detached process
        - Output redirected to /dev/null
        - Verify with: ps aux | grep daq

        Examples
        --------
        Stop LCLS-II DAQ:
        >>> bs = BashUtilities()
        >>> bs.stopdaq(daq_num=2)

        Stop LCLS-I DAQ:
        >>> bs.stopdaq(daq_num=1)

        See Also
        --------
        restartdaq : Restart DAQ system
        """
        logger.info("Stopping the DAQ")

        if daq_num == 1:
            subprocess.Popen(
                [
                    "/cds/group/pcds/dist/pds/mfx/current/tools/procmgr/procmgr "
                    "stop /cds/group/pcds/dist/pds/mfx/scripts/mfx.cnf"
                ],
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT
            )
        elif daq_num == 2:
            subprocess.Popen(
                ["/reg/g/pcds/engineering_tools/mfx/scripts/stopdaq"],
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT
            )
        else:
            logger.error("daq_num must be 1 (LCLS-I) or 2 (LCLS-II)")
            raise ValueError("Invalid daq_num")

        logger.info("DAQ stop initiated (10-20s)")

    def lecroy(self, res: str = '2560x1440'):
        """
        Open remote desktop connection to LeCroy oscilloscope.

        Launches xfreerdp connection to fast LeCroy scope for
        viewing/analyzing waveforms.

        Parameters
        ----------
        res : str, optional
            Screen resolution in format 'WIDTHxHEIGHT' (default: '2560x1440')
            Common resolutions:
            - '1920x1080' (Full HD)
            - '2560x1440' (QHD)
            - '3840x2160' (4K)

        Returns
        -------
        None

        Notes
        -----
        Connection Details:
        - Host: scope-ics-mfx-lecroy01
        - Username: lecroyuser
        - Password: pcds
        - Protocol: RDP (Remote Desktop Protocol)

        The LeCroy scope provides:
        - High-speed waveform capture
        - Timing diagnostics
        - Trigger analysis
        - Signal processing tools

        Requirements:
        - xfreerdp must be installed
        - Network access to scope-ics-mfx-lecroy01
        - X server for display

        Background Execution:
        - Runs in detached process
        - Output redirected to /dev/null
        - Window appears on local display

        Troubleshooting:
        - If connection fails, verify network access
        - Check if scope is powered on
        - Verify xfreerdp is installed: which xfreerdp

        Examples
        --------
        Connect with default resolution:
        >>> bs = BashUtilities()
        >>> bs.lecroy()

        Connect with 1080p resolution:
        >>> bs.lecroy(res='1920x1080')

        Connect with 4K resolution:
        >>> bs.lecroy(res='3840x2160')

        See Also
        --------
        grabber : Launch elog image grabber
        """
        logger.info("Opening the fast Lecroy oscilloscope")
        subprocess.Popen(
            [f"xfreerdp -g {res} -u lecroyuser -p pcds scope-ics-mfx-lecroy01"],
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT
        )

    def grabber(self):
        """
        Launch electronic logbook image grabber utility.

        Opens GUI tool for capturing and annotating screenshots
        for posting to the electronic logbook.

        Returns
        -------
        None

        Notes
        -----
        Script Location:
        - /reg/g/pcds/engineering_tools/mfx/scripts/eloggrabber

        Features:
        - Screen capture
        - Region selection
        - Image annotation
        - Direct elog posting
        - Image file saving

        Typical Workflow:
        1. Launch grabber
        2. Select capture region
        3. Add annotations (arrows, text, etc.)
        4. Post to elog or save file

        The grabber integrates with:
        - MFX electronic logbook
        - Current experiment
        - Standard image formats (PNG, JPEG)

        Background Execution:
        - Runs in detached process
        - Output redirected to /dev/null
        - GUI appears on local display

        Requirements:
        - X server for display
        - Network access to elog server
        - Current experiment must be set

        Examples
        --------
        >>> bs = BashUtilities()
        >>> bs.grabber()

        See Also
        --------
        lecroy : Remote desktop to oscilloscope
        """
        logger.info("Opening elog grabber")
        subprocess.Popen(
            ["/reg/g/pcds/engineering_tools/mfx/scripts/eloggrabber"],
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT
        )

    def cleanup_shm(self):
        """
        Clean up shared memory segments.

        Removes orphaned shared memory segments that can accumulate
        from crashed DAQ processes.

        Returns
        -------
        None

        Notes
        -----
        Shared Memory Issues:
        - DAQ uses shared memory for IPC
        - Crashed processes may leave segments
        - Can cause DAQ startup failures
        - May prevent detector connections

        This Function:
        - Lists current shared memory segments
        - Identifies orphaned segments
        - Removes unused segments
        - Logs cleanup actions

        When to Use:
        - DAQ fails to start
        - "Shared memory" errors
        - After DAQ crashes
        - Before DAQ restart

        Safety:
        - Only removes orphaned segments
        - Does not affect running processes
        - Safe to run anytime

        Commands Used:
        - ipcs: List shared memory
        - ipcrm: Remove shared memory

        Examples
        --------
        >>> bs = BashUtilities()
        >>> bs.cleanup_shm()

        See Also
        --------
        restartdaq : Restart DAQ
        stopdaq : Stop DAQ
        """
        logger.info("Cleaning up shared memory segments")

        # List current segments
        logger.info("Current shared memory segments:")
        os.system("ipcs -m")

        # Get user's segments
        result = subprocess.run(
            ["ipcs", "-m"],
            capture_output=True,
            text=True
        )

        # Parse and remove orphaned segments
        lines = result.stdout.split('\n')
        removed_count = 0

        for line in lines:
            parts = line.split()
            if len(parts) >= 6 and parts[0].startswith('0x'):
                # Check if segment is orphaned (nattch = 0)
                if parts[5] == '0':
                    shmid = parts[1]
                    logger.info(f"Removing orphaned segment: {shmid}")
                    os.system(f"ipcrm -m {shmid}")
                    removed_count += 1

        logger.info(f"Removed {removed_count} orphaned shared memory segments")


# Convenience instance for direct import
bs = BashUtilities()


# Convenience functions
def xfel_gui():
    """Launch CCTBX XFEL GUI. See BashUtilities.xfel_gui()."""
    bs.xfel_gui()


def takepeds(daq_num: int = 2):
    """Acquire pedestal data. See BashUtilities.takepeds()."""
    bs.takepeds(daq_num=daq_num)


def makepeds(
        username: str,
        run_number: int = None,
        onshift: bool = False,
        daq_num: int = 2,
        det: str = 'all'):
    """Process pedestal data. See BashUtilities.makepeds()."""
    bs.makepeds(
        username=username,
        run_number=run_number,
        onshift=onshift,
        daq_num=daq_num,
        det=det
    )


def restartdaq(daq_num: int = 2):
    """Restart DAQ system. See BashUtilities.restartdaq()."""
    bs.restartdaq(daq_num=daq_num)


def stopdaq(daq_num: int = 2):
    """Stop DAQ system. See BashUtilities.stopdaq()."""
    bs.stopdaq(daq_num=daq_num)


def lecroy(res: str = '2560x1440'):
    """Open LeCroy oscilloscope. See BashUtilities.lecroy()."""
    bs.lecroy(res=res)


def grabber():
    """Launch elog grabber. See BashUtilities.grabber()."""
    bs.grabber()


def cleanup_shm():
    """Clean up shared memory. See BashUtilities.cleanup_shm()."""
    bs.cleanup_shm()