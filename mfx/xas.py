"""X-ray Absorption Spectroscopy (XAS) utilities for MFX beamline."""

import logging
import time
import numpy as np
import os
import matplotlib.pyplot as plt
from typing import List, Optional, Tuple, Callable
from scipy.optimize import curve_fit

from hutch_python.utils import safe_load

logger = logging.getLogger(__name__)

# ==================== DCCM Initialization ====================

with safe_load('DCCM'):
    from mfx.dccm import DCCM
    dccm = DCCM(name='DCCM')


# ==================== Core XAS Functions ====================

def continuous_dccmscan(
        energies: List[float],
        pointTime: float = 1.0,
        move_vernier: bool = False,
        bidirectional: bool = False):
    """
    Perform continuous energy scan with DCCM.

    Moves DCCM through specified energies with optional vernier
    adjustment and bidirectional scanning. Does NOT start DAQ -
    use run_dccmscan() for automated data collection.

    Parameters
    ----------
    energies : List[float]
        Energy points in keV
    pointTime : float, optional
        Dwell time per energy point in seconds (default: 1.0)
    move_vernier : bool, optional
        Request vernier energy adjustment (default: False)
        If True, also adjusts undulator K parameter
    bidirectional : bool, optional
        Scan forward then backward (default: False)
        If True, scans energies then reversed energies

    Returns
    -------
    None

    Raises
    ------
    KeyboardInterrupt
        User can interrupt scan, will return to initial energy

    Notes
    -----
    Scan Procedure:
    1. Record initial DCCM energy
    2. For each energy in list:
       a. Move DCCM (with or without vernier)
       b. Wait pointTime seconds
    3. If bidirectional, repeat in reverse
    4. Return to initial energy

    Vernier Mode:
    - move_vernier=True: Uses energy_with_vernier
      - Adjusts DCCM crystals
      - Requests undulator K change
      - Maintains beam position/focus
    - move_vernier=False: Uses energy only
      - Only adjusts DCCM crystals
      - Faster but may lose beam

    Bidirectional Scanning:
    - Useful for checking hysteresis
    - Averages forward/backward scans
    - Doubles scan time

    Timing:
    - pointTime includes move time
    - Actual dwell = pointTime - move_time
    - Typical move time: 0.5-2 seconds

    Keyboard Interrupt:
    - Catches Ctrl+C gracefully
    - Returns to initial energy
    - Safe abort mechanism

    Examples
    --------
    Simple forward scan:
    >>> energies = np.linspace(7.0, 7.2, 21)  # 7.0-7.2 keV, 21 points
    >>> continuous_dccmscan(energies, pointTime=2.0)

    Scan with vernier:
    >>> continuous_dccmscan(energies, pointTime=1.0, move_vernier=True)

    Bidirectional scan:
    >>> continuous_dccmscan(energies, pointTime=1.0, bidirectional=True)

    See Also
    --------
    run_dccmscan : Automated scan with DAQ
    DCCMEnergy : DCCM energy control
    DCCMEnergyWithVernier : DCCM with vernier
    """
    # Record initial energy
    initial_energy = dccm.energy.wm()
    logger.info(f"Starting energy scan from {initial_energy:.4f} keV")

    try:
        # Forward scan
        for E in energies:
            if move_vernier:
                logger.info(f"Moving DCCM with vernier to {E:.4f} keV")
                dccm.energy_with_vernier.move(E, wait=True)
            else:
                logger.info(f"Moving DCCM to {E:.4f} keV")
                dccm.energy.move(E, wait=True)

            time.sleep(pointTime)

        # Bidirectional: reverse scan
        if bidirectional:
            logger.info("Starting reverse scan")
            for E in reversed(energies):
                if move_vernier:
                    logger.info(f"Moving DCCM with vernier to {E:.4f} keV")
                    dccm.energy_with_vernier.move(E, wait=True)
                else:
                    logger.info(f"Moving DCCM to {E:.4f} keV")
                    dccm.energy.move(E, wait=True)

                time.sleep(pointTime)

    except KeyboardInterrupt:
        logger.warning(
            "Scan interrupted by user. "
            f"Returning to initial energy: {initial_energy:.4f} keV"
        )

    finally:
        # Return to initial energy
        if move_vernier:
            dccm.energy_with_vernier.move(initial_energy, wait=True)
        else:
            dccm.energy.move(initial_energy, wait=True)

        logger.info(f"Returned to initial energy: {initial_energy:.4f} keV")


def run_dccmscan(
        energies: List[float],
        record: bool = True,
        pointTime: float = 1.0,
        move_vernier: bool = True,
        bidirectional: bool = False,
        **kwargs):
    """
    Run DCCM energy scan with automated DAQ control.

    Performs energy scan while collecting data with DAQ.
    Handles DAQ startup, scanning, and cleanup automatically.

    Parameters
    ----------
    energies : List[float]
        Energy points in keV
    record : bool, optional
        Enable data recording (default: True)
    pointTime : float, optional
        Dwell time per energy point in seconds (default: 1.0)
    move_vernier : bool, optional
        Request vernier energy adjustment (default: True)
    bidirectional : bool, optional
        Scan forward then backward (default: False)
    **kwargs
        Additional keyword arguments (reserved for future use)

    Returns
    -------
    None

    Raises
    ------
    KeyboardInterrupt
        User can interrupt, will stop DAQ and return safely

    Notes
    -----
    Scan Sequence:
    1. Configure DAQ
    2. Start DAQ in infinite mode (no event limit)
    3. Perform energy scan via continuous_dccmscan()
    4. End DAQ run
    5. Log completion

    DAQ Mode:
    - Uses begin_infinite() for continuous recording
    - Records all events during scan
    - No predetermined event count
    - Stopped manually after scan completes

    Data Output:
    - Run number automatically assigned
    - Energy stored in DAQ metadata
    - Data saved to standard location

    Scan Duration:
    - Forward: len(energies) × pointTime
    - Bidirectional: 2 × len(energies) × pointTime
    - Plus move overhead (~10%)

    Safety Features:
    - Keyboard interrupt handled gracefully
    - DAQ properly ended on interrupt
    - DCCM returned to initial energy
    - Status logged

    Typical Workflow:
    1. Plan energy range (pre-edge to post-edge)
    2. Calculate number of points
    3. Run scan with recording
    4. Analyze data offline

    Examples
    --------
    Standard XAS scan across Fe K-edge:
    >>> energies = np.linspace(7.0, 7.3, 61)  # 7.0-7.3 keV
    >>> run_dccmscan(energies, record=True, pointTime=1.0)

    Quick scan without recording:
    >>> energies = np.linspace(7.1, 7.15, 11)
    >>> run_dccmscan(energies, record=False, pointTime=0.5)

    High-resolution bidirectional scan:
    >>> energies = np.linspace(7.11, 7.13, 41)  # Fine scan
    >>> run_dccmscan(
    ...     energies,
    ...     record=True,
    ...     pointTime=2.0,
    ...     bidirectional=True
    ... )

    See Also
    --------
    continuous_dccmscan : Scan without DAQ
    build_xas_energy_list : Generate energy arrays
    """
    from mfx.db import daq

    logger.info(f"Starting DAQ-controlled energy scan, record={record}")

    try:
        # Configure and start DAQ
        daq.configure()
        daq.begin_infinite(record=record)

        # Get run number for logging
        runnum = daq._control.runnumber()
        logger.info(f"DAQ Run {runnum} started")

        # Allow DAQ to stabilize
        time.sleep(1)

        # Perform energy scan
        continuous_dccmscan(
            energies,
            pointTime=pointTime,
            move_vernier=move_vernier,
            bidirectional=bidirectional
        )

    except KeyboardInterrupt:
        logger.warning("Scan interrupted by user. Stopping DAQ")

    finally:
        # End DAQ run
        daq.end_run()
        logger.info("DAQ run complete!")


# ==================== Energy List Builders ====================

def build_xas_energy_list(
        pre_edge_start: float = 7.050,
        pre_edge_end: float = 7.095,
        edge_start: float = 7.100,
        edge_end: float = 7.140,
        post_edge_end: float = 7.200,
        pre_edge_spacing: float = 0.005,
        edge_spacing: float = 0.001,
        post_edge_spacing: float = 0.010) -> np.ndarray:
    """
    Build optimized energy list for XAS scan.

    Generates energy points with appropriate spacing for different
    regions of an absorption edge. Typical for XANES and EXAFS.

    Parameters
    ----------
    pre_edge_start : float, optional
        Start of pre-edge region in keV (default: 7.050)
    pre_edge_end : float, optional
        End of pre-edge region in keV (default: 7.095)
    edge_start : float, optional
        Start of edge region in keV (default: 7.100)
    edge_end : float, optional
        End of edge region in keV (default: 7.140)
    post_edge_end : float, optional
        End of post-edge region in keV (default: 7.200)
    pre_edge_spacing : float, optional
        Energy spacing in pre-edge in keV (default: 0.005)
    edge_spacing : float, optional
        Energy spacing near edge in keV (default: 0.001)
    post_edge_spacing : float, optional
        Energy spacing in post-edge in keV (default: 0.010)

    Returns
    -------
    np.ndarray
        Combined energy array in keV

    Notes
    -----
    XAS Regions:

    Pre-Edge (pre_edge_start to pre_edge_end):
    - Below absorption edge
    - Coarse spacing (typically 5 eV)
    - Establishes baseline
    - Identifies pre-edge features

    Edge (edge_start to edge_end):
    - Across absorption edge
    - Fine spacing (typically 1 eV)
    - Captures edge position
    - Resolves edge features (XANES)

    Post-Edge (edge_end to post_edge_end):
    - Above absorption edge
    - Medium spacing (typically 10 eV)
    - Extended for EXAFS
    - K-space more relevant here

    Default Values:
    - Optimized for Fe K-edge (7.112 keV)
    - Adjust for other elements
    - Edge at ~7.112 keV for Fe

    Total Points:
    - Pre-edge: ~10 points
    - Edge: ~40 points
    - Post-edge: ~6 points
    - Total: ~56 points

    Scan Time Estimate:
    - points × pointTime
    - 56 points × 1 s = 56 seconds
    - 56 points × 2 s = 112 seconds

    Element-Specific Examples:
    - Fe K-edge: 7.112 keV
    - Cu K-edge: 8.979 keV
    - Mn K-edge: 6.539 keV
    - Adjust ranges accordingly

    Examples
    --------
    Default Fe K-edge scan:
    >>> energies = build_xas_energy_list()
    >>> print(f"Total points: {len(energies)}")

    Custom Cu K-edge scan:
    >>> energies = build_xas_energy_list(
    ...     pre_edge_start=8.900,
    ...     pre_edge_end=8.960,
    ...     edge_start=8.970,
    ...     edge_end=9.020,
    ...     post_edge_end=9.100,
    ...     edge_spacing=0.001
    ... )

    High-resolution edge scan:
    >>> energies = build_xas_energy_list(
    ...     edge_start=7.105,
    ...     edge_end=7.120,
    ...     edge_spacing=0.0005  # 0.5 eV steps
    ... )

    Extended EXAFS:
    >>> energies = build_xas_energy_list(
    ...     post_edge_end=7.500,  # Extended to 400 eV above edge
    ...     post_edge_spacing=0.020  # Coarser spacing
    ... )

    See Also
    --------
    run_dccmscan : Run scan with energy list
    build_exafs_energy_list : K-space sampling for EXAFS
    """
    # Pre-edge region (coarse spacing)
    pre_edge = np.arange(
        pre_edge_start,
        pre_edge_end + pre_edge_spacing,
        pre_edge_spacing
    )

    # Edge region (fine spacing)
    edge = np.arange(
        edge_start,
        edge_end + edge_spacing,
        edge_spacing
    )

    # Post-edge region (medium spacing)
    post_edge = np.arange(
        edge_end + post_edge_spacing,
        post_edge_end + post_edge_spacing,
        post_edge_spacing
    )

    # Combine regions
    energies = np.concatenate([pre_edge, edge, post_edge])

    logger.info(
        f"Built XAS energy list: "
        f"{len(pre_edge)} pre-edge, "
        f"{len(edge)} edge, "
        f"{len(post_edge)} post-edge points. "
        f"Total: {len(energies)} points"
    )

    return energies


def build_exafs_energy_list(
        edge_energy: float = 7.112,
        k_min: float = 2.0,
        k_max: float = 12.0,
        k_spacing: float = 0.05,
        include_pre_edge: bool = True) -> np.ndarray:
    """
    Build energy list for EXAFS with uniform K-space sampling.

    Generates energy points with uniform spacing in K-space
    (photoelectron momentum) rather than energy space.
    Optimized for EXAFS data quality.

    Parameters
    ----------
    edge_energy : float, optional
        Absorption edge energy in keV (default: 7.112 for Fe)
    k_min : float, optional
        Minimum K value in Å⁻¹ (default: 2.0)
    k_max : float, optional
        Maximum K value in Å⁻¹ (default: 12.0)
    k_spacing : float, optional
        K spacing in Å⁻¹ (default: 0.05)
    include_pre_edge : bool, optional
        Add pre-edge points (default: True)

    Returns
    -------
    np.ndarray
        Energy array in keV

    Notes
    -----
    K-Space vs Energy Space:
    - EXAFS oscillations more uniform in K
    - K = √(0.2625 × (E - E₀))
    - E₀ is edge energy
    - K in Å⁻¹, E in eV

    Energy Conversion:
    - E = E₀ + K² / 0.2625
    - Higher K requires larger energy steps
    - Non-linear spacing in energy

    Pre-Edge Points:
    - If include_pre_edge=True:
      - Adds 10 points below edge
      - 5 eV spacing
      - From edge-50 eV to edge-5 eV

    K Range Selection:
    - k_min: Typically 2-3 Å⁻¹
      - Below this: edge features dominate
      - Low signal-to-noise
    - k_max: Typically 10-15 Å⁻¹
      - Limited by noise
      - Element-dependent

    K Spacing:
    - 0.05 Å⁻¹: Standard resolution
    - 0.025 Å⁻¹: High resolution
    - 0.1 Å⁻¹: Quick scan

    Typical Ranges by Element:
    - Light elements (Z<20): k_max ~8-10 Å⁻¹
    - Medium elements (Z=20-50): k_max ~10-14 Å⁻¹
    - Heavy elements (Z>50): k_max ~12-16 Å⁻¹

    Examples
    --------
    Standard Fe K-edge EXAFS:
    >>> energies = build_exafs_energy_list(
    ...     edge_energy=7.112,
    ...     k_max=12.0
    ... )

    High-resolution EXAFS:
    >>> energies = build_exafs_energy_list(
    ...     edge_energy=7.112,
    ...     k_max=14.0,
    ...     k_spacing=0.025
    ... )

    Extended K range for heavy element:
    >>> energies = build_exafs_energy_list(
    ...     edge_energy=8.979,  # Cu
    ...     k_max=15.0
    ... )

    EXAFS only (no pre-edge):
    >>> energies = build_exafs_energy_list(
    ...     edge_energy=7.112,
    ...     include_pre_edge=False
    ... )

    See Also
    --------
    build_xas_energy_list : General XAS energy list
    k_to_energy : Convert K to energy
    energy_to_k : Convert energy to K
    """
    # Convert edge energy to eV
    edge_eV = edge_energy * 1000

    # Generate K array
    k_values = np.arange(k_min, k_max + k_spacing, k_spacing)

    # Convert K to energy
    # E = E₀ + K² / 0.2625 (with E in eV, K in Å⁻¹)
    energies_eV = edge_eV + (k_values ** 2) / 0.2625

    # Convert to keV
    energies = energies_eV / 1000

    # Add pre-edge points if requested
    if include_pre_edge:
        pre_edge = np.arange(
            edge_energy - 0.050,  # 50 eV below edge
            edge_energy - 0.005,  # 5 eV below edge
            0.005  # 5 eV spacing
        )
        energies = np.concatenate([pre_edge, energies])

    logger.info(
        f"Built EXAFS energy list: "
        f"K = {k_min:.2f} to {k_max:.2f} Å⁻¹, "
        f"spacing = {k_spacing:.3f} Å⁻¹. "
        f"Total: {len(energies)} points"
    )

    return energies


# ==================== K-Space Utilities ====================

def energy_to_k(energy: float, edge_energy: float = 7.112) -> float:
    """
    Convert photon energy to photoelectron momentum K.

    Parameters
    ----------
    energy : float
        Photon energy in keV
    edge_energy : float, optional
        Absorption edge energy in keV (default: 7.112 for Fe)

    Returns
    -------
    float
        K value in Å⁻¹

    Notes
    -----
    Formula:
    K = √(0.2625 × (E - E₀))

    where:
    - K is photoelectron momentum in Å⁻¹
    - E is photon energy in eV
    - E₀ is edge energy in eV
    - 0.2625 is conversion constant

    Physical Meaning:
    - K is photoelectron wavenumber
    - Related to photoelectron kinetic energy
    - Determines EXAFS oscillation frequency

    Valid Range:
    - Returns 0 if energy ≤ edge_energy
    - Negative energies not physical

    Examples
    --------
    >>> k = energy_to_k(7.212, edge_energy=7.112)
    >>> print(f"K = {k:.2f} Å⁻¹")
    K = 5.12 Å⁻¹

    See Also
    --------
    k_to_energy : Inverse conversion
    """
    energy_eV = energy * 1000
    edge_eV = edge_energy * 1000

    if energy_eV <= edge_eV:
        return 0.0

    k = np.sqrt(0.2625 * (energy_eV - edge_eV))
    return k


def k_to_energy(k: float, edge_energy: float = 7.112) -> float:
    """
    Convert photoelectron momentum K to photon energy.

    Parameters
    ----------
    k : float
        K value in Å⁻¹
    edge_energy : float, optional
        Absorption edge energy in keV (default: 7.112 for Fe)

    Returns
    -------
    float
        Photon energy in keV

    Notes
    -----
    Formula:
    E = E₀ + K² / 0.2625

    where:
    - E is photon energy in eV
    - E₀ is edge energy in eV
    - K is in Å⁻¹

    Examples
    --------
    >>> energy = k_to_energy(5.0, edge_energy=7.112)
    >>> print(f"Energy = {energy:.4f} keV")
    Energy = 7.2071 keV

    See Also
    --------
    energy_to_k : Inverse conversion
    """
    edge_eV = edge_energy * 1000
    energy_eV = edge_eV + (k ** 2) / 0.2625
    return energy_eV / 1000


# ==================== Data Analysis Utilities ====================

def estimate_edge_position(
        energies: np.ndarray,
        intensities: np.ndarray,
        method: str = 'derivative') -> float:
    """
    Estimate absorption edge position from scan data.

    Parameters
    ----------
    energies : np.ndarray
        Energy array in keV
    intensities : np.ndarray
        Measured intensities (fluorescence or transmission)
    method : str, optional
        Edge finding method: 'derivative' or 'inflection' (default: 'derivative')

    Returns
    -------
    float
        Estimated edge energy in keV

    Notes
    -----
    Methods:

    'derivative':
    - Finds maximum of first derivative
    - Simple and robust
    - Good for clean data

    'inflection':
    - Finds zero of second derivative
    - More precise
    - Sensitive to noise

    Data Requirements:
    - Smooth data recommended
    - Sufficient points across edge
    - Normalized intensities helpful

    Examples
    --------
    >>> edge = estimate_edge_position(energies, intensities)
    >>> print(f"Edge at {edge:.4f} keV")

    See Also
    --------
    run_dccmscan : Acquire XAS data
    """
    if method == 'derivative':
        # First derivative
        deriv = np.gradient(intensities, energies)
        edge_idx = np.argmax(deriv)
        edge_energy = energies[edge_idx]

    elif method == 'inflection':
        # Second derivative (inflection point)
        deriv1 = np.gradient(intensities, energies)
        deriv2 = np.gradient(deriv1, energies)

        # Find zero crossing
        sign_change = np.diff(np.sign(deriv2))
        inflection_idx = np.where(sign_change != 0)[0]

        if len(inflection_idx) > 0:
            edge_idx = inflection_idx[0]
            edge_energy = energies[edge_idx]
        else:
            logger.warning("No inflection point found, using derivative method")
            deriv = np.gradient(intensities, energies)
            edge_idx = np.argmax(deriv)
            edge_energy = energies[edge_idx]

    else:
        raise ValueError(f"Unknown method: {method}. Use 'derivative' or 'inflection'")

    logger.info(f"Estimated edge position: {edge_energy:.4f} keV using {method} method")
    return edge_energy


def normalize_xas(
        energies: np.ndarray,
        intensities: np.ndarray,
        pre_edge_range: Optional[Tuple[float, float]] = None,
        post_edge_range: Optional[Tuple[float, float]] = None) -> np.ndarray:
    """
    Normalize XAS data using pre- and post-edge regions.

    Parameters
    ----------
    energies : np.ndarray
        Energy array in keV
    intensities : np.ndarray
        Measured intensities
    pre_edge_range : Tuple[float, float] or None, optional
        (min, max) energy for pre-edge fit in keV
        If None, uses first 10% of data
    post_edge_range : Tuple[float, float] or None, optional
        (min, max) energy for post-edge fit in keV
        If None, uses last 10% of data

    Returns
    -------
    np.ndarray
        Normalized intensities (0 to 1 range)

    Notes
    -----
    Normalization Procedure:
    1. Fit line to pre-edge region
    2. Fit line to post-edge region
    3. Subtract pre-edge line
    4. Divide by (post-edge - pre-edge)

    Result:
    - Pre-edge → 0
    - Post-edge → 1
    - Edge jump → 0 to 1

    Use Cases:
    - Compare different samples
    - Remove thickness effects
    - Extract edge jump

    Examples
    --------
    >>> norm_intensities = normalize_xas(energies, intensities)

    >>> norm_intensities = normalize_xas(
    ...     energies, intensities,
    ...     pre_edge_range=(7.05, 7.10),
    ...     post_edge_range=(7.15, 7.20)
    ... )

    See Also
    --------
    estimate_edge_position : Find edge energy
    """
    # Determine pre-edge range
    if pre_edge_range is None:
        n_points = len(energies)
        pre_idx = slice(0, n_points // 10)
    else:
        pre_idx = (energies >= pre_edge_range[0]) & (energies <= pre_edge_range[1])

    # Determine post-edge range
    if post_edge_range is None:
        n_points = len(energies)
        post_idx = slice(9 * n_points // 10, n_points)
    else:
        post_idx = (energies >= post_edge_range[0]) & (energies <= post_edge_range[1])

    # Fit pre-edge line
    pre_fit = np.polyfit(energies[pre_idx], intensities[pre_idx], deg=1)
    pre_line = np.polyval(pre_fit, energies)

    # Fit post-edge line
    post_fit = np.polyfit(energies[post_idx], intensities[post_idx], deg=1)
    post_line = np.polyval(post_fit, energies)

    # Normalize
    normalized = (intensities - pre_line) / (post_line - pre_line)

    logger.info("XAS data normalized")
    return normalized


# ==================== Convenience Functions ====================

def quick_xas_scan(
        element: str = 'Fe',
        record: bool = False,
        pointTime: float = 1.0) -> Optional[int]:
    """
    Quick XAS scan with default parameters for common elements.

    Parameters
    ----------
    element : str, optional
        Element symbol: 'Fe', 'Cu', 'Mn', 'Co', 'Ni' (default: 'Fe')
    record : bool, optional
        Enable recording (default: False)
    pointTime : float, optional
        Dwell time per point in seconds (default: 1.0)

    Returns
    -------
    int or None
        Run number if recording enabled, None otherwise

    Notes
    -----
    Predefined Elements:
    - Fe: 7.050 - 7.200 keV
    - Cu: 8.900 - 9.100 keV
    - Mn: 6.450 - 6.650 keV
    - Co: 7.600 - 7.850 keV
    - Ni: 8.230 - 8.450 keV

    Scan Parameters:
    - Fine spacing near edge (1 eV)
    - Coarse spacing elsewhere (5-10 eV)
    - Optimized for XANES

    Examples
    --------
    >>> quick_xas_scan('Fe', record=True, pointTime=2.0)

    See Also
    --------
    run_dccmscan : Custom XAS scan
    build_xas_energy_list : Build custom energy list
    """
    # Element-specific parameters
    edge_params = {
        'Fe': {'start': 7.050, 'end': 7.200, 'edge': 7.112},
        'Cu': {'start': 8.900, 'end': 9.100, 'edge': 8.979},
        'Mn': {'start': 6.450, 'end': 6.650, 'edge': 6.539},
        'Co': {'start': 7.600, 'end': 7.850, 'edge': 7.709},
        ' ': {'start': 8.230, 'end': 8.450, 'edge': 8.333},
    }

    if element not in edge_params:
        logger.error(
            f"Unknown element: {element}. "
            f"Available: {list(edge_params.keys())}"
        )
        return None

    params = edge_params[element]
    logger.info(f"Running quick XAS scan for {element} K-edge")

    # Build energy list
    energies = build_xas_energy_list(
        pre_edge_start=params['start'],
        pre_edge_end=params['edge'] - 0.017,
        edge_start=params['edge'] - 0.012,
        edge_end=params['edge'] + 0.028,
        post_edge_end=params['end']
    )

    # Run scan
    run_dccmscan(
        energies,
        record=record,
        pointTime=pointTime,
        move_vernier=True
    )

    if record:
        from mfx.db import daq
        return daq._control.runnumber()

    return None


# ==================== Module Initialization ====================

logger.info("XAS utilities loaded. DCCM ready for energy scans.")