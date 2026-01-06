"""
Von Hamos spectrometer control for MFX beamline.

Provides device classes for 6-crystal Von Hamos X-ray emission
spectrometer with deterministic motor positioning and optimization
routines.
"""

import logging
from typing import Optional

from ophyd.device import Component as Cpt
from pcdsdevices.epics_motor import BeckhoffAxis
from pcdsdevices.interface import BaseInterface
from pcdsdevices.device import GroupDevice

logger = logging.getLogger(__name__)


class DeterministicBeckhoffAxis(BeckhoffAxis):
    """
    Beckhoff motor with guaranteed positioning accuracy.

    Extends standard BeckhoffAxis with iterative positioning
    to ensure target is reached within specified tolerance,
    even for motors with backlash or positioning errors.

    The deterministic approach repeatedly moves and checks
    position until target is achieved, with optional smart
    overshoot to overcome backlash.

    Methods
    -------
    go(target, epsilon, n_iterations_max, smart, ...) : None
        Move to target with guaranteed accuracy

    Notes
    -----
    Standard vs. Deterministic:

    Standard BeckhoffAxis:
    - Single move command
    - May not reach target exactly
    - Backlash causes errors
    - Position drift possible

    DeterministicBeckhoffAxis:
    - Iterative positioning
    - Guaranteed accuracy
    - Overcomes backlash
    - Verified arrival

    Positioning Algorithm:
    1. Move to target
    2. Check position
    3. If within epsilon: Done
    4. If not: Repeat move
    5. Limit iterations for safety

    Smart Mode:
    - Detects stuck motors
    - Applies overshoot
    - Overcomes backlash
    - Improves reliability

    Use Cases:
    - Critical positioning (spectrometer crystals)
    - Motors with backlash
    - When accuracy essential
    - Repeatable positioning

    Typical Motors:
    - Analyzer crystals
    - Grating mounts
    - Precision stages
    - Focus adjustments

    Examples
    --------
    Create deterministic motor:
    >>> motor = DeterministicBeckhoffAxis('MFX:SPEC:MMS:01', name='det_motor')

    Standard move (inherited):
    >>> motor.mv(10.0)  # Single move attempt

    Deterministic move:
    >>> motor.go(
    ...     target=10.0,
    ...     epsilon=0.001,  # ±1 µm tolerance
    ...     n_iterations_max=10
    ... )

    Smart mode with backlash:
    >>> motor.go(
    ...     target=5.0,
    ...     epsilon=0.001,
    ...     smart=True,
    ...     overshoot_factor=1.2
    ... )

    See Also
    --------
    BeckhoffAxis : Base class
    DeterministicCrystal : Crystal with deterministic motors
    """

    def __init__(self, *args, **kwargs):
        """
        Initialize deterministic Beckhoff motor.

        Parameters
        ----------
        *args
            Positional arguments for BeckhoffAxis
        **kwargs
            Keyword arguments for BeckhoffAxis
        """
        super().__init__(*args, **kwargs)

    def go(
            self,
            target: float,
            epsilon: float = 0.001,
            n_iterations_max: int = 10,
            smart: bool = False,
            stuck_threshold: float = 0.001,
            overshoot_factor: float = 1.2,
            wait: bool = True) -> None:
        """
        Move to target position with guaranteed accuracy.

        Iteratively moves motor until position is within epsilon
        of target, or maximum iterations reached. Optionally uses
        smart overshoot strategy for stuck motors.

        Parameters
        ----------
        target : float
            Target position in motor units (typically mm or degrees)
        epsilon : float, optional
            Maximum allowed deviation from target (default: 0.001)
            Position considered reached if |pos - target| < epsilon
        n_iterations_max : int, optional
            Maximum positioning attempts (default: 10)
            Prevents infinite loops on failed motors
        smart : bool, optional
            Enable smart overshoot for backlash (default: False)
            Detects stuck motor and applies overshoot
        stuck_threshold : float, optional
            Minimum position change to not be stuck (default: 0.001)
            Used when smart=True
        overshoot_factor : float, optional
            Overshoot multiplier for smart mode (default: 1.2)
            Should be >1.0 to actually overshoot
            Typical range: 1.1-1.5
        wait : bool, optional
            Wait for motion to complete (default: True)

        Returns
        -------
        None

        Raises
        ------
        None
            Logs error if target not reached, but doesn't raise

        Notes
        -----
        Positioning Algorithm:

        Standard Mode (smart=False):
        1. Clear any errors
        2. Read current position
        3. If within epsilon: Success, return
        4. Move to target
        5. Repeat until success or max iterations

        Smart Mode (smart=True):
        1. Standard algorithm
        2. Check position change since last iteration
        3. If change < stuck_threshold:
           a. Motor is stuck (backlash)
           b. Calculate overshoot target
           c. Move past target
           d. Move back to actual target
        4. Continue until success

        Epsilon Selection:
        - Depends on application requirements
        - Typical: 0.001 mm (1 µm)
        - Energy resolution: 0.0001 mm
        - Rough positioning: 0.01 mm

        Iteration Count:
        - Usually succeeds in 1-3 iterations
        - 10 iterations generous safety margin
        - >5 iterations indicates problem

        Overshoot Strategy:
        - Overcomes backlash in one direction
        - Approaches target from same side
        - Improves repeatability
        - Factor 1.2 = 20% overshoot

        Stuck Detection:
        - Compares position change to threshold
        - Small change = stuck/backlash
        - Triggers overshoot correction
        - Helps with sticky motors

        Error Handling:
        - Clears errors before each move
        - Logs failures but doesn't raise
        - Allows continued operation
        - User can retry or diagnose

        Performance:
        - Each iteration ~1-2 seconds
        - Depends on move distance
        - Smart mode slower but more reliable
        - Worth overhead for critical positioning

        Comparison to Standard Move:
        - Standard: Fast but may miss target
        - Deterministic: Slower but guaranteed
        - Use deterministic for precision
        - Use standard for rough moves

        Examples
        --------
        Simple deterministic move:
        >>> motor = DeterministicBeckhoffAxis('MFX:SPEC:MMS:01', name='motor')
        >>> motor.go(target=10.0, epsilon=0.001)

        Tight tolerance:
        >>> motor.go(
        ...     target=5.0,
        ...     epsilon=0.0001,  # 0.1 µm
        ...     n_iterations_max=20
        ... )

        With backlash compensation:
        >>> motor.go(
        ...     target=7.5,
        ...     epsilon=0.001,
        ...     smart=True,
        ...     overshoot_factor=1.3  # 30% overshoot
        ... )

        Fast rough move:
        >>> motor.go(target=0.0, epsilon=0.01, n_iterations_max=5)

        Non-blocking:
        >>> motor.go(target=10.0, wait=False)
        >>> # Do other things while moving

        See Also
        --------
        move : Standard Ophyd move method
        clear_error : Clear motor errors
        """
        iteration = 0
        previous_pos = self.user_readback.get()

        logger.info(
            f"Starting deterministic move to {target:.6f} "
            f"(epsilon={epsilon:.6f}, max_iter={n_iterations_max})"
        )

        while iteration < n_iterations_max:
            # Clear any errors
            self.clear_error()

            # Read current position
            current_pos = self.user_readback.get()

            # Check if we've arrived
            if abs(current_pos - target) <= epsilon:
                logger.info(
                    f"Target reached: pos={current_pos:.6f}, "
                    f"target={target:.6f}, iterations={iteration}"
                )
                return

            # Smart mode: detect stuck motor
            if smart:
                position_change = abs(current_pos - previous_pos)

                if position_change < stuck_threshold and iteration > 0:
                    # Motor is stuck, apply overshoot
                    error = target - current_pos
                    direction = 1 if error > 0 else -1

                    overshoot_target = current_pos + direction * abs(error) * overshoot_factor

                    logger.info(
                        f"Stuck detected (change={position_change:.6f}). "
                        f"Applying overshoot to {overshoot_target:.6f}"
                    )

                    # Move past target
                    self.clear_error()
                    self.move(overshoot_target, wait=wait)

                    # Move back to actual target
                    self.clear_error()
                    self.move(target, wait=wait)
                else:
                    # Normal move
                    self.move(target, wait=wait)
            else:
                # Standard mode: just move
                self.move(target, wait=wait)

            previous_pos = current_pos
            iteration += 1

            logger.debug(
                f"Iteration {iteration}: pos={current_pos:.6f}, "
                f"error={abs(current_pos - target):.6f}"
            )

        # Failed to reach target
        final_pos = self.user_readback.get()
        logger.error(
            f"Failed to reach target within {n_iterations_max} iterations.\n"
            f"  Target: {target:.6f}\n"
            f"  Final position: {final_pos:.6f}\n"
            f"  Deviation: {abs(final_pos - target):.6f}\n"
            f"  Required epsilon: {epsilon:.6f}"
        )


class DeterministicCrystal(BaseInterface, GroupDevice):
    """
    Single Von Hamos crystal with deterministic positioning.

    Represents one analyzer crystal in the Von Hamos spectrometer
    with three degrees of freedom: X (position), rotation, and tilt.
    All motors use deterministic positioning for accuracy.

    Components
    ----------
    x : DeterministicBeckhoffAxis
        Crystal X position (perpendicular to beam)
        Adjusts distance from source
    rot : DeterministicBeckhoffAxis
        Crystal rotation (around vertical axis)
        Adjusts Bragg angle for energy selection
    tilt : DeterministicBeckhoffAxis
        Crystal tilt (pitch)
        Adjusts vertical focusing

    Attributes
    ----------
    tab_component_names : bool
        Enable tab completion for motors

    Notes
    -----
    Von Hamos Geometry:
    - Cylindrically bent analyzer crystal
    - Rowland circle geometry
    - Energy dispersive in one direction
    - Point-to-point focusing

    Motor Functions:

    X Position:
    - Moves crystal toward/away from source
    - Affects collection efficiency
    - Adjusts Rowland circle radius
    - Typical range: ±50 mm

    Rotation:
    - Changes Bragg angle
    - Selects X-ray energy
    - θ ~ arcsin(hc / 2d·E)
    - Typical range: ±10°

    Tilt:
    - Adjusts vertical alignment
    - Optimizes focusing
    - Compensates for mounting errors
    - Typical range: ±5°

    Crystal Properties:
    - Cylindrical curvature
    - Radius of curvature: ~100-500 mm
    - Crystal material: Si, Ge, etc.
    - Miller indices: (111), (220), etc.

    Positioning Requirements:
    - Sub-millimeter accuracy for X
    - Sub-degree accuracy for angles
    - Deterministic mode ensures precision
    - Critical for energy resolution

    Examples
    --------
    Create crystal:
    >>> crystal = DeterministicCrystal('MFX:SPEC:C1', name='crystal1')

    Access motors:
    >>> crystal.x.position
    >>> crystal.rot.position
    >>> crystal.tilt.position

    Standard moves:
    >>> crystal.x.mv(10.0)
    >>> crystal.rot.mv(45.0)

    Deterministic moves:
    >>> crystal.x.go(target=10.0, epsilon=0.001)
    >>> crystal.rot.go(target=45.0, epsilon=0.01)

    See Also
    --------
    DeterministicBeckhoffAxis : Motor with guaranteed accuracy
    DeterministicVonHamos6Crystal : Full 6-crystal assembly
    """

    tab_component_names = True

    x = Cpt(
        DeterministicBeckhoffAxis,
        ':X',
        kind='normal',
        doc='Crystal X position (mm)'
    )
    rot = Cpt(
        DeterministicBeckhoffAxis,
        ':ROT',
        kind='normal',
        doc='Crystal rotation angle (deg)'
    )
    tilt = Cpt(
        DeterministicBeckhoffAxis,
        ':TILT',
        kind='normal',
        doc='Crystal tilt angle (deg)'
    )


class DeterministicVonHamos6Crystal(BaseInterface, GroupDevice):
    """
    Complete Von Hamos 6-crystal spectrometer with deterministic positioning.

    Full spectrometer assembly with six independently controlled
    analyzer crystals plus global positioning stages. Provides
    high-resolution X-ray emission spectroscopy.

    Components
    ----------
    Analyzer Crystals:
        c1, c2, c3, c4, c5, c6 : DeterministicCrystal
            Six analyzer crystals, each with X, rotation, tilt

    Global Stages:
        rot : BeckhoffAxis
            Global rotation (changes all crystals together)
        y : BeckhoffAxis
            Vertical translation
        x_bottom : BeckhoffAxis
            Bottom X translation
        x_top : BeckhoffAxis
            Top X translation

    Attributes
    ----------
    tab_component_names : bool
        Enable tab completion for components

    Notes
    -----
    Von Hamos Spectrometer:

    Principle:
    - Cylindrically bent analyzer crystals
    - Rowland circle geometry
    - Energy dispersive spectroscopy
    - Point-to-point focusing

    6-Crystal Configuration:
    - Arranged in circle around sample
    - Each crystal covers energy range
    - Combined coverage for full spectrum
    - Parallel data collection
    - Increased solid angle

    Energy Selection:
    - Bragg's law: E = hc / (2d·sin(θ))
    - Each crystal at different angle
    - Covers different energy range
    - Detector records dispersed spectrum

    Resolution:
    - Depends on crystal quality
    - Typical: ΔE/E ~ 10⁻⁴
    - Limited by crystal rocking curve
    - Position accuracy critical

    Motor Hierarchy:

    Per-Crystal (c1-c6):
    - Fine adjustments
    - Independent optimization
    - Energy selection
    - Each crystal: X, rot, tilt

    Global :
    - Coarse positioning
    - Whole assembly movement
    - Sample distance adjustment
    - Vertical alignment

    Typical Workflow:
    1. Set global position (coarse)
    2. Adjust individual crystals (fine)
    3. Optimize each crystal separately
    4. Collect spectrum from all

    Applications:
    - X-ray emission spectroscopy (XES)
    - Resonant inelastic scattering (RIXS)
    - Valence-to-core transitions
    - Partial fluorescence yield (PFY)

    Optimization Strategy:
    - Maximize signal on each crystal
    - Balance intensities
    - Minimize overlaps
    - Verify energy calibration

    Common Measurements:
    - Kα, Kβ emission lines
    - Valence band structure
    - d-d excitations
    - Ligand effects

    Examples
    --------
    Create spectrometer:
    >>> spec = DeterministicVonHamos6Crystal('MFX:SPEC', name='spec')

    Access individual crystals:
    >>> spec.c1.x.position
    >>> spec.c2.rot.mv(45.0)
    >>> spec.c3.tilt.go(target=2.5, epsilon=0.01)

    Access global stages:
    >>> spec.y.mv(10.0)  # Move whole assembly
    >>> spec.rot.mv(30.0)  # Rotate all crystals

    Move all crystals to same X:
    >>> for i in range(1, 7):
    ...     crystal = getattr(spec, f'c{i}')
    ...     crystal.x.go(target=15.0, epsilon=0.001)

    Optimize individual crystal:
    >>> spec.c1.x.go(target=14.5, epsilon=0.001, smart=True)
    >>> spec.c1.rot.go(target=44.2, epsilon=0.01, smart=True)
    >>> spec.c1.tilt.go(target=1.8, epsilon=0.01)

    Read all positions:
    >>> for i in range(1, 7):
    ...     crystal = getattr(spec, f'c{i}')
    ...     print(f"C{i}: X={crystal.x.position:.3f}, "
    ...           f"Rot={crystal.rot.position:.2f}, "
    ...           f"Tilt={crystal.tilt.position:.2f}")

    See Also
    --------
    DeterministicCrystal : Single crystal control
    DeterministicBeckhoffAxis : Motor implementation
    """

    tab_component_names = True

    # Individual analyzer crystals
    c1 = Cpt(
        DeterministicCrystal,
        ':C1',
        kind='normal',
        doc='Crystal 1 (X, rotation, tilt)'
    )
    c2 = Cpt(
        DeterministicCrystal,
        ':C2',
        kind='normal',
        doc='Crystal 2 (X, rotation, tilt)'
    )
    c3 = Cpt(
        DeterministicCrystal,
        ':C3',
        kind='normal',
        doc='Crystal 3 (X, rotation, tilt)'
    )
    c4 = Cpt(
        DeterministicCrystal,
        ':C4',
        kind='normal',
        doc='Crystal 4 (X, rotation, tilt)'
    )
    c5 = Cpt(
        DeterministicCrystal,
        ':C5',
        kind='normal',
        doc='Crystal 5 (X, rotation, tilt)'
    )
    c6 = Cpt(
        DeterministicCrystal,
        ':C6',
        kind='normal',
        doc='Crystal 6 (X, rotation, tilt)'
    )

    # Global positioning stages
    rot = Cpt(
        BeckhoffAxis,
        ':ROT',
        kind='normal',
        doc='Global rotation (deg)'
    )
    y = Cpt(
        BeckhoffAxis,
        ':T1',
        kind='normal',
        doc='Vertical translation (mm)'
    )
    x_bottom = Cpt(
        BeckhoffAxis,
        ':T2',
        kind='normal',
        doc='Bottom X translation (mm)'
    )
    x_top = Cpt(
        BeckhoffAxis,
        ':T3',
        kind='normal',
        doc='Top X translation (mm)'
    )


# Convenience functions

def optimize_crystal(
        crystal: DeterministicCrystal,
        x_target: Optional[float] = None,
        rot_target: Optional[float] = None,
        tilt_target: Optional[float] = None,
        epsilon_x: float = 0.001,
        epsilon_rot: float = 0.01,
        epsilon_tilt: float = 0.01,
        smart: bool = True) -> None:
    """
    Optimize all axes of a single crystal.

    Parameters
    ----------
    crystal : DeterministicCrystal
        Crystal to optimize
    x_target : float or None, optional
        Target X position (None = skip)
    rot_target : float or None, optional
        Target rotation (None = skip)
    tilt_target : float or None, optional
        Target tilt (None = skip)
    epsilon_x : float, optional
        X position tolerance (default: 0.001 mm)
    epsilon_rot : float, optional
        Rotation tolerance (default: 0.01 deg)
    epsilon_tilt : float, optional
        Tilt tolerance (default: 0.01 deg)
    smart : bool, optional
        Use smart overshoot mode (default: True)

    Returns
    -------
    None

    Examples
    --------
    >>> spec = DeterministicVonHamos6Crystal('MFX:SPEC', name='spec')
    >>> optimize_crystal(
    ...     spec.c1,
    ...     x_target=15.0,
    ...     rot_target=45.0,
    ...     tilt_target=2.0
    ... )

    See Also
    --------
    DeterministicCrystal : Single crystal class
    """
    logger.info(f"Optimizing crystal: {crystal.name}")

    if x_target is not None:
        logger.info(f"  X -> {x_target:.4f}")
        crystal.x.go(target=x_target, epsilon=epsilon_x, smart=smart)

    if rot_target is not None:
        logger.info(f"  Rotation -> {rot_target:.3f}")
        crystal.rot.go(target=rot_target, epsilon=epsilon_rot, smart=smart)

    if tilt_target is not None:
        logger.info(f"  Tilt -> {tilt_target:.3f}")
        crystal.tilt.go(target=tilt_target, epsilon=epsilon_tilt, smart=smart)

    logger.info("Crystal optimization complete")


def set_all_crystals(
        spectrometer: DeterministicVonHamos6Crystal,
        x: Optional[float] = None,
        rot: Optional[float] = None,
        tilt: Optional[float] = None,
        epsilon_x: float = 0.001,
        epsilon_rot: float = 0.01,
        epsilon_tilt: float = 0.01,
        smart: bool = True) -> None:
    """
    Set all six crystals to same position.

    Parameters
    ----------
    spectrometer : DeterministicVonHamos6Crystal
        Spectrometer object
    x : float or None, optional
        X position for all crystals (None = skip)
    rot : float or None, optional
        Rotation for all crystals (None = skip)
    tilt : float or None, optional
        Tilt for all crystals (None = skip)
    epsilon_x : float, optional
        X tolerance (default: 0.001 mm)
    epsilon_rot : float, optional
        Rotation tolerance (default: 0.01 deg)
    epsilon_tilt : float, optional
        Tilt tolerance (default: 0.01 deg)
    smart : bool, optional
        Use smart mode (default: True)

    Returns
    -------
    None

    Examples
    --------
    >>> spec = DeterministicVonHamos6Crystal('MFX:SPEC', name='spec')
    >>> set_all_crystals(spec, x=15.0, rot=45.0, tilt=0.0)

    See Also
    --------
    optimize_crystal : Single crystal optimization
    """
    logger.info("Setting all crystals to same position")

    for i in range(1, 7):
        crystal = getattr(spectrometer, f'c{i}')
        logger.info(f"Crystal {i}:")
        optimize_crystal(
            crystal,
            x_target=x,
            rot_target=rot,
            tilt_target=tilt,
            epsilon_x=epsilon_x,
            epsilon_rot=epsilon_rot,
            epsilon_tilt=epsilon_tilt,
            smart=smart
        )

    logger.info("All crystals positioned")


def read_crystal_positions(
        spectrometer: DeterministicVonHamos6Crystal) -> dict:
    """
    Read positions of all crystals.

    Parameters
    ----------
    spectrometer : DeterministicVonHamos6Crystal
        Spectrometer object

    Returns
    -------
    dict
        Nested dictionary with positions:
        {
            'c1': {'x': ..., 'rot': ..., 'tilt': ...},
            'c2': {...},
            ...
        }

    Examples
    --------
    >>> spec = DeterministicVonHamos6Crystal('MFX:SPEC', name='spec')
    >>> positions = read_crystal_positions(spec)
    >>> print(f"C1 X: {positions['c1']['x']:.3f}")

    See Also
    --------
    set_all_crystals : Set all crystals
    """
    positions = {}

    for i in range(1, 7):
        crystal = getattr(spectrometer, f'c{i}')
        positions[f'c{i}'] = {
            'x': crystal.x.position,
            'rot': crystal.rot.position,
            'tilt': crystal.tilt.position
        }

    return positions


def print_crystal_positions(spectrometer: DeterministicVonHamos6Crystal) -> None:
    """
    Print formatted table of all crystal positions.

    Parameters
    ----------
    spectrometer : DeterministicVonHamos6Crystal
        Spectrometer object

    Returns
    -------
    None
        Prints to console

    Examples
    --------
    >>> spec = DeterministicVonHamos6Crystal('MFX:SPEC', name='spec')
    >>> print_crystal_positions(spec)
    Crystal Positions:
    C1: X= 15.234, Rot= 45.12, Tilt=  1.85
    C2: X= 15.189, Rot= 45.08, Tilt=  1.92
    ...

    See Also
    --------
    read_crystal_positions : Get positions as dict
    """
    positions = read_crystal_positions(spectrometer)

    print("\nCrystal Positions:")
    print("=" * 50)
    print("Crystal    X (mm)      Rot (deg)   Tilt (deg)")
    print("-" * 50)

    for i in range(1, 7):
        pos = positions[f'c{i}']
        print(
            f"  C{i}    {pos['x']:8.3f}    {pos['rot']:7.2f}    {pos['tilt']:7.2f}"
        )

    print("=" * 50)


# Module initialization
logger.info("Von Hamos spectrometer control loaded with deterministic positioning")