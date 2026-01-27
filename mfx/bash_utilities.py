"""Bash utility wrappers for MFX beamline operations."""

import os
import sys
import subprocess
import logging
import re
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)


class BashUtilities:
    """
    Collection of bash utility wrappers for MFX beamline.

    Provides Python interfaces to common bash scripts and external
    tools used at MFX, including:
    - CCTBX XFEL GUI
    - DAQ control and restart
    - Pedestal generation and processing
    - Camera viewing and control
    - System diagnostics
    - External tool launching

    Methods
    -------
    xfel_gui() : None
        Launch CCTBX XFEL GUI with current experiment
    takepeds(daq_num) : None
        Acquire pedestal data
    makepeds(username, run_number, onshift, daq_num, det) : None
        Process pedestal data
    restartdaq(daq_num) : None
        Restart DAQ system
    stopdaq(daq_num) : None
        Stop DAQ system
    lecroy(res) : None
        Open LeCroy oscilloscope remote desktop
    grabber() : None
        Launch elog grabber utility
    cleanup_shm() : None
        Clean up shared memory segments
    cameras() : None
        Launch camera viewer
    _camera_list_out() : List[List[str]]
        Get list of available cameras
    camera_list() : None
        Print formatted camera list
    focus_scan(run_number, username) : None
        Analyze focus scan data
    startami(ami_num, daq_num) : None
        Start AMI monitoring interface

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

    View cameras:
    >>> bs.camera_list()
    >>> bs.cameras()

    See Also
    --------
    bash_utilities_old : Legacy deprecated version
    """

    def xfel_gui(self):
        """
        Launch CCTBX XFEL GUI with current experiment configuration.

        Automatically updates XFEL GUI settings file with current
        experiment name before launching GUI. Ensures GUI is configured
        for the active experiment.

        Returns
        -------
        None

        Notes
        -----
        Configuration File:
        - Location: /cds/home/opr/mfxopr/.cctbx.xfel/settings.phil
        - Backup: settings_old.phil
        - Auto-updated with current experiment

        Settings Updated:
        - name: Experiment name (line 10)
        - user: Experiment user (line 11)
        - Both set to current experiment

        CCTBX XFEL GUI:
        - Real-time data monitoring
        - Hit finding visualization
        - Indexing statistics
        - Geometry refinement tools
        - Integration monitoring

        Launch Method:
        - Sources CCTBX conda environment
        - Launches in background
        - GUI appears in separate window
        - Console output suppressed

        Requirements:
        - CCTBX installed at /reg/g/cctbx/brewster/
        - Valid experiment active
        - X11 forwarding (for remote)

        Typical Use:
        - Start of experiment
        - Monitor data quality
        - Real-time hit finding
        - Geometry refinement

        Examples
        --------
        >>> bs = BashUtilities()
        >>> bs.xfel_gui()

        Check settings before launch:
        >>> from mfx.macros import get_exp
        >>> print(f"Current experiment: {get_exp()}")
        >>> bs.xfel_gui()

        See Also
        --------
        cctbx : CCTBX integration module
        om : OnDA monitoring
        """
        from mfx.macros import get_exp

        logger.info("Checking XFEL GUI configuration")

        try:
            # Read current settings
            with open(
                "/cds/home/opr/mfxopr/.cctbx.xfel/settings_old.phil",
                "r",
                encoding="UTF-8"
            ) as f:
                setting_lines = f.readlines()

            change = False
            current_exp = get_exp()

            # Check and update experiment name (line 10)
            expected_name = f'  name = "{current_exp}"\n'
            if setting_lines[10] != expected_name:
                logger.warning(f"Updating experiment to: {current_exp}")
                setting_lines[10] = expected_name
                change = True

            # Check and update user (line 11)
            expected_user = f'  user = "{current_exp}"\n'
            if setting_lines[11] != expected_user:
                logger.warning(f"Updating user to: {current_exp}")
                setting_lines[11] = expected_user
                change = True

            # Write updates if needed
            if change:
                # Update main settings
                with open(
                    "/cds/home/opr/mfxopr/.cctbx.xfel/settings.phil",
                    "w",
                    encoding="UTF-8"
                ) as f:
                    f.writelines(setting_lines)

                # Update backup
                with open(
                    "/cds/home/opr/mfxopr/.cctbx.xfel/settings_old.phil",
                    "w",
                    encoding="UTF-8"
                ) as f:
                    f.writelines(setting_lines)

                logger.info("Settings updated successfully")
            else:
                logger.info("Settings already current")

            # Launch GUI
            logger.info("Launching CCTBX XFEL GUI")
            subprocess.Popen(
                [
                    ". /reg/g/cctbx/brewster/working/build/conda_setpaths.sh;"
                    "cctbx.xfel &"
                ],
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT
            )
            logger.info("XFEL GUI launched successfully")

        except FileNotFoundError as e:
            logger.error(f"Settings file not found: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to launch XFEL GUI: {e}")
            raise

    def takepeds(self, daq_num: int = 2):
        """
        Acquire pedestal data for detectors.

        Runs data acquisition in pedestal mode to collect dark frames
        for noise characterization. Required for detector calibration.

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
        Pedestal Collection:

        Purpose:
        - Measure detector dark noise
        - Characterize pixel-by-pixel offsets
        - Establish baseline for subtraction
        - Required before experiments

        Process:
        1. Close X-ray shutter
        2. Collect ~1000 dark frames
        3. Calculate mean and std per pixel
        4. Store pedestal arrays

        DAQ Versions:

        DAQ 1 (LCLS-I):
        - Script: takepeds1.sh
        - Legacy system
        - Older format

        DAQ 2 (LCLS-II):
        - Script: takepeds
        - Current system
        - HDF5 format

        Typical Duration:
        - 1-2 minutes
        - ~1000 frames @ 120 Hz
        - Automatic completion

        Output:
        - Pedestal run recorded
        - Run number displayed
        - Ready for processing

        Next Steps:
        1. Note run number
        2. Run makepeds() to process
        3. Verify pedestal quality

        When to Take:
        - Start of experiment
        - After detector changes
        - After temperature changes
        - Daily for stability

        Examples
        --------
        Take pedestals with DAQ2:
        >>> bs = BashUtilities()
        >>> bs.takepeds(daq_num=2)

        Take pedestals with DAQ1:
        >>> bs.takepeds(daq_num=1)

        See Also
        --------
        makepeds : Process pedestal data
        """
        if daq_num not in [1, 2]:
            logger.error("daq_num must be 1 (LCLS-I) or 2 (LCLS-II)")
            raise ValueError("Invalid daq_num")

        logger.info(f"Taking pedestals with DAQ{daq_num}")

        if daq_num == 1:
            script = "/cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/takepeds1.sh"
        else:  # daq_num == 2
            script = "/reg/g/pcds/engineering_tools/mfx/scripts/takepeds"

        logger.info(f"Executing: {script}")
        os.system(script)
        logger.info("Pedestal acquisition complete")

    def makepeds(
            self,
            username: str,
            run_number: Optional[int] = None,
            onshift: bool = False,
            daq_num: int = 2,
            det: str = 'all'):
        """
        Process pedestal data to generate calibration constants.

        Submits batch job to analyze pedestal run and generate
        pixel-by-pixel dark calibration arrays.

        Parameters
        ----------
        username : str
            Username for SLURM batch job submission
            Must have write access to calibration directory
        run_number : int or None, optional
            Pedestal run number to process
            If None, uses most recent run (default: None)
        onshift : bool, optional
            Use LCLS onshift SLURM reservation (default: False)
            Ensures faster processing during beam time
        daq_num : int, optional
            DAQ version: 1 or 2 (default: 2)
        det : str, optional
            Detector to process: 'all', 'epix', 'rayonix' (default: 'all')
            Currently only 'all' supported

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
        Pedestal Processing:

        Input:
        - Raw pedestal run (dark frames)
        - Typically 1000-10000 images

        Processing:
        - Calculate mean per pixel (offset)
        - Calculate std per pixel (noise)
        - Identify hot/dead pixels
        - Generate calibration arrays

        Output:
        - Pedestal file (.npy or .h5)
        - Stored in calibration directory
        - Automatically used by DAQ

        SLURM Submission:
        - Batch queue: milano
        - Runtime: ~5-30 minutes
        - Check status: squeue -u $USER

        Reservations:

        onshift=False:
        - Standard queue
        - May wait for resources
        - Good for offline processing

        onshift=True:
        - Priority reservation
        - Faster queue access
        - Use during beam time
        - Requires onshift allocation

        DAQ Control (DAQ2 only):
        - Returns DAQ to safe state
        - Sets to "configured"
        - Disables recording
        - Ready for next run

        Calibration Directory:
        - DAQ1: /reg/d/pscdata/mfx/{exp}/calib/
        - DAQ2: /cds/data/psdm/mfx/{exp}/calib/

        Verification:
        - Check job completion
        - Verify files created
        - Test in next data run
        - Compare noise levels

        Examples
        --------
        Process most recent pedestals:
        >>> bs = BashUtilities()
        >>> bs.makepeds('myuser', onshift=True, daq_num=2)

        Process specific run:
        >>> bs.makepeds('myuser', run_number=123, daq_num=2)

        Offline processing:
        >>> bs.makepeds('myuser', run_number=123, onshift=False)

        With DAQ1:
        >>> bs.makepeds('myuser', run_number=123, daq_num=1)

        See Also
        --------
        takepeds : Acquire pedestal data
        """
        from mfx.db import daq
        from mfx.macros import get_run

        # Validate DAQ number
        if daq_num not in [1, 2]:
            logger.error("daq_num must be 1 (LCLS-I) or 2 (LCLS-II)")
            raise ValueError("Invalid daq_num")

        logger.info(f"Processing pedestals with DAQ{daq_num}")

        # Determine station
        station = 1 if daq_num == 1 else 0

        # Get run number if not provided
        if run_number is None:
            try:
                run_number = get_run(station=station)
                logger.info(f"Using most recent run: {run_number}")
            except NameError as e:
                logger.error(
                    "Could not determine run number automatically. "
                    f"Please specify: makepeds('{username}', run_number=XXX)"
                )
                raise

        # Convert to strings for command
        username = str(username)
        run_number = str(int(run_number))

        # Build command based on DAQ version
        if daq_num == 1:
            script = "/cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/makepeds1.sh"
            base_cmd = f"{script} -q milano -r {run_number} -u {username}"
        else:  # daq_num == 2
            script = "/reg/g/pcds/engineering_tools/mfx/scripts/makepeds"
            base_cmd = f"{script} -q milano -r {run_number} -u {username}"

        # Add reservation if requested
        if onshift:
            cmd = f"{base_cmd} --reservation lcls:onshift"
            logger.info("Using onshift reservation for faster processing")
        else:
            cmd = base_cmd

        logger.info(f"Executing: {cmd}")
        os.system(cmd)

        # DAQ2-specific cleanup
        if daq_num == 2:
            logger.info("Returning DAQ2 to safe state")
            try:
                from psdaq.control.DaqControl import DaqControl

                daq.control = DaqControl(
                    host=daq.control.host,
                    platform=daq.control.platform,
                    timeout=10000
                )

                instr = daq.control.getInstrument()
                if instr is None:
                    logger.warning("Failed to connect to DAQ for cleanup")
                    return

                start_state = daq.control.getState()
                if start_state == 'error':
                    logger.warning("DA is in error state")
                    return

                # Return to safe state
                daq.control.setState("configured")
                while daq.control.getState() != "configured":
                    pass

                daq.control.setRecord(False)
                daq.control.setState("running")

                logger.info("DAQ returned to configured state")

            except Exception as e:
                logger.warning(f"DAQ cleanup failed: {e}")

        logger.info(
            f"Pedestal processing submitted for run {run_number}\n"
            f"Check status with: squeue -u {username}\n"
            f"Results will be in calibration directory when complete"
        )

    def restartdaq(self, daq_num: int = 2):
        """
        Restart DAQ system.

        Completely restarts the data acquisition system. Use when
        DAQ is unresponsive or after configuration changes.

        Parameters
        ----------
        daq_num : int, optional
            DAQ version: 1 or 2 (default: 2)

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If daq_num not in [1, 2]

        Notes
        -----
        Restart Process:

        DAQ1:
        - Uses procmgr to restart
        - Reads configuration from mfx.cnf
        - Restarts all DAQ processes
        - Takes ~1-2 minutes

        DAQ2:
        - Runs restartdaq script
        - Restarts control processes
        - Reconnects to hardware
        - Takes ~30-60 seconds

        When to Restart:
        - DAQ frozen/unresponsive
        - After detector changes
        - After configuration updates
        - Connection errors
        - State machine stuck

        Caution:
        - Interrupts current run
        - Requires reconnection
        - May need reconfiguration
        - Check status before restarting

        After Restart:
        - Wait for completion
        - Reconnect DAQ in Python
        - Verify detector connections
        - Test with short run

        Examples
        --------
        Restart DAQ2:
        >>> bs = BashUtilities()
        >>> bs.restartdaq(daq_num=2)

        Restart DAQ1:
        >>> bs.restartdaq(daq_num=1)

        See Also
        --------
        stopdaq : Stop DAQ without restart
        """
        if daq_num not in [1, 2]:
            logger.error("daq_num must be 1 (LCLS-I) or 2 (LCLS-II)")
            raise ValueError("Invalid daq_num")

        logger.info(f"Restarting DAQ{daq_num}")
        logger.warning("This will interrupt any current run")

        if daq_num == 1:
            cmd = (
                "/cds/group/pcds/dist/pds/mfx/current/tools/procmgr/procmgr "
                "restart /cds/group/pcds/dist/pds/mfx/scripts/mfx.cnf"
            )
        else:  # daq_num == 2
            cmd = "/reg/g/pcds/engineering_tools/mfx/scripts/restartdaq"

        logger.info(f"Executing: {cmd}")
        subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT
        )

        logger.info(
            "DAQ restart initiated. "
            "Wait 1-2 minutes before reconnecting."
        )

    def stopdaq(self, daq_num: int = 2):
        """
        Stop DAQ system.

        Stops data acquisition system without restarting.
        Use when you need to halt DAQ processes.

        Parameters
        ----------
        daq_num : int, optional
            DAQ version: 1 or 2 (default: 2)

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If daq_num not in [1, 2]

        Notes
        -----
        Stop Process:
        - Halts all DAQ processes
        - Closes detector connections
        - Stops data recording
        - Does not restart

        When to Stop:
        - End of shift
        - Emergency stop
        - Before maintenance
        - System troubleshooting

        After Stopping:
        - DAQ processes terminated
        - Manual restart required
        - Use restartdaq() to resume

        Examples
        --------
        >>> bs = BashUtilities()
        >>> bs.stopdaq(daq_num=2)

        See Also
        --------
        restartdaq : Restart DAQ
        """
        if daq_num not in [1, 2]:
            logger.error("daq_num must be 1 (LCLS-I) or 2 (LCLS-II)")
            raise ValueError("Invalid daq_num")

        logger.info(f"Stopping DAQ{daq_num}")

        if daq_num == 1:
            cmd = (
                "/cds/group/pcds/dist/pds/mfx/current/tools/procmgr/procmgr "
                "stop /cds/group/pcds/dist/pds/mfx/scripts/mfx.cnf"
            )
        else:  # daq_num == 2
            cmd = "/reg/g/pcds/engineering_tools/mfx/scripts/stopdaq"

        logger.info(f"Executing: {cmd}")
        subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT
        )

        logger.info("DAQ stop initiated")

    def lecroy(self, res: str = '2560x1440'):
        """
        Open LeCroy oscilloscope remote desktop.

        Launches remote desktop connection to fast oscilloscope
        for laser timing diagnostics.

        Parameters
        ----------
        res : str, optional
            Screen resolution (default: '2560x1440')
            Common: '1920x1080', '2560x1440', '3840x2160'

        Returns
        -------
        None

        Notes
        -----
        LeCroy Oscilloscope:
        - Fast digital oscilloscope
        - Used for timing diagnostics
        - Laser pulse characterization
        - Trigger signal monitoring

        Connection:
        - Uses xfreerdp (RDP client)
        - Credentials: lecroyuser / pcds
        - Host: scope-ics-mfx-lecroy01

        Resolution:
        - Set to match your monitor
        - Higher res = more detail
        - May affect performance

        Use Cases:
        - Check laser timing
        - Verify trigger signals
        - Diagnose timing jitter
        - Measure pulse widths

        Examples
        --------
        Standard resolution:
        >>> bs = BashUtilities()
        >>> bs.lecroy()

        4K resolution:
        >>> bs.lecroy(res='3840x2160')

        See Also
        --------
        timetool : Time tool utilities
        """
        logger.info(f"Opening LeCroy oscilloscope (resolution: {res})")

        cmd = (
            f"xfreerdp -g {res} "
            f"-u lecroyuser -p pcds "
            f"scope-ics-mfx-lecroy01"
        )

        subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT
        )

        logger.info("LeCroy RDP session launched")

    def grabber(self):
        """
        Launch elog grabber utility.

        Opens tool for capturing screenshots and annotations
        to the electronic logbook (elog).

        Returns
        -------
        None

        Notes
        -----
        Elog Grabber:
        - Screenshot capture tool
        - Annotation capabilities
        - Direct elog posting
        - Image manipulation

        Features:
        - Select screen region
        - Add text annotations
        - Draw arrows/shapes
        - Crop and resize
        - Post to elog automatically

        Typical Use:
        - Document detector images
        - Capture plots/graphs
        - Record equipment settings
        - Log unusual events
        - Share results with team

        Examples
        --------
        >>> bs = BashUtilities()
        >>> bs.grabber()

        See Also
        --------
        autorun.post : Post run info to elog
        """
        logger.info("Opening elog grabber")

        cmd = "/reg/g/pcds/engineering_tools/mfx/scripts/eloggrabber"

        subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT
        )

        logger.info("Elog grabber launched")

    def cleanup_shm(self):
        """
        Clean up shared memory segments.

        Removes stale shared memory segments that can accumulate
        from crashed processes. Helps prevent memory leaks.

        Returns
        -------
        None

        Notes
        -----
        Shared Memory:
        - Used for inter-process communication
        - Can persist after process crash
        - Accumulates over time
        - Causes memory exhaustion

        Cleanup Process:
        - Identifies orphaned segments
        - Removes stale entries
        - Frees memory
        - Safe to run anytime

        When to Clean:
        - After DAQ crashes
        - Memory warnings
        - Periodic maintenance
        - Sluggish performance

        Safety:
        - Only removes orphaned segments
        - Active segments preserved
        - No data loss risk

        Examples
        --------
        >>> bs = BashUtilities()
        >>> bs.cleanup_shm()

        See Also
        --------
        restartdaq : May need cleanup after restart
        """
        logger.info("Cleaning up shared memory")

        cmd = "/reg/g/pcds/engineering_tools/mfx/scripts/cleanupshm"

        os.system(cmd)

        logger.info("Shared memory cleanup complete")

    def cameras(self, pro=False):
        """
        Launch camera viewer GUI.

        Opens graphical interface to view all MFX beamline cameras
        simultaneously.

        Returns
        -------
        None

        Notes
        -----
        Camera Viewer:
        - Multi-camera display
        - Real-time video feeds
        - Pan/zoom controls
        - Snapshot capability

        Available Cameras:
        - Diagnostic cameras
        - Sample viewing
        - Alignment cameras
        - Beam position monitors

        Features:
        - Grid or tabbed layout
        - Individual camera control
        - Exposure adjustment
        - ROI selection
        - Recording capability

        Use Cases:
        - Sample alignment
        - Beam verification
        - Diagnostic monitoring
        - Documentation

        Examples
        --------
        >>> bs = BashUtilities()
        >>> bs.cameras()

        See Also
        --------
        camera_list : List available cameras
        _camera_list_out : Get camera info programmatically
        """
        logger.info("Launching camera viewer")

        if pro:
            cmd = 'bash /cds/home/opr/mfxopr/camViewerPro.sh'
        else:
            cmd = "/reg/g/pcds/engineering_tools/latest-released/scripts/camViewer"

        subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT
        )

        logger.info("Camera viewer launched")

    def camera_list_out(self):
        """
        Get list of available cameras as structured data.

        Returns detailed information about all MFX cameras
        in a format suitable for programmatic use.

        Returns
        -------
        List[List[str]]
            List of camera entries, each containing:
            [name, PV_base, description, ...]
        """
        logging.info("Opening Camera List")
        camlist = open("/reg/g/pcds/pyps/config/mfx/camviewer.cfg", "r", encoding="UTF-8")
        cam_list = camlist.readlines()
        avail_cams = [cam for cam in cam_list if cam.startswith('GE')]
        self.camera_names = [['camera_name', 'camera_pv']]
        print("Available Cameras")
        for cam in avail_cams:
            cam = re.split(';|,', cam)
            self.camera_names.append([cam[4].strip(),cam[2]])
            print(f"Camera {cam[4].strip()} ....  {cam[2]}")

        return self.camera_names


    def camera_list(self):
        """
        Print formatted list of available cameras.

        Displays human-readable table of all MFX cameras with
        names, locations, and descriptions.
        """
        camera_names = self.camera_list_out()


    def focus_scan(self, camera, record=False, daq_num=2):
        logging.info(
            "Preparing for Focus Scan\n"
            "Please check the following\n"
            "One of the following cameras is selected\n\n")
        self.camera_list()
        logging.info(
            "\nCamera orientation set to none\n"
            "Slits are open\n"
            "Blue crosshair in upper left corner\n"
            "Red crosshair in bottom right corner\n")

        input("Press Enter to continue...")

        if camera not in [pv[1] for pv in self.camera_names]:
            logging.error("Desired Camera not in List. Please double check camera name.")

        logging.info("Checking Focus Scan Plot")
        os.system(f"python /reg/g/pcds/pyps/apps/hutch-python/mfx/scripts/focus_scan.py {camera} -p")
        input("Press Enter to continue...")

        logging.info("Running Focus Scan")
        if record:
            logging.info("Recording Focus Scan")
            cmd = f"python /reg/g/pcds/pyps/apps/hutch-python/mfx/scripts/focus_scan.py {camera} -s -r -d {daq_num}"
        else:
            cmd = f"python /reg/g/pcds/pyps/apps/hutch-python/mfx/scripts/focus_scan.py {camera} -s"

        logging.info(cmd)
        os.system(cmd)

        tfs_position = input(
            "Please enter your desired z-position for the TFS from the plot provided as an interger between 1 and 299: ")

        if 0 < int(tfs_position) < 300:
            logging.info(f"Moving TFS to {tfs_position}")
            os.system(f'caput MFX:TFS:MMS:21.VAL {tfs_position}')
        else:
            logging.error(f"{tfs_position} is not a valid position please use an interger between 1 and 299")

    def startami(self, ami_num: int = 1, daq_num: int = 1):
        """
        Start AMI (Analysis and Monitoring Interface).

        Launches real-time data analysis and monitoring GUI
        for online data visualization during experiments.

        Parameters
        ----------
        ami_num : int, optional
            AMI instance: 1 or 2 (default: 1)
            Multiple instances for different analyses
        daq_num : int, optional
            DAQ version: 1 or 2 (default: 1)
            Note: AMI mainly used with DAQ1

        Returns
        -------
        None

        Notes
        -----
        AMI (Analysis and Monitoring Interface):
        - Real-time data visualization
        - Online analysis plots
        - Detector image display
        - Waveform monitoring
        - Custom calculations

        Features:
        - Drag-and-drop plot creation
        - Python scripting interface
        - Correlation plots
        - Histogramming
        - Event filtering
        - Data export

        AMI Instances:

        AMI 1:
        - Primary instance
        - Standard plots
        - General monitoring
        - Note: DAQ1/AMI1 currently disabled

        AMI 2:
        - Secondary instance
        - Custom analyses
        - Specialized plots
        - Independent from AMI1

        DAQ Compatibility:

        DAQ1:
        - Native AMI support
        - Full functionality
        - Recommended

        DAQ2:
        - Limited AMI support
        - Use alternative tools
        - Transitioning to new system

        Use Cases:
        - Monitor detector signals
        - Track experimental parameters
        - Real-time data quality
        - Correlation analysis
        - Troubleshooting

        Limitations:
        - DAQ1/AMI1 currently not working
        - Use AMI2 with DAQ1
        - DAQ2 has limited AMI support

        Examples
        --------
        Start AMI2 with DAQ1:
        >>> bs = BashUtilities()
        >>> bs.startami(ami_num=2, daq_num=1)

        Start AMI with DAQ2:
        >>> bs.startami(daq_num=2)

        See Also
        --------
        restartdaq : Restart DAQ for AMI
        """
        logger.info(f"Starting AMI{ami_num} with DAQ{daq_num}")

        if daq_num == 1:
            if ami_num == 1:
                logger.error(
                    "DAQ1/AMI1 combination currently not working. "
                    "Please use AMI2 (ami_num=2)"
                )
                return
            elif ami_num == 2:
                cmd = "/reg/g/pcds/engineering_tools/mfx/scripts/startami2"
                logger.info("Starting AMI2 for DAQ1")
            else:
                logger.error("ami_num must be 1 or 2")
                return

        elif daq_num == 2:
            cmd = "/reg/g/pcds/engineering_tools/mfx/scripts/startami"
            logger.info("Starting AMI for DAQ2")

        else:
            logger.error("daq_num must be 1 or 2")
            return

        logger.info(f"Executing: {cmd}")
        os.system(cmd)

        logger.info("AMI launched")

    def coyote_gui(self, cfg: str = 'coyote', debug: bool = False):
        """
        Launch Coyote GUI with current experiment configuration.

        Returns
        -------
        None

        Notes
        -----
        GUI configuration File:
        - Location: /cds/group/pcds/epics-dev/zlentz/bsmtraj/cfg_assembly/coyote.toml

        Chip config folder:
        - Location: /cds/group/pcds/epics-dev/zlentz/bsmtraj/cfg_chip

        """

        # Launch GUI
        logger.info("Launching Coyote GUI")

        cmd = (
            f"source pcds_conda; "
            f"cd /cds/group/pcds/epics-dev/zlentz/bsmtraj; "
            f"python -m bsmtraj.gui {cfg}"
        )

        logger.warning(cmd)
        logger.warning(
            'GUI configuration File: '
            '/cds/group/pcds/epics-dev/zlentz/bsmtraj/cfg_assembly/coyote.toml')
        logger.warning(
            'Chip config folder: '
            '/cds/group/pcds/epics-dev/zlentz/bsmtraj/cfg_chip')

        if debug:
            os.system(cmd)

        else:
            subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT
            )
        logger.info("Coyote GUI launched successfully")

# Convenience instance for direct import
bs = BashUtilities()


# Convenience functions

def xfel_gui():
    """Launch CCTBX XFEL GUI. See BashUtilities.xfel_gui()."""
    bs.xfel_gui()


def takepeds(daq_num: int = 2):
    """Take pedestal data. See BashUtilities.takepeds()."""
    bs.takepeds(daq_num=daq_num)


def makepeds(
        username: str,
        run_number: Optional[int] = None,
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


def cameras():
    """Launch camera viewer. See BashUtilities.cameras()."""
    bs.cameras()


def camera_list():
    """Print camera list. See BashUtilities.camera_list()."""
    bs.camera_list()


def focus_scan(camera: str, record: bool = False, daq_num: int = 2):
    """Run focus scan. See BashUtilities.focus_scan()."""
    bs.focus_scan(camera=camera, record=record, daq_num=daq_num)


def startami(ami_num: int = 1, daq_num: int = 1):
    """Start AMI. See BashUtilities.startami()."""
    bs.startami(ami_num=ami_num, daq_num=daq_num)

# Module initialization
logger.info("Bash utilities loaded and ready")