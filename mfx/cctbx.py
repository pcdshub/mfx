"""
CCTBX (Computational Crystallography Toolbox) integration for MFX beamline.

Provides interfaces for serial crystallography data processing, including
hit finding, indexing, geometry refinement, and result visualization on
S3DF and NERSC computing facilities.
"""

import os
import logging
import subprocess
import sys
from typing import Optional, List

logger = logging.getLogger(__name__)


class cctbx:
    """
    CCTBX data processing interface for serial crystallography.

    Provides Python wrappers for CCTBX processing scripts running on
    S3DF (SLAC) and NERSC (Berkeley) computing facilities. Supports
    hit finding, indexing, integration, and geometry refinement.

    Attributes
    ----------
    experiment : str
        Current experiment name (e.g., 'mfxls1234')

    Methods
    -------
    sshproxy(user)
        Renew SSH proxy for NERSC access
    image_viewer(user, facility, image_type, exp, run, group, debug)
        Launch interactive image viewer for detector data
    indexing(user, facility, exp, run, group, debug)
        Submit indexing job for diffraction data
    merge(user, facility, exp, group, debug)
        Merge indexed data into structure factors
    geom_refine(user, facility, group, level, exp)
        Refine detector geometry from indexed data

    Notes
    -----
    Computing Facilities:

    S3DF (SLAC):
    - SLAC Shared Scientific Data Facility
    - Direct network access from MFX
    - Fast data transfer to/from experiment
    - Interactive and batch processing
    - Preferred for real-time analysis
    - Location: SLAC campus
    - Access: mfxopr@s3dflogin

    NERSC (Berkeley):
    - National Energy Research Scientific Computing Center
    - High-performance computing resources
    - Requires SSH proxy authentication
    - Large-scale batch processing
    - Good for offline/post-experiment analysis
    - Location: Berkeley, CA
    - Access: username@perlmutter-p1.nersc.gov

    CCTBX Pipeline:
    1. Hit finding: Identify frames with diffraction
    2. Indexing: Determine crystal orientation
    3. Integration: Extract intensities
    4. Scaling: Merge multiple crystals
    5. Structure determination: Solve structure

    Data Flow:
    - Raw data: /cds/data/psdm/mfx/{exp}/xtc/
    - Processing scratch: /sdf/data/lcls/ds/mfx/{exp}/scratch/
    - Results: /sdf/data/lcls/ds/mfx/{exp}/results/
    - NERSC: /global/cfs/cdirs/lcls/mfx/{exp}/

    SSH Proxy (NERSC):
    - Time-limited authentication (24 hours)
    - Must renew daily during beam time
    - Uses sshproxy.sh script
    - Required for all NERSC operations

    Typical Workflow:
    1. Check SSH proxy (NERSC only)
    2. Submit processing job
    3. Monitor progress via logs
    4. Retrieve and analyze results
    5. Iterate geometry/parameters if needed

    Examples
    --------
    Create CCTBX interface (auto-detects experiment):
    >>> cctbx_obj = cctbx()

    Create for specific experiment:
    >>> cctbx_obj = cctbx(experiment='mfxls1234')

    View images from run 100:
    >>> cctbx_obj.image_viewer(
    ...     user='myuser',
    ...     facility='S3DF',
    ...     image_type='idx',
    ...     run=100
    ... )

    Index diffraction data:
    >>> cctbx_obj.indexing(
    ...     user='myuser',
    ...     facility='S3DF',
    ...     run=100,
    ...     group='001_rg001'
    ... )

    See Also
    --------
    BashUtilities.xfel_gui : Launch CCTBX GUI
    """

    def __init__(self, experiment: Optional[str] = None):
        """
        Initialize CCTBX interface.

        Parameters
        ----------
        experiment : str, optional
            Experiment name. If None, attempts to determine from
            current hutch configuration. Default is None.

        Notes
        -----
        Experiment name format: {hutch}{ls|lr}{number}
        - hutch: mfx, cxi, xpp, etc.
        - ls: long shutdown (new experiment)
        - lr: long run (continuing experiment)
        - number: sequential experiment number

        Example: mfxls1234 = MFX long shutdown experiment 1234

        Examples
        --------
        Auto-detect experiment:
        >>> cctbx_obj = cctbx()

        Specify experiment:
        >>> cctbx_obj = cctbx(experiment='mfxls1234')
        """
        if experiment is None:
            from mfx.macros import get_exp
            self.experiment = str(get_exp())
            logger.info(f"Auto-detected experiment: {self.experiment}")
        else:
            self.experiment = experiment
            logger.info(f"Using specified experiment: {self.experiment}")

    def sshproxy(self, user: str):
        """
        Renew SSH proxy for NERSC access.

        Runs sshproxy.sh script to obtain time-limited SSH certificate
        for accessing NERSC resources. Required daily for NERSC
        operations.

        Parameters
        ----------
        user : str
            NERSC username

        Returns
        -------
        None

        Notes
        -----
        SSH Proxy:
        - One-time password (OTP) required
        - Valid for 24 hours
        - Must be renewed daily
        - Required for all NERSC SSH connections

        The sshproxy creates a certificate stored in ~/.ssh/ that
        allows passwordless SSH to NERSC for the validity period.

        Process:
        1. Run sshproxy.sh
        2. Enter NERSC password
        3. Enter OTP from authenticator app
        4. Certificate created (~/.ssh/nersc)
        5. Valid for 24 hours

        Troubleshooting:
        - "Permission denied": Renew proxy
        - "OTP incorrect": Check authenticator app time sync
        - "Password incorrect": Reset NERSC password

        Warnings
        --------
        Keep OTP device (phone) accessible during beam time.
        Renew proxy before starting overnight processing jobs.

        Examples
        --------
        Renew proxy:
        >>> cctbx_obj = cctbx()
        >>> cctbx_obj.sshproxy('myuser')
        Enter NERSC password:
        Enter OTP:
        Success: SSH certificate valid for 24 hours

        See Also
        --------
        indexing : Uses SSH proxy for NERSC access
        merge : Uses SSH proxy for NERSC access
        """
        logger.info(f"Renewing SSH proxy for NERSC user: {user}")
        logger.info("You will be prompted for:")
        logger.info("  1. NERSC password")
        logger.info("  2. One-time password (OTP) from authenticator")

        cmd = (
            f"ssh -Yt {user}@s3dflogin "
            f"/sdf/group/lcls/ds/tools/mfx/scripts/cctbx/sshproxy.sh "
            f"-c cctbx -u {user}"
        )
        logger.info(f"Executing: {cmd}")

        result = os.system(cmd)

        if result == 0:
            logger.info("SSH proxy renewed successfully")
            logger.info("Certificate valid for 24 hours")
        else:
            logger.error("SSH proxy renewal failed")
            logger.error("Check password and OTP")

    def image_viewer(
            self,
            user: str,
            facility: str = 'S3DF',
            image_type: str = 'avg',
            exp: Optional[str] = None,
            run: Optional[int] = None,
            group: Optional[str] = None,
            debug: bool = False):
        """
        Launch interactive image viewer for detector data.

        Opens CCTBX image viewer to display detector images, indexed
        patterns, or averaged frames from specified run.

        Parameters
        ----------
        user : str
            Username for remote facility access
        facility : str, optional
            Computing facility: 'S3DF' or 'NERSC' (case-insensitive).
            Default is 'S3DF'.
        image_type : str, optional
            Type of images to display:
            - 'avg': Averaged frames (default)
            - 'idx': Indexed diffraction patterns
            - 'max': Maximum projections
            - 'raw': Raw detector frames
            Default is 'avg'.
        exp : str, optional
            Experiment name. If None, uses instance experiment.
            Default is None.
        run : int, optional
            Run number to display. If None, prompts user.
            Default is None.
        group : str, optional
            Processing group (e.g., '001_rg001'). Required for
            indexed images. Default is None.
        debug : bool, optional
            Enable debug output. Default is False.

        Returns
        -------
        None

        Notes
        -----
        Image Types:

        avg (Average):
        - Average of many frames
        - Useful for powder patterns
        - Shows overall detector response
        - Good for geometry verification

        idx (Indexed):
        - Frames with successful indexing
        - Shows found Bragg peaks
        - Miller indices overlaid
        - Requires group specification

        max (Maximum):
        - Maximum projection over run
        - Highlights brightest spots
        - Good for spot finding validation
        - Shows detector active area

        raw (Raw):
        - Unprocessed detector frames
        - Full resolution
        - Large file sizes
        - Useful for diagnostics

        Viewer Features:
        - Zoom and pan
        - Colormap adjustment
        - ROI (Region of Interest) selection
        - Bragg peak overlay (idx mode)
        - Distance/resolution rings
        - Export to image files

        Requirements:
        - X11 forwarding or FastX
        - Sufficient bandwidth for image transfer
        - Processing must be complete (idx mode)

        Warnings
        --------
        Viewer requires X11 display. Use FastX or ssh -Y for
        remote connections. Large images may be slow to load.

        Examples
        --------
        View averaged images:
        >>> cctbx_obj = cctbx()
        >>> cctbx_obj.image_viewer(
        ...     user='myuser',
        ...     facility='S3DF',
        ...     image_type='avg',
        ...     run=100
        ... )

        View indexed patterns:
        >>> cctbx_obj.image_viewer(
        ...     user='myuser',
        ...     facility='S3DF',
        ...     image_type='idx',
        ...     run=100,
        ...     group='001_rg001'
        ... )

        View on NERSC (requires proxy):
        >>> cctbx_obj.sshproxy('myuser')
        >>> cctbx_obj.image_viewer(
        ...     user='myuser',
        ...     facility='NERSC',
        ...     image_type='avg',
        ...     run=100
        ... )

        See Also
        --------
        indexing : Process data before viewing indexed images
        BashUtilities.xfel_gui : Alternative CCTBX GUI
        """
        # Determine experiment
        if exp is None:
            experiment = self.experiment
        else:
            experiment = exp

        # Get run number if not specified
        if run is None:
            run = int(input("Enter run number to view: "))

        # Validate facility
        facility = facility.upper()
        if facility not in ['S3DF', 'NERSC']:
            logger.error(f"Unknown facility: {facility}")
            logger.error("Use 'S3DF' or 'NERSC'")
            raise ValueError("Invalid facility")

        logger.info("Launching image viewer:")
        logger.info(f"  Facility: {facility}")
        logger.info(f"  Experiment: {experiment}")
        logger.info(f"  Run: {run}")
        logger.info(f"  Image type: {image_type}")
        if group:
            logger.info(f"  Group: {group}")

        # Build command based on facility
        if facility == 'S3DF':
            script = ("/sdf/group/lcls/ds/tools/mfx/scripts/cctbx/"
                      "image_viewer.py")
            cmd = (
                f"ssh -Yt {user}@s3dflogin "
                f"/sdf/group/lcls/ds/tools/cctbx/build/bin/python "
                f"{script} "
                f"-e {experiment} -f {facility} -t {image_type} "
                f"-r {run} "
                f"{'-g ' + group if group else ''} "
                f"{'-d' if debug else ''}"
            )
        elif facility == 'NERSC':
            # Check SSH proxy
            logger.warning("Have you renewed your SSH token today?")
            token = input("(y/n)? ")
            if token.lower() == "n":
                self.sshproxy(user)

            script = ("/global/cfs/cdirs/lcls/mfxopr/scripts/cctbx/"
                      "image_viewer.py")
            cmd = (
                f"ssh -Yt {user}@perlmutter-p1.nersc.gov "
                f"python {script} "
                f"-e {experiment} -f {facility} -t {image_type} "
                f"-r {run} "
                f"{'-g ' + group if group else ''} "
                f"{'-d' if debug else ''}"
            )

        logger.info(f"Executing: {cmd}")
        logger.info("Image viewer will open in new window...")

        os.system(cmd)

    def indexing(
            self,
            user: str,
            facility: str = 'S3DF',
            exp: Optional[str] = None,
            run: Optional[int] = None,
            group: str = '001_rg001',
            debug: bool = False):
        """
        Submit indexing job for diffraction data.

        Processes diffraction images to determine crystal orientations
        and unit cell parameters. Runs as batch job on specified
        computing facility.

        Parameters
        ----------
        user : str
            Username for job submission
        facility : str, optional
            Computing facility: 'S3DF' or 'NERSC'.
            Default is 'S3DF'.
        exp : str, optional
            Experiment name. If None, uses instance experiment.
            Default is None.
        run : int, optional
            Run number to process. If None, prompts user.
            Default is None.
        group : str, optional
            Processing group identifier for organizing results.
            Format: '{trial}_{rungroup}'
            Example: '001_rg001' = trial 1, run group 1
            Default is '001_rg001'.
        debug : bool, optional
            Enable verbose debug output in logs.
            Default is False.

        Returns
        -------
        None

        Notes
        -----
        Indexing Process:
        1. Read detector images from run
        2. Find Bragg peaks on each image
        3. Attempt to index peaks (determine orientation)
        4. Refine unit cell parameters
        5. Integrate indexed spots
        6. Write results to files

        Output Files:
        - indexed.refl: Reflection intensities
        - indexed.expt: Experiment geometry
        - indexing.log: Processing log
        - plots/: Diagnostic plots

        Processing Time:
        - S3DF: 10-60 minutes (depends on hits)
        - NERSC: 30-120 minutes
        - Scales with number of hits

        Indexing Parameters:
        - Space group: From input or auto-determined
        - Unit cell: Target or refined
        - Detector distance: From geometry
        - Beam center: From geometry

        Success Metrics:
        - Indexing rate: % of hits indexed
        - Unit cell consistency
        - Spot prediction residuals
        - Crystal mosaicity

        Group Naming:
        - Trial: Parameter set number (001, 002, etc .)
        - Run group: Subset of runs (rg001, rg002, etc.)
        - Allows parallel processing strategies

        Warnings
        --------
        Indexing requires accurate detector geometry.
        Refine geometry before large-scale processing.
        Monitor indexing rate - low rates indicate problems.

        Examples
        --------
        Index single run on S3DF:
        >>> cctbx_obj = cctbx()
        >>> cctbx_obj.indexing(
        ...     user='myuser',
        ...     facility='S3DF',
        ...     run=100,
        ...     group='001_rg001'
        ... )

        Index on NERSC with debug:
        >>> cctbx_obj.sshproxy('myuser')
        >>> cctbx_obj.indexing(
        ...     user='myuser',
        ...     facility='NERSC',
        ...     run=100,
        ...     group='002_rg001',
        ...     debug=True
        ... )

        See Also
        --------
        merge : Merge indexed data
        geom_refine : Refine detector geometry
        """
        # Determine experiment
        if exp is None:
            experiment = self.experiment
        else:
            experiment = exp

        # Get run number if not specified
        if run is None:
            run = int(input("Enter run number to index: "))

        # Validate facility
        facility = facility.upper()
        if facility not in ['S3DF', 'NERSC']:
            logger.error(f"Unknown facility: {facility}")
            raise ValueError("Invalid facility")

        logger.info("Submitting indexing job:")
        logger.info(f"  Facility: {facility}")
        logger.info(f"  Experiment: {experiment}")
        logger.info(f"  Run: {run}")
        logger.info(f"  Group: {group}")
        logger.info(f"  Debug: {debug}")

        # Build submission command
        if facility == 'S3DF':
            script = "/sdf/group/lcls/ds/tools/mfx/scripts/cctbx/index.sh"
            cmd = (
                f"ssh {user}@s3dflogin "
                f"'{script} {experiment} {run} {group} "
                f"{'-d' if debug else ''}'"
            )
        elif facility == 'NERSC':
            # Check SSH proxy
            logger.warning("Have you renewed your SSH token today?")
            token = input("(y/n)? ")
            if token.lower() == "n":
                self.sshproxy(user)

            script = ("/global/cfs/cdirs/lcls/mfxopr/scripts/cctbx/"
                      "index.sh")
            cmd = (
                f"ssh {user}@perlmutter-p1.nersc.gov "
                f"'{script} {experiment} {run} {group} "
                f"{'-d' if debug else ''}'"
            )

        logger.info(f"Executing: {cmd}")
        result = os.system(cmd)

        if result == 0:
            logger.info("Indexing job submitted successfully")
            logger.info(f"Monitor with: squeue -u {user}")
            logger.info(f"Results: {experiment}/scratch/{group}/")
        else:
            logger.error(f"Indexing submission failed (code {result})")

    def merge(
            self,
            user: str,
            facility: str = 'S3DF',
            exp: Optional[str] = None,
            group: str = '001_rg001',
            debug: bool = False):
        """
        Merge indexed data into structure factors.

        Combines reflections from multiple crystals into single dataset
        of structure factor amplitudes for structure determination.

        Parameters
        ----------
        user : str
            Username for job submission
        facility : str, optional
            Computing facility: 'S3DF' or 'NERSC'.
            Default is 'S3DF'.
        exp : str, optional
            Experiment name. If None, uses instance experiment.
            Default is None.
        group : str, optional
            Processing group containing indexed data to merge.
            Default is '001_rg001'.
        debug : bool, optional
            Enable verbose debug output.
            Default is False.

        Returns
        -------
        None

        Notes
        -----
        Merging Process:
        1. Read all indexed reflections in group
        2. Apply scaling corrections
        3. Resolve symmetry-equivalent reflections
        4. Merge equivalent observations
        5. Calculate structure factors
        6. Write MTZ file for refinement

        Scaling:
        - Accounts for crystal-to-crystal variation
        - Corrects for beam decay
        - Normalizes intensities
        - Rejects outliers

        Output Files:
        - merged.mtz: Structure factors (CCP4 format)
        - scaling.log: Scaling statistics
        - plots/: Scaling diagnostic plots
        - stats.txt: Merging statistics

        Quality Metrics:
        - R-split: Agreement between half-datasets
        - CC1/2: Correlation coefficient
        - I/σ(I): Signal-to-noise ratio
        - Completeness: % of unique reflections
        - Multiplicity: Average observations per reflection

        Typical Statistics (good data):
        - R-split < 0.10 at high resolution
        - CC1/2 > 0.50 at resolution limit
        - I/σ(I) > 2.0 at cutoff
        - Completeness > 90%

        Processing Time:
        - S3DF: 30-120 minutes
        - NERSC: 1-3 hours
        - Depends on dataset size

        Warnings
        --------
        Merging requires completed indexing jobs.
        Check indexing statistics before merging.
        Poor scaling may indicate geometry problems.

        Examples
        --------
        Merge on S3DF:
        >>> cctbx_obj = cctbx()
        >>> cctbx_obj.merge(
        ...     user='myuser',
        ...     facility='S3DF',
        ...     group='001_rg001'
        ... )

        Merge on NERSC with debug:
        >>> cctbx_obj.sshproxy('myuser')
        >>> cctbx_obj.merge(
        ...     user='myuser',
        ...     facility='NERSC',
        ...     group='002_rg001',
        ...     debug=True
        ... )

        See Also
        --------
        indexing : Generate data to merge
        geom_refine : Optimize geometry before merging
        """
        # Determine experiment
        if exp is None:
            experiment = self.experiment
        else:
            experiment = exp

        # Validate facility
        facility = facility.upper()
        if facility not in ['S3DF', 'NERSC']:
            logger.error(f"Unknown facility: {facility}")
            raise ValueError("Invalid facility")

        logger.info("Submitting merging job:")
        logger.info(f"  Facility: {facility}")
        logger.info(f"  Experiment: {experiment}")
        logger.info(f"  Group: {group}")
        logger.info(f"  Debug: {debug}")

        # Build submission command
        if facility == 'S3DF':
            script = "/sdf/group/lcls/ds/tools/mfx/scripts/cctbx/merge.sh"
            cmd = (
                f"ssh {user}@s3dflogin "
                f"'{script} {experiment} {group} "
                f"{'-d' if debug else ''}'"
            )
        elif facility == 'NERSC':
            # Check SSH proxy
            logger.warning("Have you renewed your SSH token today?")
            token = input("(y/n)? ")
            if token.lower() == "n":
                self.sshproxy(user)

            script = ("/global/cfs/cdirs/lcls/mfxopr/scripts/cctbx/"
                      "merge.sh")
            cmd = (
                f"ssh {user}@perlmutter-p1.nersc.gov "
                f"'{script} {experiment} {group} "
                f"{'-d' if debug else ''}'"
            )

        logger.info(f"Executing: {cmd}")
        result = os.system(cmd)

        if result == 0:
            logger.info("Merging job submitted successfully")
            logger.info(f"Monitor with: squeue -u {user}")
            logger.info(f"Results: {experiment}/results/{group}/")
        else:
            logger.error(f"Merging submission failed (code {result})")

    def geom_refine(
            self,
            user: str,
            facility: str = 'S3DF',
            group: str = '001_rg001',
            level: Optional[int] = 0,
            exp: Optional[str] = None):
        """
        Refine detector geometry from indexed diffraction data.

        Optimizes detector panel positions and orientations to minimize
        spot prediction residuals, improving indexing and integration
        accuracy.

        Parameters
        ----------
        user : str
            Username for job submission
        facility : str, optional
            Computing facility: 'S3DF' or 'NERSC'.
            Default is 'S3DF'.
        group : str, optional
            Processing group with indexed data for refinement.
            Default is '001_rg001'.
        level : int, optional
            Refinement hierarchy level:
            - 0: Whole detector (6 DOF)
            - 1: Panel groups (multiple DOF)
            - 2: Individual panels (highest detail)
            - None: All levels sequentially
            Default is 0 (whole detector).
        exp : str, optional
            Experiment name. If None, uses instance experiment.
            Default is None.

        Returns
        -------
        None

        Notes
        -----
        Refinement Levels:

        Level 0 (Whole Detector):
        - 6 degrees of freedom
        - 3 translations (x, y, z)
        - 3 rotations (rx, ry, rz)
        - Fast refinement
        - Good for initial geometry

        Level 1 (Panel Groups):
        - Refine groups of panels
        - Detector-dependent grouping
        - More parameters than level 0
        - Corrects for misalignments

        Level 2 (Individual Panels):
        - Each panel refined independently
        - Maximum flexibility
        - Hundreds of parameters
        - Best accuracy but slowest
        - Risk of overfitting

        Refinement Process:
        1. Read indexed reflections
        2. Predict spot positions from current geometry
        3. Calculate residuals (predicted - observed)
        4. Optimize geometry to minimize residuals
        5. Write refined geometry file

        Output Files:
        - refined.expt: Updated geometry
        - refinement.log: Optimization details
        - before_after.pdf: Residual comparison plots
        - geometry_shifts.txt: Parameter changes

        Quality Metrics:
        - RMS residual: Should decrease
        - Indexing rate: May improve
        - Unit cell consistency: Should improve
        - Systematic shifts: Should be corrected

        Typical Workflow:
        1. Initial indexing with approximate geometry
        2. Level 0 refinement (whole detector)
        3. Re-index with refined geometry
        4. Level 1/2 refinement if needed
        5. Final re-indexing

        Processing Time:
        - Level 0: 10-30 minutes
        - Level 1: 30-90 minutes
        - Level 2: 1-4 hours
        - All levels: 2-5 hours

        Warnings
        --------
        Requires high-quality indexed data (>1000 patterns).
        Level 2 refinement can overfit with insufficient data.
        Always validate refined geometry with test dataset.

        Examples
        --------
        Whole detector refinement:
        >>> cctbx_obj = cctbx()
        >>> cctbx_obj.geom_refine(
        ...     user='myuser',
        ...     facility='S3DF',
        ...     group='001_rg001',
        ...     level=0
        ... )

        Panel group refinement:
        >>> cctbx_obj.geom_refine(
        ...     user='myuser',
        ...     group='001_rg001',
        ...     level=1
        ... )

        Full hierarchical refinement:
        >>> cctbx_obj.geom_refine(
        ...     user='myuser',
        ...     group='001_rg001',
        ...     level=None  # All levels
        ... )

        On NERSC:
        >>> cctbx_obj.sshproxy('myuser')
        >>> cctbx_obj.geom_refine(
        ...     user='myuser',
        ...     facility='NERSC',
        ...     group='001_rg001',
        ...     level=0
        ... )

        See Also
        --------
        indexing : Generate data for refinement
        merge : Use refined geometry for better merging
        """
        # Determine experiment
        if exp is None:
            experiment = self.experiment
        else:
            experiment = exp

        # Validate facility
        facility = facility.upper()
        if facility not in ['S3DF', 'NERSC']:
            logger.error(f"Unknown facility: {facility}")
            raise ValueError("Invalid facility")

        logger.info("Submitting geometry refinement job:")
        logger.info(f"  Facility: {facility}")
        logger.info(f"  Experiment: {experiment}")
        logger.info(f"  Group: {group}")
        if level is not None:
            logger.info(f"  Level: {level}")
        else:
            logger.info("  Level: All (hierarchical)")

        # Build submission command
        level_arg = str(level) if level is not None else 'all'

        if facility == 'S3DF':
            script = ("/sdf/group/lcls/ds/tools/mfx/scripts/cctbx/"
                      "geom_refine.sh")
            cmd = (
                f"ssh {user}@s3dflogin "
                f"'{script} {experiment} {group} {level_arg}'"
            )
        elif facility == 'NERSC':
            # Check SSH proxy
            logger.warning("Have you renewed your SSH token today?")
            token = input("(y/n)? ")
            if token.lower() == "n":
                self.sshproxy(user)

            script = ("/global/cfs/cdirs/lcls/mfxopr/scripts/cctbx/"
                      "geom_refine.sh")
            cmd = (
                f"ssh {user}@perlmutter-p1.nersc.gov "
                f"'{script} {experiment} {group} {level_arg}'"
            )

        logger.info(f"Executing: {cmd}")
        result = os.system(cmd)

        if result == 0:
            logger.info("Geometry refinement job submitted")
            logger.info(f"Monitor with: squeue -u {user}")
            logger.info(f"Results: {experiment}/scratch/{group}/geom/")
            logger.info("Use refined.expt for subsequent processing")
        else:
            logger.error(f"Refinement submission failed (code {result})")


    def xfel_gui(
        self,
        user: str,
        facility: str = "NERSC",
        exp: str  = '',
        debug: bool = False,
<<<<<<< HEAD
    ):
        """
        Launch CCTBX XFEL GUI.
=======
        ):
        """Launch CCTBX XFEL GUI.
>>>>>>> 91ff2e2303b44c05a355cf66fd73da3938e68c26

        Parameters
        ----------
        user: str
            Username for computer account at facility.

        facility: str
            Default: "NERSC". Options: "S3DF, NERSC".

        exp: str
            Experiment number in format 'mfxp1047723'.
            If none selected default is the current experiment.

        debug: bool
            Default: False.
        """
        if exp != '':
            experiment = exp
        else:
            experiment = self.experiment

        facility = facility.upper()

        cmd = (
            f"ssh -Yt {user}@s3dflogin "
            f"/sdf/group/lcls/ds/tools/mfx/scripts/cctbx/cctbx.sh "
            f"{user} {experiment} {facility} 1 {str(debug)} "
            )

        logging.info(cmd)

        if facility == 'NERSC':
            logging.warning(f"Have you renewed your token with sshproxy today?")
            token = input("(y/n)? ")

            if token.lower() == "n":
                self.sshproxy(user)

        if debug:
            os.system(cmd)
        else:
            subprocess.Popen(
                cmd, shell=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    def notch_check(self, user, runs=[]):
        if len(runs) > 0:
            run_list = []
            for run in runs:
                run_list.append(f'{experiment}:{run}')
            logging.info(f'Selected runs: {run_list}')
            runlist = ' '
            runlist = runlist.join(run_list)
            logging.info(f'Selected runs: {runlist}')
        else:
            logging.warning(f'No selected runs. Program will exit.')
            sys.exit()

        proc = [
            f'ssh -YAC {user}@s3dflogin '
            f'/sdf/group/lcls/ds/tools/mfx/scripts/cctbx/cctbx_notch_check.sh "{self.runlist}"'
            ]

        logging.info(proc)

        subprocess.Popen(
            proc, shell=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


# Convenience module-level instance
cctbx_instance = cctbx()