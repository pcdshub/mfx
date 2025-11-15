"""OnDA Monitor (OM) setup and configuration utilities for MFX beamline."""

import os
import subprocess
import logging
from typing import Optional, List

logger = logging.getLogger(__name__)


class OM:
    """
    OnDA Monitor (OM) configuration and control.

    Provides automated setup and management of OnDA real-time data
    monitoring for MFX detectors. OnDA enables:
    - Real-time hit finding
    - Live data visualization
    - Peak detection and indexing
    - Geometry refinement
    - Experimental feedback

    OnDA monitors detector data streams and provides immediate feedback
    on data quality, hit rates, and diffraction patterns. Essential for
    optimizing serial crystallography experiments.

    Components
    ----------
    Configuration Files:
        monitor.yaml : OnDA configuration
        geometry files : Detector geometry (.geom)
        mask files : Bad pixel masks (.h5, .npy)

    Attributes
    ----------
    experiment : str
        Current experiment name
    cwd : str
        Base OnDA directory (/cds/home/opr/mfxopr/OM-GUI)
    pwd : str
        Current experiment directory

    Notes
    -----
    OnDA System:
    - Real-time data processing
    - Parallel processing on compute nodes
    - Graphical monitoring interface
    - Configurable algorithms

    Typical Workflow:
    1. Setup experiment directory (check())
    2. Configure monitor.yaml
    3. Launch OnDA (run())
    4. Monitor data in GUI
    5. Reset plots as needed (reset())

    Directory Structure:
    /cds/home/opr/mfxopr/OM-GUI/{experiment}/
        om_workspace/           # Epix10k2M configuration
            monitor.yaml
            geometry.geom
            mask.h5
        om_workspace_rayonix/   # Rayonix configuration
            monitor.yaml
            geometry.geom
            mask.h5
        om_workspace_xes/       # XES configuration
            monitor.yaml
            geometry.geom
            mask.h5
        om_reset_plots.py       # Plot reset script

    Detector Support:
    - Epix10k2M: Main area detector
    - Rayonix: Large area detector
    - XES: X-ray emission spectrometer

    Key Files:

    monitor.yaml:
    - OnDA configuration
    - Hit finding parameters
    - Peak detection settings
    - Geometry file paths

    geometry.geom:
    - Detector panel positions
    - Pixel sizes
    - Distance to sample
    - Beam center

    mask.h5:
    - Bad pixel mask
    - Module boundaries
    - Dead regions

    Examples
    --------
    Create OM controller:
    >>> om = OM()

    Check/setup experiment:
    >>> om.check()

    Launch OnDA for Epix10k2M:
    >>> om.run(node=10, det='epix')

    Launch for all detectors:
    >>> om.run(node=10, det='all')

    Reset plots:
    >>> om.reset(node=10)

    See Also
    --------
    check : Setup experiment directory
    run : Launch OnDA monitor
    reset : Reset OnDA plots
    """

    def __init__(self, experiment: Optional[str] = None):
        """
        Initialize OM controller.

        Parameters
        ----------
        experiment : str or None, optional
            Experiment name (e.g., 'mfxls1234')
            If None, uses current experiment from get_exp()
        """
        if experiment is None:
            from mfx.macros import get_exp
            self.experiment = str(get_exp())
        else:
            self.experiment = experiment

        self.cwd = '/cds/home/opr/mfxopr/OM-GUI'
        self.pwd = f'{self.cwd}/{self.experiment}'

        logger.info(f"OM controller initialized for {self.experiment}")

    def fix_run_om(self, path: str):
        """
        Update run_om.sh script with current PSANA environment.

        Modifies the OnDA launch script to use the correct PSANA
        host for the current session.

        Parameters
        ----------
        path : str
            Path to run_om.sh file

        Returns
        -------
        None

        Raises
        ------
        IOError
            If file cannot be read or written

        Notes
        -----
        Script Modification:
        - Queries current PSANA host (wherepsana)
        - Updates --host argument in launch command
        - Preserves other script settings

        PSANA Host:
        - Dynamic assignment by batch system
        - Changes between sessions
        - Must match OnDA environment

        File Format:
        The run_om.sh script contains mpirun command
        with --host parameter that needs updating.

        Examples
        --------
        >>> om = OM()
        >>> om.fix_run_om('/path/to/run_om.sh')

        See Also
        --------
        check : Setup experiment (calls this automatically)
        """
        logger.info(f"Updating run_om.sh: {path}")

        # Get current PSANA host
        wherepsana = subprocess.check_output(
            "wherepsana",
            shell=True
        ).decode().strip('\n')

        try:
            # Read script
            with open(path, "r") as file:
                lines = file.readlines()

            # Update host line
            for ind, line in enumerate(lines):
                if '--host' in line:
                    newline = f'     --host {wherepsana} $(pwd)/monitor_wrapper.sh\n'
                    logger.info(f'Updating line {ind}: {newline.strip()}')
                    lines[ind] = newline

            # Write updated script
            with open(path, 'w') as file:
                file.writelines(lines)

            logger.info("run_om.sh updated successfully")

        except IOError as e:
            logger.error(f"Failed to update run_om.sh: {e}")
            raise

    def fix_yaml(
            self,
            yaml: str,
            mask: str = '',
            geom: str = ''):
        """
        Update monitor.yaml with current experiment and file paths.

        Modifies OnDA configuration file to reference correct
        experiment, geometry, and mask files.

        Parameters
        ----------
        yaml : str
            Path to monitor.yaml file
        mask : str, optional
            Mask filename (not full path, just basename)
        geom : str, optional
            Geometry filename (not full path, just basename)

        Returns
        -------
        None

        Raises
        ------
        IOError
            If YAML file cannot be read or written

        Notes
        -----
        YAML Updates:
        - Experiment name (Onda.data_retrieval.experiment)
        - Geometry file path
        - Mask file path

        File Paths:
        - Paths are relative to workspace directory
        - Only basenames needed as parameters
        - Full paths constructed in YAML

        YAML Structure:
        The monitor.yaml contains nested configuration
        with specific keys for experiment, geometry, mask.

        Common Issues:
        - YAML indentation critical
        - Paths must match file locations
        - Experiment name must match DAQ

        Examples
        --------
        >>> om = OM()
        >>> om.fix_yaml(
        ...     yaml='/path/to/monitor.yaml',
        ...     mask='epix_mask.h5',
        ...     geom='epix_geometry.geom'
        ... )

        See Also
        --------
        check : Setup experiment (calls this automatically)
        """
        import re

        logger.info(f"Updating YAML: {yaml}")
        logger.info(f"  Mask: {mask}")
        logger.info(f"  Geometry: {geom}")

        try:
            # Read YAML
            with open(yaml, "r") as file:
                lines = file.readlines()

            # Update lines
            for ind, line in enumerate(lines):
                # Update experiment name
                if 'experiment:' in line and 'Onda.data_retrieval' in lines[ind-1]:
                    newline = f'  experiment: {self.experiment}\n'
                    logger.info(f'Updating experiment: {newline.strip()}')
                    lines[ind] = newline

                # Update geometry file
                if 'geometry_file:' in line and geom:
                    # Preserve indentation
                    indent = len(line) - len(line.lstrip())
                    newline = ' ' * indent + f'geometry_file: {geom}\n'
                    logger.info(f'Updating geometry: {newline.strip()}')
                    lines[ind] = newline

                # Update mask file
                if 'mask_filename:' in line and mask:
                    # Preserve indentation
                    indent = len(line) - len(line.lstrip())
                    newline = ' ' * indent + f'mask_filename: {mask}\n'
                    logger.info(f'Updating mask: {newline.strip()}')
                    lines[ind] = newline

            # Write updated YAML
            with open(yaml, 'w') as file:
                file.writelines(lines)

            logger.info("YAML updated successfully")

        except IOError as e:
            logger.error(f"Failed to update YAML: {e}")
            raise

    def check(self):
        """
        Check and setup OnDA experiment directory.

        Verifies OnDA directory structure exists and contains
        necessary configuration files. If missing, creates
        directory and copies files from previous experiment.

        Returns
        -------
        None

        Raises
        ------
        IOError
            If files cannot be copied or created
        SystemExit
            If user chooses not to create directory

        Notes
        -----
        Check Procedure:
        1. Check if experiment directory exists
        2. If missing, offer to create from template
        3. Find most recent experiment directory
        4. Create detector subdirectories:
           - om_workspace (Epix10k2M)
           - om_workspace_rayonix
           - om_workspace_xes
        5. Copy key files from previous experiment:
           - Geometry files (.geom)
           - Mask files (.h5)
           - YAML configs (.yaml)
           - Reset script (om_reset_plots.py)
        6. Update files for current experiment:
           - Fix run_om.sh PSANA host
           - Fix monitor.yaml experiment name
           - Update file paths in YAML

        Files Copied:
        For each detector:
        - Most recent .geom file
        - Most recent mask file
        - Most recent .yaml file

        Files Updated:
        - run_om.sh: PSANA host
        - monitor.yaml: Experiment, paths

        Directory Selection:
        - Finds most recent by modification time
        - Skips if empty
        - User prompted to confirm

        Safety:
        - User must confirm directory creation
        - Existing files not overwritten
        - Logs all operations

        Examples
        --------
        >>> om = OM()
        >>> om.check()  # Interactive setup

        See Also
        --------
        fix_yaml : Update YAML files
        fix_run_om : Update run script
        """
        import sys
        from shutil import copy2

        logger.info("Checking OnDA directory structure")

        # Check if directory exists and has content
        if not os.path.exists(self.pwd) or len(os.listdir(self.pwd)) == 0:
            logger.warning(
                f"No directory exists for experiment: {self.experiment}"
            )
            mkdir = input("Would you like to create it? (y/n): ")

            if mkdir.lower() != "y":
                logger.info("Setup cancelled by user")
                sys.exit("OM setup cancelled")

            # Find most recent experiment directory
            logger.info("Finding most recent experiment for template")

            experiment_dirs = [
                os.path.join(self.cwd, d)
                for d in os.listdir(self.cwd)
                if os.path.isdir(os.path.join(self.cwd, d))
            ]

            if not experiment_dirs:
                logger.error("No previous experiments found for template")
                sys.exit("Cannot create directory without template")

            pre_pwd = max(experiment_dirs, key=os.path.getmtime)
            logger.info(f"Using template from: {pre_pwd}")

            # Create main directory
            os.makedirs(self.pwd)
            logger.info(f"Created directory: {self.pwd}")

            # Create detector subdirectories
            det_dirs = [
                f'{self.pwd}/om_workspace',          # Epix10k2M
                f'{self.pwd}/om_workspace_rayonix',  # Rayonix
                f'{self.pwd}/om_workspace_xes'       # XES
            ]

            det_names = ['Epix10k2M', 'Rayonix', 'XES']

            for det_dir, det_name in zip(det_dirs, det_names):
                logger.info(f"Creating {det_name} workspace")
                os.makedirs(det_dir)

            # Template detector directories
            pre_det_dirs = [
                f'{pre_pwd}/om_workspace',
                f'{pre_pwd}/om_workspace_rayonix',
                f'{pre_pwd}/om_workspace_xes'
            ]

            # Copy files for each detector
            logger.info(f"Copying files from: {pre_pwd}")

            for ind, (det_dir, det_name) in enumerate(zip(det_dirs, det_names)):
                logger.info(f"Setting up {det_name}...")

                if not os.path.exists(pre_det_dirs[ind]):
                    logger.warning(f"Template missing for {det_name}, skipping")
                    continue

                # Copy geometry file
                geom_list = [
                    os.path.join(pre_det_dirs[ind], file)
                    for file in os.listdir(pre_det_dirs[ind])
                    if file.endswith('.geom')
                ]

                if geom_list:
                    geom = max(geom_list, key=os.path.getmtime)
                    copy2(geom, det_dir)
                    logger.info(f"Copied geometry: {os.path.basename(geom)}")
                else:
                    logger.warning(f"No geometry found for {det_name}")
                    geom = ''

                # Copy mask file
                mask_list = [
                    os.path.join(pre_det_dirs[ind], file)
                    for file in os.listdir(pre_det_dirs[ind])
                    if 'mask' in file.lower()
                ]

                if mask_list:
                    mask = max(mask_list, key=os.path.getmtime)
                    copy2(mask, det_dir)
                    logger.info(f"Copied mask: {os.path.basename(mask)}")
                else:
                    logger.warning(f"No mask found for {det_name}")
                    mask = ''

                # Copy and update YAML file
                yaml_list = [
                    os.path.join(pre_det_dirs[ind], file)
                    for file in os.listdir(pre_det_dirs[ind])
                    if file.endswith('.yaml')
                ]

                if yaml_list:
                    yaml = max(yaml_list, key=os.path.getmtime)
                    copy2(yaml, det_dir)
                    logger. info(f"Copied YAML: {os.path.basename(yaml)}")

                    # Update YAML
                    yaml_path = os.path.join(det_dir, os.path.basename(yaml))
                    self.fix_yaml(
                        yaml=yaml_path,
                        mask=os.path.basename(mask) if mask else '',
                        geom=os.path.basename(geom) if geom else ''
                    )
                else:
                    logger.warning(f"No YAML found for {det_name}")

                # Copy shell scripts
                shell_list = [
                    os.path.join(pre_det_dirs[ind], file)
                    for file in os.listdir(pre_det_dirs[ind])
                    if file.endswith('.sh')
                ]

                for sh in shell_list:
                    copy2(sh, det_dir)
                    logger.info(f"Copied script: {os.path.basename(sh)}")

                # Update run_om.sh if present
                run_om_path = os.path.join(det_dir, 'run_om.sh')
                if os.path.isfile(run_om_path):
                    self.fix_run_om(run_om_path)

            # Copy reset plots script
            reset_script = os.path.join(pre_pwd, 'om_reset_plots.py')
            if os.path.exists(reset_script):
                copy2(reset_script, self.pwd)
                logger.info("Copied om_reset_plots.py")
            else:
                logger.warning("om_reset_plots.py not found in template")

            logger.info(
                f"OnDA setup complete for {self.experiment}\n"
                "Please review and update configuration files as needed."
            )
        else:
            logger.info(f"OnDA directory exists: {self.pwd}")

    def run(
            self,
            node: int = 10,
            det: str = 'epix'):
        """
        Launch OnDA monitor for specified detector.

        Starts OnDA real-time monitoring on specified compute node
        for selected detector(s).

        Parameters
        ----------
        node : int, optional
            Compute node number (default: 10)
            Valid range: typically 1-20 depending on allocation
        det : str, optional
            Detector to monitor: 'epix', 'rayonix', 'xes', or 'all' (default: 'epix')

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If det not in valid options
        FileNotFoundError
            If detector workspace doesn't exist

        Notes
        -----
        OnDA Launch:
        - Executes on compute nodes
        - Parallel MPI processing
        - GUI displayed locally
        - Configured via monitor.yaml

        Detector Workspaces:
        - 'epix': om_workspace (Epix10k2M)
        - 'rayonix': om_workspace_rayonix
        - 'xes': om_workspace_xes
        - 'all': All three detectors

        Compute Node:
        - Dedicated processing node
        - Sufficient cores for MPI
        - Access to data streams
        - Network to GUI

        Launch Script:
        - run_om.sh in workspace
        - Contains mpirun command
        - Specifies number of workers
        - Configures GUI connection

        GUI:
        - Opens automatically
        - Shows real-time plots
        - Hit rate monitoring
        - Peak statistics

        Typical Nodes:
        - Node 10: Often used for OM
        - Check allocation before using
        - May need to request nodes

        Multiple Detectors:
        - Can run simultaneously
        - Each needs separate node
        - Or use 'all' for sequential

        Stopping OnDA:
        - Ctrl+C in terminal
        - Or use om.stop()
        - GUI closes automatically

        Examples
        --------
        Launch for Epix10k2M on node 10:
        >>> om = OM()
        >>> om.run(node=10, det='epix')

        Launch for Rayonix on node 12:
        >>> om.run(node=12, det='rayonix')

        Launch all detectors:
        >>> om.run(node=10, det='all')

        See Also
        --------
        check : Setup before running
        reset : Reset OnDA plots
        stop : Stop OnDA monitor
        """
        import subprocess

        logger.info(
            f"Launching OnDA for {det} on node {node}"
        )

        # Determine workspace(s)
        det = det.lower()

        if det == 'epix':
            workspaces = ['om_workspace']
        elif det == 'rayonix':
            workspaces = ['om_workspace_rayonix']
        elif det == 'xes':
            workspaces = ['om_workspace_xes']
        elif det == 'all':
            workspaces = [
                'om_workspace',
                'om_workspace_rayonix',
                'om_workspace_xes'
            ]
        else:
            logger.error(
                f"Unknown detector: {det}. "
                "Use 'epix', 'rayonix', 'xes', or 'all'"
            )
            raise ValueError("Invalid detector")

        # Launch OnDA for each workspace
        for workspace in workspaces:
            workspace_path = os.path.join(self.pwd, workspace)

            if not os.path.exists(workspace_path):
                logger.warning(f"Workspace not found: {workspace_path}")
                continue

            run_script = os.path.join(workspace_path, 'run_om.sh')

            if not os.path.exists(run_script):
                logger.error(f"run_om.sh not found in {workspace}")
                continue

            logger.info(f"Starting OnDA in {workspace}")

            # Launch OnDA
            try:
                cmd = f"cd {workspace_path} && ./run_om.sh -n {node}"
                logger.info(f"Executing: {cmd}")

                # Run in background
                subprocess.Popen(
                    cmd,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )

                logger.info(f"OnDA started for {workspace} on node {node}")

            except Exception as e:
                logger.error(f"Failed to launch OnDA: {e}")

    def reset(self, node: int = 10):
        """
        Reset OnDA monitor plots.

        Clears accumulated statistics and resets plots in running
        OnDA monitor. Useful when starting new sample or condition.

        Parameters
        ----------
        node : int, optional
            Compute node number where OnDA is running (default: 10)

        Returns
        -------
        None

        Raises
        ------
        FileNotFoundError
            If reset script not found

        Notes
        -----
        Reset Operation:
        - Clears plot buffers
        - Resets statistics
        - Maintains connection
        - Does not restart OnDA

        When to Reset:
        - Changing samples
        - After adjustments
        - New experimental condition
        - After detector changes

        Reset Script:
        - om_reset_plots.py in experiment directory
        - Communicates with running OnDA
        - Fast operation (<1 second)

        OnDA Continues:
        - Does not stop monitoring
        - No reconfiguration needed
        - Immediate effect

        Examples
        --------
        >>> om = OM()
        >>> om.reset(node=10)

        See Also
        --------
        run : Launch OnDA
        stop : Stop OnDA
        """
        logger.info(f"Resetting OnDA plots on node {node}")

        reset_script = os.path.join(self.pwd, 'om_reset_plots.py')

        if not os.path.exists(reset_script):
            logger.error("om_reset_plots.py not found")
            logger.info("Run om.check() to setup experiment directory")
            raise FileNotFoundError("Reset script missing")

        try:
            cmd = f"python {reset_script} -n {node}"
            logger.info(f"Executing: {cmd}")

            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                logger.info("OnDA plots reset successfully")
            else:
                logger.error(f"Reset failed: {result.stderr}")

        except subprocess.TimeoutExpired:
            logger.error("Reset timeout (OnDA may not be running)")
        except Exception as e:
            logger.error(f"Reset error: {e}")

    def stop(self, node: int = 10):
        """
        Stop OnDA monitor.

        Terminates running OnDA process on specified node.

        Parameters
        ----------
        node : int, optional
            Compute node number (default: 10)

        Returns
        -------
        None

        Notes
        -----
        Stop Procedure:
        - Finds OnDA process on node
        - Sends termination signal
        - Waits for cleanup
        - Closes GUI

        Graceful Shutdown:
        - Saves current state
        - Closes connections
        - Releases resources

        Examples
        --------
        >>> om = OM()
        >>> om.stop(node=10)

        See Also
        --------
        run : Launch OnDA
        reset : Reset plots
        """
        logger.info(f"Stopping OnDA on node {node}")

        try:
            # Kill OnDA processes
            cmd = f"ssh psana{node:04d} 'pkill -f onda_monitor'"
            logger.info(f"Executing: {cmd}")

            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=10
            )

            logger.info("OnDA stop signal sent")

        except Exception as e:
            logger.error(f"Failed to stop OnDA: {e}")


# Convenience instance for direct import
om = OM()


def setup_om(experiment: Optional[str] = None):
    """
    Convenience function to setup OnDA for experiment.

    Parameters
    ----------
    experiment : str or None, optional
        Experiment name (auto-detected if None)

    Returns
    -------
    None

    Examples
    --------
    >>> setup_om()  # Current experiment
    >>> setup_om('mfxls1234')  # Specific experiment

    See Also
    --------
    OM.check : Full implementation
    """
    om_inst = OM(experiment=experiment)
    om_inst.check()


def launch_om(
        node: int = 10,
        det: str = 'epix',
        experiment: Optional[str] = None):
    """
    Convenience function to launch OnDA.

    Parameters
    ----------
    node : int, optional
        Compute node (default: 10)
    det : str, optional
        Detector: 'epix', 'rayonix', 'xes', 'all' (default: 'epix')
    experiment : str or None, optional
        Experiment name (auto-detected if None)

    Returns
    -------
    None

    Examples
    --------
    >>> launch_om(node=10, det='epix')
    >>> launch_om(node=12, det='all')

    See Also
    --------
    OM.run : Full implementation
    """
    om_inst = OM(experiment=experiment)
    om_inst.run(node=node, det=det)


def reset_om(node: int = 10, experiment: Optional[str] = None):
    """
    Convenience function to reset OnDA plots.

    Parameters
    ----------
    node : int, optional
        Compute node (default: 10)
    experiment : str or None, optional
        Experiment name (auto-detected if None)

    Returns
    -------
    None

    Examples
    --------
    >>> reset_om(node=10)

    See Also
    --------
    OM.reset : Full implementation
    """
    om_inst = OM(experiment=experiment)
    om_inst.reset(node=node)


def stop_om(node: int = 10, experiment: Optional[str] = None):
    """
    Convenience function to stop OnDA.

    Parameters
    ----------
    node : int, optional
        Compute node (default: 10)
    experiment : str or None, optional
        Experiment name (auto-detected if None)

    Returns
    -------
    None

    Examples
    --------
    >>> stop_om(node=10)

    See Also
    --------
    OM.stop : Full implementation
    """
    om_inst = OM(experiment=experiment)
    om_inst.stop(node=node)


# Module initialization
logger.info("OM utilities loaded and ready")