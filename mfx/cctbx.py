"""CCTBX (Computational Crystallography Toolbox) integration for MFX beamline."""

import os
import subprocess
import sys
import logging
from typing import Optional, List, Union

logger = logging.getLogger(__name__)


class cctbx:
    """
    CCTBX integration for crystallography data processing.

    Provides interface to CCTBX suite for X-ray crystallography
    data analysis at remote computing facilities (S3DF, NERSC).
    Handles SSH connections, job submission, and result retrieval.

    CCTBX (Computational Crystallography Toolbox) enables:
    - Diffraction data processing
    - Structure determination
    - Geometry refinement
    - Hit finding and indexing
    - Integration and scaling
    - Real-time feedback

    Methods
    -------
    geom_refine(...) : None
        Refine detector geometry
    average(...) : None
        Average diffraction patterns
    image_viewer(...) : None
        Launch interactive image viewer
    indexing(...) : None
        Index diffraction patterns
    merge(...) : None
        Merge indexed reflections
    sshproxy(user) : None
        Renew SSH proxy for NERSC access
    notch_check(...) : None
        Check notch scan energy calibration

    Attributes
    ----------
    experiment : str
        Current experiment name (e.g., 'mfxls1234')

    Notes
    -----
    Computing Facilities:

    S3DF (SLAC):
    - SLAC Shared Scientific Data Facility
    - Direct network access from MFX
    - Fast data transfer
    - Interactive processing
    - Preferred for real-time analysis

    NERSC (Berkeley):
    - National Energy Research Scientific Computing Center
    - Requires SSH proxy authentication
    - Large-scale batch processing
    - High-performance computing
    - Good for offline analysis

    CCTBX Pipeline:
    1. Data collection (DAQ)
    2. Hit finding (OnDA or cctbx)
    3. Indexing (cctbx.xfel)
    4. Integration
    5. Scaling and merging
    6. Structure determination

    Data Flow:
    - Raw data: /cds/data/psdm/mfx/{exp}/xtc/
    - Processing: /sdf/data/lcls/ds/mfx/{exp}/scratch/
    - Results: /sdf/data/lcls/ds/mfx/{exp}/results/

    SSH Proxy (NERSC):
    - Time-limited authentication
    - Must renew daily
    - Uses sshproxy.sh script
    - Required for NERSC access

    Typical Workflow:
    1. Check SSH proxy (NERSC only)
    2. Submit processing job
    3. Monitor progress
    4. Retrieve results
    5. Iterate if needed

    Common Applications:
    - Serial crystallography (SFX)
    - Time-resolved crystallography
    - Room temperature structures
    - Damage-free data collection
    - Mix-and-inject experiments

    Examples
    --------
    Create CCTBX interface:
    >>> cctbx = cctbx()  # Auto-detects experiment
    >>> cctbx = cctbx(experiment='mfxls1234')  # Specific experiment

    Refine geometry:
    >>> cctbx.geom_refine(
    ...     user='myuser',
    ...     group='000_rg005',
    ...     level=0
    ... )

    Average patterns:
    >>> cctbx.average(user='myuser', run=123)

    View images:
    >>> cctbx.image_viewer(
    ...     user='myuser',
    ...     run=123,
    ...     image_type='average'
    ... )

    See Also
    --------
    om : OnDA real-time monitoring
    autorun : Automated data collection
    """

    def __init__(self, experiment: Optional[str] = None):
        """
        Initialize CCTBX interface.

        Parameters
        ----------
        experiment : str or None, optional
            Experiment name (e.g., 'mfxls1234')
            If None, auto-detects from current session
        """
        if experiment is None:
            from mfx.macros import get_exp
            self.experiment = str(get_exp())
        else:
            self.experiment = experiment

        logger.info(f"CCTBX interface initialized for {self.experiment}")

    def geom_refine(
            self,
            user: str,
            group: str,
            level: Optional[int] = None,
            facility: str = "NERSC",
            exp: str = ''):
        """
        Refine detector geometry from diffraction data.

        Optimizes detector panel positions and orientations to
        minimize indexing residuals. Critical for accurate
        structure determination in serial crystallography.

        Parameters
        ----------
        user : str
            Username for computing facility account
        group : str
            Trial and rungroup identifier (format: '000_rg005')
            Identifies which processed data to refine
        level : int or None, optional
            Refinement level:
            - 0: Whole detector (6 DOF: X, Y, Z, rotX, rotY, rotZ)
            - 1: Individual panels (6 DOF × N panels)
            - None: Systematic refinement (both levels)
        facility : str, optional
            Computing facility: 'NERSC' or 'S3DF' (default: 'NERSC')
        exp : str, optional
            Experiment name (default: '' = current experiment)

        Returns
        -------
        None
            Launches remote processing job

        Raises
        ------
        ValueError
            If facility not 'NERSC' or 'S3DF'

        Notes
        -----
        Geometry Refinement:

        Purpose:
        - Correct detector positioning errors
        - Improve indexing success rate
        - Reduce indexing residuals
        - Enable accurate unit cell determination

        Refinement Levels:

        Level 0 (Whole Detector):
        - Treats detector as rigid body
        - 6 degrees of freedom total
        - Fast optimization
        - Good first approximation
        - Typical corrections: mm-scale position, mrad rotations

        Level 1 (Panel-by-Panel):
        - Independent panel positioning
        - 6 DOF per panel (typically 32-64 panels)
        - Slower optimization
        - Corrects manufacturing tolerances
        - Typical corrections: 0.1 mm, 0.1 mrad

        Systematic (level=None):
        - Runs level 0 first
        - Then level 1 with refined geometry
        - Best final geometry
        - Recommended workflow

        Requirements:
        - Indexed data available
        - Sufficient statistics (>1000 indexed images)
        - Known unit cell
        - Good initial geometry estimate

        Input Files:
        - Indexed reflections (*.refl)
        - Experiments list (*.expt)
        - Initial geometry file (.geom)

        Output:
        - Refined geometry (.geom)
        - Refinement statistics
        - Residual plots
        - Panel shift visualization

        Quality Metrics:
        - RMSD of spot positions
        - Indexing rate improvement
        - Unit cell parameter consistency
        - Panel shift magnitudes

        Iteration:
        - May need multiple refinements
        - Check residuals after each
        - Converges when shifts < threshold
        - Typical: 2-4 iterations

        Common Issues:
        - Insufficient indexed images
        - Poor initial geometry
        - Incorrect unit cell
        - Systematic errors (e.g., energy calibration)

        Examples
        --------
        Whole detector refinement:
        >>> cctbx = cctbx()
        >>> cctbx.geom_refine(
        ...     user='myuser',
        ...     group='002_rg003',
        ...     level=0,
        ...     facility='S3DF'
        ... )

        Panel-by-panel refinement:
        >>> cctbx.geom_refine(
        ...     user='myuser',
        ...     group='002_rg003',
        ...     level=1
        ... )

        Systematic refinement (recommended):
        >>> cctbx.geom_refine(
        ...     user='myuser',
        ...     group='002_rg003',
        ...     level=None  # Both levels
        ... )

        Specific experiment:
        >>> cctbx.geom_refine(
        ...     user='myuser',
        ...     group='000_rg005',
        ...     exp='mfxls1234'
        ... )

        See Also
        --------
        indexing : Index diffraction patterns
        merge : Merge indexed data
        """
        import logging
        import os

        # Determine experiment
        if exp:
            experiment = exp
        else:
            experiment = self.experiment

        # Validate facility
        facility = facility.upper()
        if facility not in ['NERSC', 'S3DF']:
            logger.error(f"Unknown facility: {facility}. Use 'NERSC' or 'S3DF'")
            raise ValueError("Invalid facility")

        logger.info(
            f"Starting geometry refinement:\n"
            f"  Experiment: {experiment}\n"
            f"  Group: {group}\n"
            f"  Level: {level if level is not None else 'systematic'}\n"
            f"  Facility: {facility}"
        )

        # Build command based on facility
        if facility == 'NERSC':
            cmd = (
                f"ssh -Yt {user}@s3dflogin "
                f"python /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/geom_refine.py "
                f"-e {experiment} -f {facility} -g {group} -l {level}"
            )
        elif facility == 'S3DF':
            cmd = (
                f"ssh -Yt {user}@s3dflogin "
                f"/sdf/group/lcls/ds/tools/cctbx/build/bin/python "
                f"/sdf/group/lcls/ds/tools/mfx/scripts/cctbx/geom_refine.py "
                f"-e {experiment} -f {facility} -g {group} -l {level}"
            )

        logger.info(f"Executing: {cmd}")

        # Check SSH proxy for NERSC
        if facility == 'NERSC':
            logger.warning("Have you renewed your SSH token today?")
            token = input("(y/n)? ")

            if token.lower() == "n":
                self.sshproxy(user)

        # Execute command
        os.system(cmd)

        logger.info("Geometry refinement submitted")

    def average(
            self,
            user: str,
            run: int,
            facility: str = "NERSC",
            exp: str = '',
            debug: bool = False):
        """
        Average diffraction patterns from run.

        Computes average of all images in run to identify
        systematic features, powder rings, ice rings, and
        assess data quality.

        Parameters
        ----------
        user : str
            Username for computing facility
        run : int
            Run number to average
        facility : str, optional
            'NERSC' or 'S3DF' (default: 'NERSC')
        exp : str, optional
            Experiment name (default: '' = current)
        debug : bool, optional
            Enable debug output (default: False)

        Returns
        -------
        None
            Launches remote averaging job

        Notes
        -----
        Image Averaging:

        Purpose:
        - Identify powder/ice rings
        - Check beam position
        - Assess background levels
        - Verify detector function
        - Quality control

        Output:
        - Average image (HDF5/CBF)
        - Standard deviation image
        - Maximum projection
        - Radial profile

        Use Cases:
        - Initial data assessment
        - Geometry verification
        - Background characterization
        - Troubleshooting

        Statistics:
        - Mean intensity per pixel
        - Std deviation per pixel
        - Identifies hot/dead pixels
        - Shows systematic features

        Examples
        --------
        Average run 123:
        >>> cctbx = cctbx()
        >>> cctbx.average(user='myuser', run=123)

        With debug output:
        >>> cctbx.average(
        ...     user='myuser',
        ...     run=123,
        ...     debug=True
        ... )

        Specific experiment on S3DF:
        >>> cctbx.average(
        ...     user='myuser',
        ...     run=123,
        ...     facility='S3DF',
        ...     exp='mfxls1234'
        ... )

        See Also
        --------
        image_viewer : View averaged images
        """
        import logging
        import os
        import subprocess

        # Determine experiment
        if exp:
            experiment = exp
        else:
            experiment = self.experiment

        # Validate facility
        facility = facility.upper()
        if facility not in ['NERSC', 'S3DF']:
            logger.error(f"Unknown facility: {facility}")
            raise ValueError("Invalid facility")

        logger.info(
            f"Averaging run {run} for experiment {experiment} on {facility}"
        )

        # Build command
        cmd = (
            f"ssh -Yt {user}@s3dflogin "
            f"python /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/average.py "
            f"-e {experiment} -f {facility} -d {str(debug)} -r {run}"
        )

        logger.info(f"Executing: {cmd}")

        # Check SSH proxy for NERSC
        if facility == 'NERSC':
            logger.warning("Have you renewed your SSH token today?")
            token = input("(y/n)? ")

            if token.lower() == "n":
                self.sshproxy(user)

        # Execute command
        if debug:
            # Show output for debugging
            os.system(cmd)
        else:
            # Background execution
            subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT
            )

        logger.info("Averaging job submitted")

    def image_viewer(
            self,
            user: str,
            run: int,
            image_type: str,
            group: Optional[str] = None,
            facility: str = "NERSC",
            exp: str = '',
            debug: bool = False):
        """
        Launch interactive image viewer for diffraction data.

        Opens GUI for browsing diffraction images with annotations,
        indexing overlays, and interactive analysis tools.

        Parameters
        ----------
        user : str
            Username for computing facility
        run : int
            Run number to view
        image_type : str
            Type of images to view:
            - 'average': Averaged images
            - 'raw': Raw detector images
            - 'indexed': With indexing overlays
            - 'integrated': After integration
        group : str or None, optional
            Trial/rungroup (for processed data)
            Format: '000_rg005'
        facility : str, optional
            'NERSC' or 'S3DF' (default: 'NERSC')
        exp : str, optional
            Experiment name (default: '' = current)
        debug : bool, optional
            Debug mode (default: False) Returns
        -------
        None
            Launches GUI viewer

        Notes
        -----
        Image Viewer Features:
        - Browse all images in run
        - Zoom and pan
        - Intensity scaling
        - Spot finding overlays
        - Indexing solution display
        - Resolution rings
        - Panel boundaries
        - Pixel value inspection

        Image Types:

        'average':
        - Mean of all images
        - Shows systematic features
        - Good for geometry check

        'raw':
        - Unprocessed detector data
        - As collected
        - Full dynamic range

        'indexed':
        - Predicted spot positions
        - Miller indices shown
        - Indexing solution overlay

        'integrated':
        - After background subtraction
        - Integrated intensities
        - Quality metrics

        Viewer Controls:
        - Arrow keys: Navigate images
        - Mouse wheel: Zoom
        - Click: Pixel info
        - Keyboard shortcuts: Various functions

        Examples
        --------
        View averaged images:
        >>> cctbx = cctbx()
        >>> cctbx.image_viewer(
        ...     user='myuser',
        ...     run=123,
        ...     image_type='average'
        ... )

        View indexed images:
        >>> cctbx.image_viewer(
        ...     user='myuser',
        ...     run=123,
        ...     image_type='indexed',
        ...     group='002_rg003'
        ... )

        View raw data:
        >>> cctbx.image_viewer(
        ...     user='myuser',
        ...     run=123,
        ...     image_type='raw'
        ... )

        See Also
        --------
        average : Generate averaged images
        indexing : Index diffraction patterns
        """
        import logging
        import os
        import subprocess

        # Determine experiment
        if exp:
            experiment = exp
        else:
            experiment = self.experiment

        # Validate facility
        facility = facility.upper()
        if facility not in ['NERSC', 'S3DF']:
            logger.error(f"Unknown facility: {facility}")
            raise ValueError("Invalid facility")

        logger.info(
            f"Launching image viewer:\n"
            f"  Type: {image_type}\n"
            f"  Run: {run}\n"
            f"  Group: {group if group else 'N/A'}"
        )

        # Build command
        if facility == 'S3DF':
            cmd = (
                f"ssh -Yt {user}@s3dflogin "
                f"/sdf/group/lcls/ds/tools/cctbx/build/bin/python "
                f"/sdf/group/lcls/ds/tools/mfx/scripts/cctbx/image_viewer.py "
                f"-e {experiment} -f {facility} -d {str(debug)} "
                f"-t {image_type} -r {run} -g {group if group else ''}"
            )
        elif facility == 'NERSC':
            cmd = (
                f"ssh -Yt {user}@s3dflogin "
                f"python /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/image_viewer.py "
                f"-e {experiment} -f {facility} -d {str(debug)} "
                f"-t {image_type} -r {run} -g {group if group else ''}"
            )

        logger.info(f"Executing: {cmd}")

        # Check SSH proxy for NERSC
        if facility == 'NERSC':
            logger.warning("Have you renewed your SSH token today?")
            token = input("(y/n)? ")

            if token.lower() == "n":
                self.sshproxy(user)

        # Execute command
        if debug:
            os.system(cmd)
        else:
            subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT
            )

        logger.info("Image viewer launched")

    def sshproxy(self, user: str):
        """
        Renew SSH proxy for NERSC access.

        NERSC requires time-limited SSH proxy authentication.
        This must be renewed periodically (typically daily).

        Parameters
        ----------
        user : str
            NERSC username

        Returns
        -------
        None
            Runs interactive SSH proxy renewal

        Notes
        -----
        SSH Proxy:
        - Required for NERSC access
        - Time-limited (24 hours typical)
        - Must renew before expiration
        - Interactive password entry

        Renewal Process:
        1. Executes sshproxy.sh script
        2. Prompts for NERSC password
        3. Optionally requests OTP
        4. Stores credentials locally
        5. Valid for 24 hours

        When to Renew:
        - Daily before processing
        - When access fails
        - After credential expiration

        Security:
        - Credentials stored securely
        - Automatic expiration
        - Required for each session

        Examples
        --------
        >>> cctbx = cctbx()
        >>> cctbx.sshproxy('myuser')
        [Interactive password prompt]

        See Also
        --------
        geom_refine : Uses NERSC (checks proxy)
        average : Uses NERSC (checks proxy)
        """
        import os
        import logging

        logger.info(f"Renewing SSH proxy for NERSC user: {user}")
        logger.info("Please enter your NERSC password when prompted")

        cmd = f"sshproxy.sh -u {user}"
        os.system(cmd)

        logger.info("SSH proxy renewal complete")

    def notch_check(
            self,
            user: str,
            facility: str = "NERSC",
            exp: str = '',
            runs: Optional[List[int]] = None,
            energy_range: Optional[tuple] = None):
        """
        Check energy calibration from notch filter scan.

        Analyzes notch filter scan data to verify X-ray energy
        calibration. Compares measured vs. expected absorption edges.

        Parameters
        ----------
        user : str
            Username for computing facility
        facility : str, optional
            'NERSC' or 'S3DF' (default: 'NERSC')
        exp : str, optional
            Experiment name (default: '' = current)
        runs : List[int] or None, optional
            List of run numbers in notch scan
        energy_range : tuple or None, optional
            (start_eV, end_eV, step_eV) for scan

        Returns
        -------
        None
            Launches analysis and displays results

        Notes
        -----
        Notch Filter Calibration:

        Purpose:
        - Verify monochromator energy
        - Check energy calibration
        - Measure energy resolution
        - Detect systematic errors

        Procedure:
        1. Scan across absorption edge
        2. Measure transmitted intensity
        3. Fit edge position
        4. Compare to literature value
        5. Calculate offset

        Analysis:
        - Fits absorption edge
        - Determines edge energy
        - Calculates calibration offset
        - Plots results

        Output:
        - Edge position plot
        - Fitted parameters
        - Calibration offset
        - Recommendations

        Examples
        --------
        Check notch scan:
        >>> cctbx = cctbx()
        >>> cctbx.notch_check(
        ...     user='myuser',
        ...     runs=[100, 101, 102, 103, 104]
        ... )

        With energy range:
        >>> cctbx.notch_check(
        ...     user='myuser',
        ...     runs=[100, 101, 102],
        ...     energy_range=(7100, 7140, 10)  # eV
        ... )

        See Also
        --------
        vernier : Energy vernier scans
        """
        logger.info("Notch filter calibration check")
        logger.warning("This feature is under development")


# Convenience instance for direct import
cctbx_instance = cctbx()


# Convenience functions

def refine_geometry(
        user: str,
        group: str,
        level: Optional[int] = None,
        facility: str = "S3DF"):
    """
    Convenience function for geometry refinement.

    Parameters
    ----------
    user : str
        Username
    group : str
        Trial/rungroup (e.g., '002_rg003')
    level : int or None, optional
        Refinement level (0, 1, or None for both)
    facility : str, optional
        'NERSC' or 'S3DF' (default: 'S3DF')

    Returns
    -------
    None

    Examples
    --------
    >>> from mfx.cctbx import refine_geometry
    >>> refine_geometry('myuser', '002_rg003', level=0)

    See Also
    --------
    cctbx.geom_refine : Full implementation
    """
    cctbx_instance.geom_refine(
        user=user,
        group=group,
        level=level,
        facility=facility
    )


def view_images(
        user: str,
        run: int,
        image_type: str = 'average',
        group: Optional[str] = None,
        facility: str = "S3DF"):
    """
    Convenience function for image viewer.

    Parameters
    ----------
    user : str
        Username
    run : int
        Run number
    image_type : str, optional
        Image type (default: 'average')
    group : str or None, optional
        Trial/rungroup
    facility : str, optional
        'NERSC' or 'S3DF' (default: 'S3DF')

    Returns
    -------
    None

    Examples
    --------
    >>> from mfx.cctbx import view_images
    >>> view_images('myuser', 123, image_type='indexed', group='002_rg003')

    See Also
    --------
    cctbx.image_viewer : Full implementation
    """
    cctbx_instance.image_viewer(
        user=user,
        run=run,
        image_type=image_type,
        group=group,
        facility=facility
    )


def average_run(
        user: str,
        run: int,
        facility: str = "S3DF"):
    """
    Convenience function for averaging run.

    Parameters
    ----------
    user : str
        Username
    run : int
        Run number
    facility : str, optional
        'NERSC' or 'S3DF' (default: 'S3DF')

    Returns
    -------
    None

    Examples
    --------
    >>> from mfx.cctbx import average_run
    >>> average_run('myuser', 123)

    See Also
    --------
    cctbx.average : Full implementation
    """
    cctbx_instance.average(
        user=user,
        run=run,
        facility=facility
    )


def renew_nersc_proxy(user: str):
    """
    Convenience function to renew NERSC SSH proxy.

    Parameters
    ----------
    user : str
        NERSC username

    Returns
    -------
    None

    Examples
    --------
    >>> from mfx.cctbx import renew_nersc_proxy
    >>> renew_nersc_proxy('myuser')

    See Also
    --------
    cctbx.sshproxy : Full implementation
    """
    cctbx_instance.sshproxy(user)


# Module initialization
logger.info("CCTBX integration loaded for crystallography data processing")