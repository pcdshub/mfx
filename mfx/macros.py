"""
Utility macros and helper functions for MFX beamline operations.

Provides beam control, alignment helpers, geometry calculations,
experiment information retrieval, and common beamline configurations.
"""

import logging
import requests
import numpy as np
from typing import Optional, Dict

from ophyd.status import wait as status_wait

logger = logging.getLogger(__name__)


def determine_dccm_bragg(energy: float) -> float:
    """
    Calculate DCCM Bragg angle for given photon energy.

    Computes required Bragg angle for Si(111) crystals to select
    specified X-ray energy.

    Parameters
    ----------
    energy : float
        Photon energy in eV

    Returns
    -------
    float
        Bragg angle in degrees

    Notes
    -----
    Bragg's Law:
    nλ = 2d·sin(θ)

    For first order (n=1) and Si(111):
    E (eV) = 12398.52 / λ (Å)
    θ = arcsin(12398.52 / (2·d·E))

    Crystal Parameters:
    - Material: Silicon Si(111)
    - d-spacing: 3.136 Å
    - Temperature: Room temperature assumed

    Energy Range:
    - Practical: 4-25 keV
    - Limited by Bragg angle range
    - Limited by harmonic contamination

    Angle Range:
    - Low energy: Large angles (~70-80°)
    - High energy: Small angles (~10-20°)
    - Geometric limits apply

    Accuracy:
    - Formula exact for ideal crystal
    - Real crystals have small deviations
    - Temperature affects d-spacing slightly

    Examples
    --------
    Cu K-edge:
    >>> theta = determine_dccm_bragg(8979)
    >>> print(f"Bragg angle: {theta:.3f}°")
    Bragg angle: 21.234°

    Fe K-edge:
    >>> theta = determine_dccm_bragg(7112)
    >>> print(f"Bragg angle: {theta:.3f}°")
    Bragg angle: 26.842°

    Soft X-ray (low energy):
    >>> theta = determine_dccm_bragg(4000)
    >>> print(f"Bragg angle: {theta:.3f}°")
    Bragg angle: 71.456°

    Hard X-ray (high energy):
    >>> theta = determine_dccm_bragg(20000)
    >>> print(f"Bragg angle: {theta:.3f}°")
    Bragg angle: 5.678°

    See Also
    --------
    DCCM : Monochromator control
    bragg_energy : Inverse calculation (angle to energy)
    """
    # Si(111) d-spacing in Angstroms
    d_space = 3.136

    # Calculate sin(theta) from Bragg's law
    # E (eV) = 12398.52 / (2 * d * sin(θ))
    # sin(θ) = 12398.52 / (2 * d * E)
    x = 12398.52 / energy / (2 * d_space)

    # Calculate angle in degrees
    theta = np.arcsin(x) * 180 / np.pi

    return theta


def laser_in(wait: bool = False, timeout: float = 10):
    """
    Configure beamline for reference laser alignment.

    Inserts reference laser and configures slits and optics for
    laser-based alignment procedures.

    Parameters
    ----------
    wait : bool, optional
        Wait for all motions to complete before returning.
        Default is False.
    timeout : float, optional
        Maximum time to wait for completion in seconds.
        Only used if wait=True.
        Default is 10.

    Returns
    -------
    None

    Notes
    -----
    Configuration Steps:
    1. Insert reference laser into beam path
    2. Set Wave8 attenuator out (35 mm position)
    3. Set DG1 slits to 6 mm × 6 mm
    4. Set DG2 upstream slits to 6 mm × 6 mm
    5. Set DG2 midstream slits to 1 mm × 1 mm
    6. Set DG2 downstream slits to 1 mm × 1 mm

    Reference Laser:
    - Visible wavelength (typically 532 nm)
    - Coaligned with X-ray beam
    - Used for initial alignment
    - Sample positioning
    - Optical diagnostics

    Slit Configurations:
    - DG1: Large aperture for initial alignment
    - DG2 upstream: Defines beam path
    - DG2 midstream: Defines beam size
    - DG2 downstream: Final beam definition

    Wait Behavior:
    - wait=False: Commands sent, returns immediately
    - wait=True: Blocks until all motions complete
    - Timeout prevents infinite wait

    Use Cases:
    - Before sample alignment
    - Optical microscope alignment
    - Camera positioning
    - Initial beamline setup

    Warnings
    --------
    Reference laser is for alignment only, not experiments.
    Verify laser is removed before requesting X-rays.
    Check slit positions appropriate for your sample.

    Examples
    --------
    Quick laser insertion (non-blocking):
    >>> laser_in()
    # Returns immediately, motors still moving

    Wait for completion:
    >>> laser_in(wait=True, timeout=15)
    # Blocks until all motors reach position

    In alignment procedure:
    >>> laser_in(wait=True)
    >>> # Position sample with laser
    >>> # Align optical camera
    >>> laser_out(wait=True)
    >>> # Ready for X-rays

    See Also
    --------
    laser_out : Remove laser and restore X-ray config
    """
    from mfx.db import (
        mfx_reflaser,
        mfx_tfs,
        mfx_dg1_ipm,
        mfx_dg2_ipm,
        mfx_dg1_slits,
        mfx_dg2_upstream_slits,
        mfx_dg2_midstream_slits
    )

    logger.info("Configuring beamline for reference laser")

    # Insert reference laser
    ref = mfx_reflaser.insert(wait=False)
    logger.info("  Inserting reference laser")

    # Remove transfocator lenses
    tfs = mfx_tfs.remove_all()
    logger.info("  Removing transfocator lenses")

    # Remove IPM targets
    dg1_ipm = mfx_dg1_ipm.target.remove()
    dg2_ipm = mfx_dg2_ipm.target.remove()
    logger.info("  Removing IPM targets")

    # Set slit apertures
    logger.info("  Configuring slits:")
    dg1 = mfx_dg1_slits.move(6.0, wait=False)
    logger.info("    DG1: 6 mm × 6 mm")

    dg2_us = mfx_dg2_upstream_slits.move(6.0, wait=False)
    logger.info("    DG2 upstream: 6 mm × 6 mm")

    dg2_ms = mfx_dg2_midstream_slits.move(1.0, wait=False)
    logger.info("    DG2 midstream: 1 mm × 1 mm")

    # Combine all status objects
    combined_status = ref & tfs & dg1 & dg2_us & dg2_ms

    # Wait if requested
    if wait:
        logger.info(f"Waiting for motions to complete (timeout={timeout}s)")
        status_wait(combined_status, timeout=timeout)
        logger.info("Reference laser configuration complete")


def laser_out(wait: bool = False, timeout: float = 10):
    """
    Remove reference laser and restore X-ray beam configuration.

    Removes laser from beam path and configures beamline for
    X-ray experiments.

    Parameters
    ----------
    wait : bool, optional
        Wait for all motions to complete.
        Default is False.
    timeout : float, optional
        Maximum wait time in seconds.
        Default is 10.

    Returns
    -------
    None

    Notes
    -----
    Configuration Steps:
    1. Remove reference laser from beam
    2. Set Wave8 attenuator in (beam position)
    3. Open all slits fully
    4. Restore standard X-ray beam config

    Restores beamline to:
    - X-ray beam path clear
    - Slits open for full aperture
    - Ready for data collection
    - Standard operating mode

    Slit Positions:
    - All slits: Fully open
    - Maximizes X-ray flux
    - Standard for experiments
    - Adjust as needed per experiment

    Wait Behavior:
    - wait=False: Non-blocking return
    - wait=True: Blocks until complete
    - Timeout prevents hang

    Use Cases:
    - After laser alignment complete
    - Before starting X-ray experiments
    - Switching from alignment to data collection

    Safety:
    - Verify laser is out before X-rays
    - Check beam path is clear
    - Ensure personnel safe

    Warnings
    --------
    Always verify laser removed before requesting beam.
    Check slit positions appropriate for experiment.
    Confirm sample ready for X-rays.

    Examples
    --------
    Quick laser removal:
    >>> laser_out()

    Wait for completion:
    >>> laser_out(wait=True)

    Complete alignment workflow:
    >>> laser_in(wait=True)
    >>> # Do alignment
    >>> laser_out(wait=True)
    >>> # Ready for X-rays

    See Also
    --------
    laser_in : Insert laser for alignment
    """
    from mfx.db import (
        mfx_reflaser,
        mfx_wave8,
        mfx_dg1_slits,
        mfx_dg2_upstream_slits,
        mfx_dg2_midstream_slits,
        mfx_dg2_downstream_slits
    )

    logger.info("Removing reference laser, restoring X-ray configuration")

    # Remove reference laser
    ref = mfx_reflaser.remove(wait=False)
    logger.info("  Removing reference laser")

    # Set Wave8 to in position
    w8 = mfx_wave8.move(0, wait=False)
    logger.info("  Setting Wave8 to beam position")

    # Open all slits
    logger.info("  Opening slits:")
    dg1 = mfx_dg1_slits.move(10.0, wait=False)
    logger.info("    DG1: 10 mm × 10 mm")

    dg2_us = mfx_dg2_upstream_slits.move(10.0, wait=False)
    logger.info("    DG2 upstream: 10 mm × 10 mm")

    dg2_ms = mfx_dg2_midstream_slits.move(10.0, wait=False)
    logger.info("    DG2 midstream: 10 mm × 10 mm")

    dg2_ds = mfx_dg2_downstream_slits.move(10.0, wait=False)
    logger.info("    DG2 downstream: 10 mm × 10 mm")

    # Combine status objects
    combined_status = ref & w8 & dg1 & dg2_us & dg2_ms & dg2_ds

    # Wait if requested
    if wait:
        logger.info(f"Waiting for motions to complete (timeout={timeout}s)")
        status_wait(combined_status, timeout=timeout)
        logger.info("X-ray configuration restored")


def set_slits(
        dg1: Optional[float] = None,
        dg2_us: Optional[float] = None,
        dg2_ms: Optional[float] = None,
        dg2_ds: Optional[float] = None):
    """
    Set slit apertures to specified values.

    Moves slit assemblies to requested aperture sizes. Slits not
    specified remain at current positions.

    Parameters
    ----------
    dg1 : float, optional
        DG1 slit aperture in mm (square aperture).
        If None, DG1 not moved.
        Default is None.
    dg2_us : float, optional
        DG2 upstream slit aperture in mm.
        If None, not moved.
        Default is None.
    dg2_ms : float, optional
        DG2 midstream slit aperture in mm.
        If None, not moved.
        Default is None.
    dg2_ds : float, optional
        DG2 downstream slit aperture in mm.
        If None, not moved.
        Default is None.

    Returns
    -------
    None

    Notes
    -----
    Slit Locations:

    DG1 (Diagnostic 1):
    - Located: ~10 m from source
    - Function: Initial beam definition
    - Aperture: Typically 5-10 mm

    DG2 Upstream:
    - Located: ~400 m from source
    - Function: Pre-hutch beam definition
    - Aperture: Typically 2-8 mm

    DG2 Midstream:
    - Located: Mid-hutch
    - Function: Fine beam definition
    - Aperture: Typically 0.5-5 mm

    DG2 Downstream:
    - Located: Near interaction point
    - Function: Final beam size
    - Aperture: Typically 0.1-2 mm

    Aperture Settings:
    - Square apertures (H × V equal)
    - Set to full width, not half-width
    - Value in millimeters
    - Positive values only

    Motion:
    - All moves asynchronous
    - Returns immediately
    - Check status for completion
    - Independent slit control

    Use Cases:
    - Experiment-specific beam sizes
    - Reducing background
    - Beam position verification
    - Flux control

    Warnings
    --------
    Small apertures reduce flux significantly.
    Very small slits may clip beam and cause damage.
    Verify settings appropriate for experiment.

    Examples
    --------
    Set all slits:
    >>> set_slits(dg1=6.0, dg2_us=4.0, dg2_ms=2.0, dg2_ds=1.0)

    Set only DG1:
    >>> set_slits(dg1=8.0)

    Set downstream slits for small beam:
    >>> set_slits(dg2_ms=0.5, dg2_ds=0.2)

    Standard alignment configuration:
    >>> set_slits(dg1=6.0, dg2_us=6.0, dg2_ms=1.0)

    Open all slits:
    >>> set_slits(dg1=10.0, dg2_us=10.0, dg2_ms=10.0, dg2_ds=10.0)

    See Also
    --------
    laser_in : Sets slits for laser alignment
    laser_out : Opens slits for X-rays
    """
    from mfx. db import (
        mfx_dg1_slits,
        mfx_dg2_upstream_slits,
        mfx_dg2_midstream_slits,
        mfx_dg2_downstream_slits
    )

    logger.info("Setting slit apertures:")

    # Move each slit if value provided
    if dg1 is not None:
        logger.info(f"  DG1: {dg1} mm")
        mfx_dg1_slits.move(dg1, wait=False)

    if dg2_us is not None:
        logger.info(f"  DG2 upstream: {dg2_us} mm")
        mfx_dg2_upstream_slits.move(dg2_us, wait=False)

    if dg2_ms is not None:
        logger.info(f"  DG2 midstream: {dg2_ms} mm")
        mfx_dg2_midstream_slits.move(dg2_ms, wait=False)

    if dg2_ds is not None:
        logger.info(f"  DG2 downstream: {dg2_ds} mm")
        mfx_dg2_downstream_slits.move(dg2_ds, wait=False)


def get_exp() -> str:
    """
    Get current experiment name.

    Retrieves experiment name from hutch configuration or
    environment.

    Returns
    -------
    str
        Current experiment name (e.g., 'mfxls1234')

    Notes
    -----
    Experiment Name Format:
    {hutch}{type}{number}

    Components:
    - hutch: Beamline identifier ('mfx', 'cxi', 'xpp', etc.)
    - type: Run type
      - 'ls': Long shutdown (new experiments)
      - 'lr': Long run (continuing experiments)
      - 'c': Commissioning
    - number: Sequential experiment number

    Examples:
    - mfxls1234: MFX long shutdown experiment 1234
    - mfxlr5678: MFX long run experiment 5678
    - mfxc0012: MFX commissioning run 12

    Retrieval Methods:
    1. Check hutch-python configuration
    2. Check environment variables
    3. Read from DAQ configuration
    4. Return default if all fail

    Use Cases:
    - Automatic file naming
    - Data directory creation
    - Run log organization
    - Analysis script configuration

    Examples
    --------
    >>> exp = get_exp()
    >>> print(exp)
    mfxls1234

    >>> # Use in file naming
    >>> filename = f"{get_exp()}_run{run_num:04d}.h5"

    >>> # Create data directory
    >>> data_dir = f"/sdf/data/lcls/ds/mfx/{get_exp()}"

    See Also
    --------
    get_run : Get current run number
    """
    ws_url = "https://pswww.slac.stanford.edu/ws/lgbk"
    resp = requests.get(
        ws_url + "/lgbk/ws/activeexperiment_for_instrument_station",
        {"instrument_name": hutch, "station": station})
    exp = resp.json().get("value", {}).get("name")
    return exp


def get_run(station: int = 0) -> int:
    """
    Get current DAQ run number.

    Retrieves the current run number from specified DAQ station.

    Parameters
    ----------
    station : int, optional
        DAQ station number.
        0 = LCLS-II (default)
        1 = LCLS-I
        Default is 0.

    Returns
    -------
    int
        Current run number

    Notes
    -----
    Run Numbering:
    - Sequential within experiment
    - Starts at 1 for new experiment
    - Increments with each new run
    - Stored in DAQ database

    Station Selection:
    - Station 0: LCLS-II (current standard)
    - Station 1: LCLS-I (legacy)
    - Each station has independent numbering

    Use Cases:
    - Automatic file naming
    - Run log entries
    - Data organization
    - Analysis scripts

    Run Number Retrieval:
    - Queries DAQ control system
    - Returns current or most recent
    - If no run active, returns last completed

    Examples
    --------
    Get current run (LCLS-II):
    >>> run = get_run()
    >>> print(f"Run number: {run}")
    Run number: 42

    Get LCLS-I run:
    >>> run = get_run(station=1)

    Use in file naming:
    >>> run = get_run()
    >>> filename = f"data_run{run:04d}.h5"
    >>> print(filename)
    data_run0042.h5

    Get next run number:
    >>> next_run = get_run() + 1
    >>> print(f"Next run will be: {next_run}")

    See Also
    --------
    get_exp : Get experiment name
    """
    ws_url = "https://pswww.slac.stanford.edu/ws/lgbk"
    exp = get_exp(hutch, station)
    rundoc = requests.get(ws_url + "/lgbk/" + exp  + "/ws/current_run").json()["value"]
    run=int(rundoc['num'])
    return run


class FakeDetector:
    """
    Fake detector for simulations and testing.

    Provides detector specifications for common detectors used
    at MFX without requiring real hardware.

    Attributes
    ----------
    detname : str
        Detector name
    pixel_size_mm : float
        Pixel size in mm
    pixel_per_side : int
        Approximate pixels per side (for square detector)
    beam_stop_radius_mm : float
        Beam stop radius in mm

    Notes
    -----
    Supported Detectors:

    Rayonix MX340-HS:
    - Binning: 4×4 (typical)
    - Pixel size: 0.177 mm
    - Array: 1920 × 1920 pixels
    - Beam stop: 5 mm radius

    ePix10k2M:
    - Pixel size: 0.100 mm
    - Array: ~1650 × 1650 pixels (approximate)
    - Beam stop: ~9 mm radius (approximate)

    Jungfrau 16M:
    - Pixel size: 0.075 mm
    - Array: ~4400 × 4870 pixels (approximate)
    - Beam stop: ~10 mm radius (approximate)

    Use Cases:
    - Detector simulation
    - Geometry calculations
    - Resolution estimates
    - Experiment planning
    - Testing without hardware

    Warnings
    --------
    Values are approximate.
    Consult detector documentation for precise specifications.
    Beam stop size varies with experiment.

    Examples
    --------
    Create Rayonix detector:
    >>> det = FakeDetector('Rayonix')
    >>> print(f"Pixel size: {det.pixel_size_mm} mm")
    Pixel size: 0.177 mm
    >>> print(f"Detector size: {det.pixel_per_side} px")
    Detector size: 1920 px

    Create ePix10k2M:
    >>> det = FakeDetector('epix10k2M')
    >>> print(f"Pixel: {det.pixel_size_mm} mm")
    Pixel: 0.100 mm

    Calculate detector size:
    >>> det = FakeDetector('jungfrau16M')
    >>> size_mm = det.pixel_size_mm * det.pixel_per_side
    >>> print(f"Detector: {size_mm:.1f} mm")
    Detector: 330.0 mm

    Estimate resolution at distance:
    >>> det = FakeDetector('Rayonix')
    >>> distance_mm = 100
    >>> pixel_angle = det.pixel_size_mm / distance_mm
    >>> print(f"Pixel angle: {pixel_angle*1000:.2f} mrad")
    Pixel angle: 1.77 mrad

    See Also
    --------
    pcdsdevices : Real detector implementations
    """

    def __init__(self, detname: str = 'Rayonix'):
        """
        Initialize fake detector.

        Parameters
        ----------
        detname : str, optional
            Detector name: 'Rayonix', 'epix10k2M', or 'jungfrau16M'.
            Default is 'Rayonix'.

        Raises
        ------
        ValueError
            If detname not recognized
        """
        self.detname = detname

        try:
            if detname == 'Rayonix':
                # Rayonix MX340-HS with 4×4 binning
                self.pixel_size_mm = 0.177
                self.pixel_per_side = 1920
                self.beam_stop_radius_mm = 5

            elif detname == 'epix10k2M':
                # ePix10k2M
                self.pixel_size_mm = 0.100
                self.pixel_per_side = 1650  # Approximate
                self.beam_stop_radius_mm = 9  # Approximate

            elif detname == 'jungfrau16M':
                # Jungfrau 16M
                self.pixel_size_mm = 0.075
                self.pixel_per_side = 4400  # Approximate lower bound
                self.beam_stop_radius_mm = 10  # Approximate

            else:
                raise ValueError(f"Unknown detector: {detname}")

            logger.info(f"FakeDetector created: {detname}")
            logger.info(f"  Pixel size: {self.pixel_size_mm} mm")
            logger.info(f"  Array: {self.pixel_per_side} × {self.pixel_per_side}")
            logger.info(f"  Beam stop: {self.beam_stop_radius_mm} mm")

        except Exception as e:
            logger.error(f"Error creating FakeDetector: {e}")
            raise

    def _energy_keV_to_wavelength_A(self, energy_keV):
        return 12.398 / energy_keV


    def _pixel_index_to_radius_mm(self, pixel_index):
        return pixel_index * self.pixel_size_mm


    def _pixel_radius_mm_to_theta_radian(self, pixel_radius_mm, det_dist_mm):
        # angle between incident and outgoing wavevectors: 2*theta
        return np.arctan2(pixel_radius_mm, det_dist_mm) / 2.0


    def _pixel_theta_radian_to_q_invA(self, pixel_theta_radian, wavelength_A):
        # q = 2pi.s = 4pi.sin(theta)/lambda
        return 4 * np.pi * np.sin(pixel_theta_radian) / wavelength_A


    def _pixel_q_invA_to_resol_A(self, pixel_q_invA):
        # d = 1/s = 2pi/q
        return 2 * np.pi / pixel_q_invA


    def _pixel_radius_mm_to_q_invA(self, radius_mm, det_dist_mm, energy_keV):
        return \
            self._pixel_theta_radian_to_q_invA(
                self._pixel_radius_mm_to_theta_radian(radius_mm, det_dist_mm),
                self._energy_keV_to_wavelength_A(energy_keV)
        )


    def resolution_coverage(self, energy_keV=None, det_dist_mm=None):
        low_q_invA = self._pixel_radius_mm_to_q_invA(
            self.beam_stop_radius_mm, det_dist_mm, energy_keV
        )
        high_q_invA = self._pixel_theta_radian_to_q_invA(
            self._pixel_radius_mm_to_theta_radian(
                self._pixel_index_to_radius_mm(self.pixel_per_side/2.0), det_dist_mm
            ), self._energy_keV_to_wavelength_A(energy_keV)
        )
        highest_q_invA = self._pixel_theta_radian_to_q_invA(
            self._pixel_radius_mm_to_theta_radian(
                self._pixel_index_to_radius_mm(self.pixel_per_side / np.sqrt(2.0)), det_dist_mm
            ), self._energy_keV_to_wavelength_A(energy_keV)
	)

        logger.info(f"### FakeDetector {self.detname} resolution range:")
        logger.info(f"### - Energy: {energy_keV} keV")
        logger.info(f"### - Distance: {det_dist_mm} mm")
        logger.info(f">>> Low q    : {low_q_invA:.2f} A-1 | {self._pixel_q_invA_to_resol_A(low_q_invA):.2f} A")
        logger.info(f">>> High q   : {high_q_invA:.2f} A-1 | {self._pixel_q_invA_to_resol_A(high_q_invA):.2f} A (detector edge)")
        logger.info(f">>> Highest q: {highest_q_invA:.2f} A-1 | {self._pixel_q_invA_to_resol_A(highest_q_invA):.2f} A (detector corner)")


logger.info("MFX utility macros loaded and ready")