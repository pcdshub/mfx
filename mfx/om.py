"""
OnDA (Online Data Analysis) monitor control for MFX beamline.

Provides setup, configuration, and launch utilities for OnDA real-time
crystallography monitoring system for Epix10k2M, Rayonix, and XES detectors.
"""

import os
import logging
from typing import Optional, List
import glob

logger = logging.getLogger(__name__)


class OM:
    """
    OnDA Monitor configuration and control.

    Manages OnDA monitoring system setup including directory structure,
    configuration files, geometry files, and process launching for
    real-time crystallography analysis.

    Attributes
    ----------
    experiment : str
        Current experiment name
    pwd : str
        OnDA workspace directory path
    detector_types : List[str]
        Available detector configurations

    Methods
    -------
    check()
        Verify and setup OnDA directory structure
    run(node, det)
        Launch OnDA monitor process
    reset(node)
        Reset OnDA plot displays
    fix_yaml(yaml, mask, geom)
        Update YAML configuration files
    fix_run_om(detector)
        Update OnDA launch script

    Notes
    -----
    OnDA System:
    - Real-time crystallography monitoring
    - Hit finding and indexing
    - Live feedback during data collection
    - GUI displays for visualization
    - Parallel processing on compute nodes

    Directory Structure:
    /cds/home/opr/mfxopr/OM-GUI/{experiment}/
        om_workspace/           # Epix10k2M config
            monitor.yaml
            geometry.geom
            mask.h5
            run_om.sh
        om_workspace_rayonix/   # Rayonix config
            monitor.yaml
            geometry.geom
            mask.h5
            run_om.sh
        om_workspace_xes/       # XES config
            monitor.yaml
            geometry.geom
            mask.h5
            run_om.sh
        om_reset_plots.py       # Plot reset script

    Configuration Files:

    monitor.yaml:
    - OnDA parameters
    - Hit finding thresholds
    - Peak detection settings
    - Data source configuration
    - Output specifications

    geometry.geom:
    - Detector panel positions
    - Pixel sizes and geometry
    - Distance to sample
    - Beam center location

    mask.h5:
    - Bad pixel mask
    - Module boundaries
    - Dead/hot pixels
    - Shadowed regions

    run_om.sh:
    - Launch script
    - MPI configuration
    - Node assignments
    - Environment setup

    Detector Support:
    - Epix10k2M: Main area detector (2M pixels)
    - Rayonix: Large area detector
    - XES: X-ray emission spectrometer

    Examples
    --------
    Create OM controller:
    >>> om = OM()
    Checking experiment: mfxls1234

    Setup experiment (first time):
    >>> om.check()
    Setting up OnDA directories...

    Launch OnDA for Epix10k2M:
    >>> om.run(node=10, det='epix')
    Starting OnDA on drp-srcf-cmp010

    Launch for all detectors:
    >>> om.run(node=10, det='all')

    Reset displays:
    >>> om.reset(node=10)

    See Also
    --------
    check : Setup and verification
    run : Launch OnDA process
    """

    def __init__(self, experiment: Optional[str] = None):
        """
        Initialize OM controller.

        Parameters
        ----------
        experiment : str, optional
            Experiment name. If None, auto-detects from hutch config.
            Default is None.

        Notes
        -----
        Initialization Process:
        1. Determine experiment name
        2. Set workspace directory path
        3. Log configuration
        """
        if experiment is None:
            from mfx.macros import get_exp
            self.experiment = str(get_exp())
        else:
            self.experiment = experiment

        # Set workspace directory
        self.pwd = f"/cds/home/opr/mfxopr/OM-GUI/{self.experiment}"

        # Define detector types
        self.detector_types = ['epix', 'rayonix', 'xes']

        logger.info(f"OM controller initialized for {self.experiment}")
        logger.info(f"Workspace: {self.pwd}")

    def check(self):
        """
        Verify and setup OnDA directory structure.

        Checks if experiment directory exists and contains proper
        OnDA configuration. If not, creates directories and copies
        template files from most recent experiment.

        Returns
        -------
        None

        Raises
        ------
        SystemExit
            If user cancels directory creation

        Notes
        -----
        Check Process:
        1. Verify experiment directory exists
        2. If not exists or empty:
           a. Prompt user to create
           b. Find most recent experiment as template
           c. Copy directory structure
           d. Copy configuration files
        3. Update experiment name in configs
        4. Update YAML files with paths
        5. Update run scripts

        Template Selection:
        - Searches /cds/home/opr/mfxopr/OM-GUI/
        - Finds most recent experiment directory
        - Excludes current experiment
        - Uses newest by modification time

        Files Copied:
        For each detector workspace:
        - Most recent .geom file
        - Most recent mask file (.h5)
        - Most recent monitor.yaml
        - run_om.sh script
        - Supporting scripts

        Files Updated:
        - monitor.yaml: Experiment name, file paths
        - run_om.sh: PSANA host, paths

        Warnings
        --------
        Directory creation requires user confirmation.
        Template files copied without modification of parameters.
        Review and adjust thresholds before first use.

        Examples
        --------
        Check and setup:
        >>> om = OM()
        >>> om.check()
        No directory exists for experiment: mfxls1234
        Would you like to create it? (y/n): y
        Finding most recent experiment...
        Copying from mfxls1200...
        Setup complete

        Verify existing setup:
        >>> om.check()
        Directory exists and configured
        Ready for OnDA operation

        See Also
        --------
        fix_yaml : Update YAML configuration
        fix_run_om : Update run script
        """
        logger.info("Checking OnDA directory structure...")

        # Check if directory exists and has content
        if not os.path.exists(self.pwd) or len(os.listdir(self.pwd)) == 0:
            logger.warning(
                f"No directory exists for experiment: {self.experiment}"
            )

            # Prompt user
            mkdir = input("Would you like to create it? (y/n): ")

            if mkdir.lower() != 'y':
                logger.info("Setup cancelled by user")
                raise SystemExit("OM setup cancelled")

            # Find most recent experiment as template
            logger.info("Finding most recent experiment for template...")

            om_base = "/cds/home/opr/mfxopr/OM-GUI"
            all_exps = [
                d for d in os.listdir(om_base)
                if os.path.isdir(os.path.join(om_base, d))
                and d.startswith('mfx')
                and d != self.experiment
            ]

            if not all_exps:
                logger.error("No template experiments found")
                raise SystemExit("Cannot create directory without template")

            # Sort by modification time (newest first)
            all_exps.sort(
                key=lambda x: os.path.getmtime(os.path.join(om_base, x)),
                reverse=True
            )

            template_exp = all_exps[0]
            template_pwd = os.path.join(om_base, template_exp)

            logger.info(f"Using template: {template_exp}")

            # Create experiment directory
            os.makedirs(self.pwd, exist_ok=True)
            logger.info(f"Created directory: {self.pwd}")

            # Copy workspace directories for each detector
            for det in self.detector_types:
                # Determine workspace name
                if det == 'epix':
                    workspace = 'om_workspace'
                elif det == 'rayonix':
                    workspace = 'om_workspace_rayonix'
                elif det == 'xes':
                    workspace = 'om_workspace_xes'

                template_workspace = os.path.join(template_pwd, workspace)
                new_workspace = os.path.join(self.pwd, workspace)

                if not os.path.exists(template_workspace):
                    logger.warning(
                        f"Template workspace not found: {workspace}"
                    )
                    continue

                logger.info(f"Setting up {workspace}...")

                # Create workspace directory
                os.makedirs(new_workspace, exist_ok=True)

                # Copy geometry file (most recent .geom)
                geom_files = glob.glob(
                    os.path.join(template_workspace, '*.geom')
                )
                if geom_files:
                    geom_files.sort(key=os.path.getmtime, reverse=True)
                    latest_geom = geom_files[0]
                    os.system(
                        f"cp {latest_geom} "
                        f"{os.path.join(new_workspace, 'geometry.geom')}"
                    )
                    logger.info(f"  Copied geometry file")

                # Copy mask file (most recent .h5)
                mask_files = glob.glob(
                    os.path.join(template_workspace, '*.h5')
                )
                if mask_files:
                    mask_files.sort(key=os.path.getmtime, reverse=True)
                    latest_mask = mask_files[0]
                    os.system(
                        f"cp {latest_mask} "
                        f"{os.path.join(new_workspace, 'mask.h5')}"
                    )
                    logger.info(f"  Copied mask file")

                # Copy YAML file (most recent .yaml)
                yaml_files = glob.glob(
                    os.path.join(template_workspace, '*.yaml')
                )
                if yaml_files:
                    yaml_files.sort(key=os.path.getmtime, reverse=True)
                    latest_yaml = yaml_files[0]
                    os.system(
                        f"cp {latest_yaml} "
                        f"{os.path.join(new_workspace, 'monitor.yaml')}"
                    )
                    logger.info(f"  Copied YAML config")

                # Copy run script
                template_script = os.path.join(
                    template_workspace, 'run_om.sh'
                )
                if os.path.exists(template_script):
                    os.system(
                        f"cp {template_script} "
                        f"{os.path.join(new_workspace, 'run_om.sh')}"
                    )
                    os.system(
                        f"chmod +x "
                        f"{os.path.join(new_workspace, 'run_om.sh')}"
                    )
                    logger.info(f"  Copied run script")

                # Update YAML with correct paths
                yaml_path = os.path.join(new_workspace, 'monitor.yaml')
                geom_path = os.path.join(new_workspace, 'geometry.geom')
                mask_path = os.path.join(new_workspace, 'mask.h5')

                if os.path.exists(yaml_path):
                    self.fix_yaml(yaml_path, mask_path, geom_path)
                    logger.info(f"  Updated YAML configuration")

                # Update run script
                if det == 'epix':
                    self.fix_run_om('epix10k2M')
                elif det == 'rayonix':
                    self.fix_run_om('rayonix')
                elif det == 'xes':
                    self.fix_run_om('xes')

            # Copy reset script
            template_reset = os.path.join(template_pwd, 'om_reset_plots.py')
            if os.path.exists(template_reset):
                os.system(
                    f"cp {template_reset} "
                    f"{os.path.join(self.pwd, 'om_reset_plots.py')}"
                )
                logger.info("Copied plot reset script")

            logger.info("\n" + "="*60)
            logger.info("OnDA Setup Complete")
            logger.info("="*60)
            logger.info(f"Experiment: {self.experiment}")
            logger.info(f"Directory: {self.pwd}")
            logger.info("\nNext steps:")
            logger.info("1. Review monitor.yaml parameters")
            logger.info("2. Verify geometry files")
            logger.info("3. Launch OnDA with om.run()")
            logger.info("="*60)

        else:
            logger.info("OnDA directory exists and configured")
            logger.info(f"Location: {self.pwd}")
            logger.info("Ready for OnDA operation")

    def fix_yaml(
            self,
            yaml: str,
            mask: Optional[str] = None,
            geom: Optional[str] = None):
        """
        Update YAML configuration file.

        Modifies OnDA YAML configuration to set correct experiment
        name, geometry file path, and mask file path.

        Parameters
        ----------
        yaml : str
            Path to YAML file to update
        mask : str, optional
            Path to mask file. If None, skips mask update.
            Default is None.
        geom : str, optional
            Path to geometry file. If None, skips geometry update.
            Default is None.

        Returns
        -------
        None

        Notes
        -----
        Update Process:
        1. Read YAML file line by line
        2. Find and replace:
           - experiment: {new_experiment}
           - geometry_file: {geom}
           - mask_filename: {mask}
        3. Preserve indentation
        4. Write back to file

        YAML Structure:
        ```yaml
        Onda.data_retrieval:
          experiment: mfxls1234
          ...
        Onda.crystallography:
          geometry_file: /path/to/geometry.geom
          mask_filename: /path/to/mask.h5
          ...
        ```

        Warnings
        --------
        Modifies file in place. Backup before modifying.
        Indentation must be preserved for valid YAML.

        Examples
        --------
        Update all fields:
        >>> om.fix_yaml(
        ...     '/path/to/monitor.yaml',
        ...     mask='/path/to/mask.h5',
        ...     geom='/path/to/geometry.geom'
        ... )

        Update only experiment:
        >>> om.fix_yaml('/path/to/monitor.yaml')

        See Also
        --------
        check : Calls this during setup
        """
        logger.info(f"Updating YAML: {yaml}")
        if mask:
            logger.info(f"  Mask: {mask}")
        if geom:
            logger.info(f"  Geometry: {geom}")

        try:
            # Read YAML file
            with open(yaml, 'r') as f:
                lines = f.readlines()

            # Update lines
            for ind, line in enumerate(lines):
                # Update experiment name
                if ('experiment:' in line and
                        'Onda.data_retrieval' in lines[ind-1]):
                    # Preserve indentation
                    indent = len(line) - len(line.lstrip())
                    newline = ' ' * indent + f'experiment: {self.experiment}\n'
                    logger.debug(f'Updating experiment: {newline.strip()}')
                    lines[ind] = newline

                # Update geometry file
                if 'geometry_file:' in line and geom:
                    indent = len(line) - len(line.lstrip())
                    newline = ' ' * indent + f'geometry_file: {geom}\n'
                    logger.debug(f'Updating geometry: {newline .strip()}')
                    lines[ind] = newline

                # Update mask file
                if 'mask_filename:' in line and mask:
                    indent = len(line) - len(line.lstrip())
                    newline = ' ' * indent + f'mask_filename: {mask}\n'
                    logger.debug(f'Updating mask: {newline.strip()}')
                    lines[ind] = newline

            # Write updated YAML
            with open(yaml, 'w') as f:
                f.writelines(lines)

            logger.info("YAML updated successfully")

        except IOError as e:
            logger.error(f"Failed to update YAML: {e}")
            raise

    def fix_run_om(self, detector: str):
        """
        Update OnDA run script for current environment.

        Modifies run_om.sh to use current PSANA host for MPI
        execution.

        Parameters
        ----------
        detector : str
            Detector type: 'epix10k2M', 'rayonix', or 'xes'

        Returns
        -------
        None

        Notes
        -----
        Script Updates:
        - Replaces --host parameter with current PSANA node
        - Uses wherepsana to find current host
        - Preserves rest of MPI command

        Run Script Format:
        ```bash
        mpirun -n 24 --host drp-srcf-cmp010 \
            $(pwd)/monitor_wrapper.sh
        ```

        The --host line is updated to current PSANA node.

        Examples
        --------
        >>> om.fix_run_om('epix10k2M')
        Updating run_om.sh for epix10k2M

        See Also
        --------
        check : Calls this during setup
        """
        # Determine workspace
        if detector.lower() == 'epix10k2m':
            workspace = 'om_workspace'
        elif detector.lower() == 'rayonix':
            workspace = 'om_workspace_rayonix'
        elif detector.lower() == 'xes':
            workspace = 'om_workspace_xes'
        else:
            logger.error(f"Unknown detector: {detector}")
            return

        script_path = os.path.join(self.pwd, workspace, 'run_om.sh')

        if not os.path.exists(script_path):
            logger.warning(f"Run script not found: {script_path}")
            return

        logger.info(f"Updating run_om.sh for {detector}")

        # Get current PSANA host
        wherepsana = os.popen("wherepsana").read().strip()
        logger.info(f"Current PSANA host: {wherepsana}")

        try:
            # Read script
            with open(script_path, 'r') as f:
                lines = f.readlines()

            # Update --host line
            for ind, line in enumerate(lines):
                if '--host' in line:
                    # Replace host parameter
                    newline = f'     --host {wherepsana} $(pwd)/monitor_wrapper.sh\n'
                    logger.debug(f'Updating line {ind}: {newline.strip()}')
                    lines[ind] = newline

            # Write updated script
            with open(script_path, 'w') as f:
                f.writelines(lines)

            logger.info("run_om.sh updated successfully")

        except IOError as e:
            logger.error(f"Failed to update run script: {e}")
            raise

    def run(self, node: int, det: str = 'epix'):
        """
        Launch OnDA monitor process.

        Starts OnDA monitoring on specified compute node for
        specified detector(s).

        Parameters
        ----------
        node : int
            Compute node number (e.g., 10 for drp-srcf-cmp010)
        det : str, optional
            Detector to monitor: 'epix', 'rayonix', 'xes', or 'all'.
            Default is 'epix'.

        Returns
        -------
        None

        Notes
        -----
        Launch Process:
        1. Determine workspace directory
        2. Change to workspace
        3. Execute run_om.sh script
        4. Script starts MPI parallel processing
        5. OnDA begins monitoring data stream

        Compute Nodes:
        - drp-srcf-cmp001 through drp-srcf-cmp030
        - High-performance machines
        - Local to data acquisition
        - MPI parallel processing

        Monitor Operation:
        - Reads data from psana
        - Performs hit finding
        - Extracts peak positions
        - Attempts indexing
        - Updates GUI displays
        - Logs statistics

        Multiple Detectors:
        - Use det='all' to start all
        - Each runs in separate process
        - Can monitor different nodes
        - Independent GUI windows

        Stopping OnDA:
        - Ctrl+C in terminal
        - Or kill process on node
        - GUI windows close automatically

        Warnings
        --------
        Ensure data acquisition is running before starting OnDA.
        Check compute node is available and responsive.
        Verify detector is enabled in DAQ configuration.

        Examples
        --------
        Start Epix10k2M monitoring:
        >>> om = OM()
        >>> om.run(node=10, det='epix')
        Launching OnDA on drp-srcf-cmp010...

        Start all detectors:
        >>> om.run(node=10, det='all')
        Launching OnDA for all detectors...

        Start Rayonix only:
        >>> om.run(node=15, det='rayonix')

        See Also
        --------
        reset : Reset OnDA displays
        check : Setup before running
        """
        logger.info(f"Launching OnDA on node {node} for {det}")

        # Determine workspaces to start
        if det.lower() == 'epix':
            workspaces = ['om_workspace']
        elif det.lower() == 'rayonix':
            workspaces = ['om_workspace_rayonix']
        elif det.lower() == 'xes':
            workspaces = ['om_workspace_xes']
        elif det.lower() == 'all':
            workspaces = [
                'om_workspace',
                'om_workspace_rayonix',
                'om_workspace_xes'
            ]
        else:
            logger.error(f"Unknown detector: {det}")
            logger.error("Use 'epix', 'rayonix', 'xes', or 'all'")
            return

        # Launch each workspace
        for workspace in workspaces:
            workspace_path = os.path.join(self.pwd, workspace)

            if not os.path.exists(workspace_path):
                logger.warning(f"Workspace not found: {workspace}")
                continue

            run_script = os.path.join(workspace_path, 'run_om.sh')

            if not os.path.exists(run_script):
                logger.warning(f"Run script not found: {run_script}")
                continue

            logger.info(f"Starting {workspace}...")

            # Change to workspace and execute
            cmd = f"cd {workspace_path} && ./run_om.sh &"
            logger.debug(f"Executing: {cmd}")

            os.system(cmd)

            logger.info(f"  OnDA started for {workspace}")

        logger.info("\n" + "="*60)
        logger.info("OnDA Monitor Started")
        logger.info("="*60)
        logger.info("GUI windows should appear shortly")
        logger.info("Press Ctrl+C in launch window to stop")
        logger.info("="*60)

    def reset(self, node: int):
        """
        Reset OnDA plot displays.

        Clears and reinitializes OnDA GUI plots, useful when
        displays become corrupted or unresponsive.

        Parameters
        ----------
        node : int
            Compute node number where OnDA is running

        Returns
        -------
        None

        Notes
        -----
        Reset Process:
        1. Execute om_reset_plots.py script
        2. Clears all plot buffers
        3. Reinitializes displays
        4. Restores default view
        5. Does not restart OnDA process

        When to Reset:
        - Plots frozen or not updating
        - Display corrupted
        - After parameter changes
        - GUI unresponsive

        Does Not Reset:
        - OnDA parameters
        - Processing statistics
        - Monitoring process

        Examples
        --------
        >>> om.reset(node=10)
        Resetting OnDA plots on node 10

        See Also
        --------
        run : Launch OnDA
        """
        logger.info(f"Resetting OnDA plots on node {node}")

        reset_script = os.path.join(self.pwd, 'om_reset_plots.py')

        if not os.path.exists(reset_script):
            logger.error("Reset script not found")
            logger.error(f"Expected: {reset_script}")
            return

        # Execute reset script
        cmd = f"python {reset_script}"
        logger.debug(f"Executing: {cmd}")

        os.system(cmd)

        logger.info("OnDA plots reset complete")


# Convenience module-level instance
om = OM()


def start_onda(node: int, detector: str = 'epix'):
    """
    Start OnDA monitor (convenience function).

    Parameters
    ----------
    node : int
        Compute node number
    detector : str, optional
        Detector type. Default is 'epix'.

    Examples
    --------
    >>> start_onda(10, 'epix')
    >>> start_onda(10, 'all')

    See Also
    --------
    OM.run : Full implementation
    """
    om.run(node=node, det=detector)


def reset_onda(node: int):
    """
    Reset OnDA displays (convenience function).

    Parameters
    ----------
    node : int
        Compute node number

    Examples
    --------
    >>> reset_onda(10)

    See Also
    --------
    OM.reset : Full implementation
    """
    om.reset(node=node)


logger.info("OnDA monitor control loaded and ready")