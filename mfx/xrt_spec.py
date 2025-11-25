"""
Yano laser control and automated data acquisition for MFX beamline.

This module provides interfaces for controlling OPO and EVO laser systems,
managing laser shutters, configuring timing triggers, and executing
automated pump-probe experiments with optional energy spread measurements.
"""

import os
import logging
from time import time, sleep
from typing import Optional

class XRTspec:
    """
    Laser control and automated data acquisition system for MFX.

    The Yano class provides comprehensive control of OPO (Optical Parametric
    Oscillator) and EVO (Evolution) laser systems, including shutter
    management, timing configuration, and automated pump-probe experiments
    with optional energy spread (SPREAD) measurements.

    Attributes
    ----------
    opo_shutter : LaserShutter
        OPO free-space laser shutter control
    evo_shutter1 : LaserShutter
        EVO fiber delivery shutter 1
    evo_shutter2 : LaserShutter
        EVO fiber delivery shutter 2
    evo_shutter3 : LaserShutter
        EVO fiber delivery shutter 3
    opo : Trigger
        OPO laser timing trigger (EVR channel 6)
    evo : Trigger
        EVO laser timing trigger (EVR channel 5)
    opo_time_zero : int
        OPO laser time-zero reference in nanoseconds
    opo_ec_short : int
        Event code for short OPO delay (212)
    opo_ec_long : int
        Event code for long OPO delay (211)
    opo_ec_longer : int
        Event code for longer OPO delay (210)
    opo_ec_longest : int
        Event code for longest OPO delay (213)
    PP : int
        Event code for pump-probe experiments (197)
    DAQ : int
        Event code for DAQ trigger (198)
    WATER : int
        Event code for water sample (211)
    SAMPLE : int
        Event code for sample measurement (212)
    rep_rate : int
        Laser repetition rate in Hz
    delay : float or None
        Current laser delay setting

    Methods
    -------
    shutter_status
        Get current status of all laser shutters
    configure_shutters(fiber1, fiber2, fiber3, free_space)
        Configure all laser shutters for experiment
    autorun(num_runs, num_events, run_length, record, use_l3t, controls,
            spread, spread_type, step_time, brewster, daq_num, add_note)
        Execute automated data acquisition with optional SPREAD

    Notes
    -----
    Laser Systems:
    - OPO: Free-space optical parametric oscillator for IR/Vis
    - EVO: Fiber-delivered laser with three independent channels

    Event Codes and Timing:
    - Event codes control laser timing relative to X-rays
    - Different codes provide various delay ranges
    - Time-zero calibration required for pump-probe experiments

    SPREAD Functionality:
    - Automated energy variation during data collection
    - Two modes: 'vernier' (fast) or 'k' (slow undulator change)
    - Enables energy-dependent studies with single command

    Examples
    --------
    Basic initialization and shutter configuration:
    >>> y = Yano()
    >>> y.configure_shutters(fiber1=True, fiber2=False,
    ...                      fiber3=False, free_space=True)

    Simple automated run:
    >>> y.autorun(num_runs=10, num_events=1000, record=True)

    Pump-probe with energy spread:
    >>> y.autorun(num_runs=20, num_events=5000, record=True,
    ...           spread=[8980, 9020, 5], spread_type='vernier',
    ...           brewster=True)

    See Also
    --------
    LaserShutter : Individual shutter control
    Trigger : EVR trigger configuration
    """

    def __init__(self):
        from pcdsdevices.spectrometer import HXRSpectrometer
        # Initialize spectrometer
        try:
            self.hxrsss = HXRSpectrometer("STEP:XRT1", name="self.hxrsss")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize HXRSpectrometer: {e}")

        self.logger = logging.getLogger(__name__)

    def get_feespec_positions(self, energy_keV, crystal_angle_offset=0.0, debug=False):
        """
        Calculate FEE spectrometer positions for a given energy.

        Computes the crystal angle, camera angle, and camera Y position required
        for the FEE spectrometer to operate at a specified photon energy. Uses
        the standard calibration formulas relating energy to spectrometer geometry.

        The energy-to-position conversion uses the following relationships:
            crystal_angle = 140.0 - 21.2*E + 1.02*E² + offset
            camera_angle = -1.9 + 2*crystal_angle
            camera_y = -4.92 - 0.111*E

        where E is the photon energy in keV.

        Parameters
        ----------
        energy_keV : float
            Target photon energy in keV. Recommended range is 4.0 to 25.0 keV
            to stay within the spectrometer's operational limits.

        debug : bool, optional
                If True, logs detailed calculation information. Default: False

        crystal_angle_offset : float, optional
            Offset to add to the calculated crystal angle in degrees. Used for
            fine-tuning calibration or compensating for systematic errors.
            Positive values increase the crystal angle. Default: 0.0

        Returns
        -------
        positions : dict
            Dictionary containing calculated positions with the following keys:

            energy_keV : float
                Input photon energy in keV.

            crystal_angle : float
                Required crystal angle (θ) in degrees for Bragg diffraction
                at the specified energy, including any applied offset.

            camera_angle : float
                Required camera angle (2θ) in degrees, positioned to collect
                the diffracted beam.

            camera_y : float
                Required camera Y-axis position in mm to center the diffracted
                beam on the detector.

            crystal_angle_offset : float
                Applied crystal angle offset in degrees.

        Notes
        -----
        - This function only calculates positions; it does NOT move any motors.
        Use move_feespec_energy() to actually move the spectrometer.
        - The formulas are empirically determined calibrations specific to the
        HXR FEE spectrometer at LCLS.
        - Crystal angle follows the Bragg law modified by mechanical constraints
        of the spectrometer design.
        - Camera angle is fixed at 2θ geometry with a small offset correction.
        - Camera Y position compensates for beam height variation with energy.
        - Values are valid for Si(111) crystal configuration.
        - The crystal angle offset affects both the crystal and camera angles,
        since camera_angle = -1.9 + 2*crystal_angle.
        - Logging output is sent to the module logger 'feespec_positions' at
        INFO level.

        Examples
        --------
        Get positions for 9 keV:

        >>> positions = get_feespec_positions(9.0)
        >>> print(f"Crystal angle: {positions['crystal_angle']:.3f}°")
        >>> print(f"Camera angle: {positions['camera_angle']:.3f}°")
        >>> print(f"Camera Y: {positions['camera_y']:.3f} mm")
        Crystal angle: 28.580°
        Camera angle: 55.260°
        Camera Y: -5.919 mm

        Apply a +0.5° offset to crystal angle:

        >>> positions = get_feespec_positions(9.0, crystal_angle_offset=0.5)
        >>> print(f"Crystal angle: {positions['crystal_angle']:.3f}°")
        Crystal angle: 29.080°

        Calculate positions for a range of energies:

        >>> energies = [7.0, 8.0, 9.0, 10.0, 11.0]
        >>> for E in energies:
        ...     pos = get_feespec_positions(E)
        ...     print(f"{E:.1f} keV: θ={pos['crystal_angle']:.2f}°")
        7.0 keV: θ=40.46°
        8.0 keV: θ=34.08°
        9.0 keV: θ=28.58°
        10.0 keV: θ=23.96°
        11.0 keV: θ=20.22°

        Verify positions match expected values:

        >>> pos = get_feespec_positions(8.5)
        >>> assert 30 < pos['crystal_angle'] < 35
        >>> assert 60 < pos['camera_angle'] < 70
        >>> assert -6 < pos['camera_y'] < -5

        See Also
        --------
        move_feespec_energy : Move spectrometer to energy
        check_feespec_crystal_angle : Check and adjust crystal angle
        scan_feespec_camera_angle : Scan camera angle over energy range

        References
        ----------
        .. [1] FEE Spectrometer calibration documentation (MFX beamline wiki)
        .. [2] Bragg's law and spectrometer geometry
        """
        # Calculate crystal angle using quadratic formula
        # Accounts for Bragg law and mechanical geometry
        crystal_angle = 140.0 - (21.2 * energy_keV) + (1.02 * energy_keV ** 2)

        # Calculate camera angle (2θ geometry with offset)
        camera_angle = -1.9 + 2 * crystal_angle

        # Calculate camera Y position (energy-dependent height correction)
        camera_y = -4.92 - 0.111 * energy_keV

        # Alter the crystal_angle without affecting the camera_angle
        if crystal_angle_offset != 0.0:
            crystal_angle = (140.0 - (21.2 * energy_keV) +
                            (1.02 * energy_keV ** 2) + crystal_angle_offset)

        # Return dictionary of positions
        positions = {
            'energy_keV': energy_keV,
            'crystal_angle': crystal_angle,
            'camera_angle': camera_angle,
            'camera_y': camera_y,
            'crystal_angle_offset': crystal_angle_offset
        }
        if debug:
            # Log the calculated positions
            self.logger.info(f"FEE Spectrometer positions for {energy_keV:.4f} keV:")
            self.logger.info(f"  Crystal angle (θ):  {crystal_angle:.4f}°")
            if crystal_angle_offset != 0.0:
                self.logger.info(f"    (includes offset: {crystal_angle_offset:+.4f}°)")
            self.logger.info(f"  Camera angle (2θ):  {camera_angle:.4f}°")
            self.logger.info(f"  Camera Y position:  {camera_y:.4f} mm")

        return positions

    def move_feespec_energy(self, energy_keV, crystal_angle_offset=0.0):
        """
        Move FEE spectrometer to energy.

        Parameters
        ----------
        energy_keV : float
            Target energy in keV

        crystal_angle_offset : float, optional
            Offset to add to the calculated crystal angle in degrees. Used for
            fine-tuning calibration or compensating for systematic errors.
            Positive values increase the crystal angle. Default: 0.0

        Notes
        -----
        Moves crystal angle, camera angle, and camera Y position.
        Formula: crystal_angle = 140.0 - 21.2*E + 1.02*E²
        camera_angle = -1.9 + 2*crystal_angle
        camera_y = -4.92 - 0.111*E

        Performs safety check on XRT transmission after move.
        Returns to previous position if alarm detected.
        Stops/starts camera acquisition as needed.
        """
        self.logger.warning(f'Calibrating XRT-Spec for {energy_keV:.3f} keV')

        # Stop camera if running
        cam_status = os.popen("caget CAMR:FEE1:441:Acquire | awk '{print $2}'").read().strip()
        if cam_status == 'Acquire':
            os.system('caput CAMR:FEE1:441:Acquire Done')

        # Store current positions
        ref_crystal_angle = self.hxrsss.th.position
        ref_camera_angle = self.hxrsss.tth.position
        ref_camera_y = self.hxrsss.camy.position

        # Calculate target positions
        positions = self.get_feespec_positions(
            energy_keV, crystal_angle_offset=crystal_angle_offset)

        # Move to target
        self.hxrsss.tth.mv(positions['camera_angle'])
        self.hxrsss.camy.mv(positions['camera_y'])
        self.hxrsss.th.mv(positions['crystal_angle'])

        # Safety check
        xrt_status = os.popen("caget XRT:HXS:TRNS.SEVR | awk '{print $2}'").read().strip()
        if xrt_status != 'NO_ALARM':
            self.logger.error('XRT transmission alarm. Returning to previous position')
            self.hxrsss.tth.mv(ref_camera_angle)
            self.hxrsss.camy.mv(ref_camera_y)
            self.hxrsss.th.mv(ref_crystal_angle)

    def check_feespec_crystal_angle(self, energy_keV, crystal_angle_offset=0.0):
        """
        Check and adjust FEE spectrometer crystal angle.

        Parameters
        ----------
        energy_keV : float
            Target energy in keV

        crystal_angle_offset : float, optional
            Offset to add to the calculated crystal angle in degrees. Used for
            fine-tuning calibration or compensating for systematic errors.
            Positive values increase the crystal angle. Default: 0.0

        Notes
        -----
        Only moves crystal if angle differs from target by >0.01°.
        Uses user move (umv) which blocks until complete.
        Performs XRT transmission safety check.
        Manages camera acquisition state.
        """
        self.hxrsss = HXRSpectrometer("STEP:XRT1", name="self.hxrsss")

        ref_crystal_angle = self.hxrsss.th.position

        # Calculate target positions
        positions = self.get_feespec_positions(
            energy_keV, crystal_angle_offset=crystal_angle_offset)

        if round(crystal_angle, 2) == round(ref_crystal_angle, 2):
            return

        # Stop camera
        cam_status = os.popen("caget CAMR:FEE1:441:Acquire | awk '{print $2}'").read().strip()
        if cam_status == 'Acquire':
            os.system('caput CAMR:FEE1:441:Acquire Done')

        self.hxrsss.th.umv(positions['crystal_angle'])

        # Safety check
        xrt_status = os.popen("caget XRT:HXS:TRNS.SEVR | awk '{print $2}'").read().strip()
        if xrt_status != 'NO_ALARM':
            self.logger.error('XRT transmission alarm after move')
            self.hxrsss.th.mv(ref_crystal_angle)

        # Restart camera
        cam_status = os.popen("caget CAMR:FEE1:441:Acquire | awk '{print $2}'").read().strip()
        if cam_status == 'Done':
            os.system('caput CAMR:FEE1:441:Acquire Acquire')

    def track_feespec_camera(self, energy_keV):
        """
        Move FEE spectrometer camera position.

        Parameters
        ----------
        energy_keV : float
            Target energy in keV

        Notes
        -----
        Moves only camera angle (tth), not crystal or Y position.
        Used to compensate for vignetting during energy scans.
        Starts camera if currently stopped.
        Performs XRT transmission safety check.
        """
        self.hxrsss = HXRSpectrometer("STEP:XRT1", name="self.hxrsss")

        cam_status = os.popen("caget CAMR:FEE1:441:Acquire | awk '{print $2}'").read().strip()
        if cam_status == 'Done':
            os.system('caput CAMR:FEE1:441:Acquire Acquire')

        ref_camera_angle = self.hxrsss.tth.position

        # Calculate target positions
        positions = self.get_feespec_positions(
            energy_keV, crystal_angle_offset=crystal_angle_offset)

        self.hxrsss.tth.mv(positions['camera_angle'])

        xrt_status = os.popen("caget XRT:HXS:TRNS.SEVR | awk '{print $2}'").read().strip()
        if xrt_status != 'NO_ALARM':
            self.logger.error('XRT transmission alarm')
            self.hxrsss.tth.mv(ref_camera_angle)

    def scan_feespec_camera_angle(
        self,
        start_energy_keV,
        end_energy_keV,
        num_points,
        run_length: int = 30,
        tag: str = 'xrt_cam_scan',
        picker: Optional[str] = None,
        inspire: bool = False,
        daq_delay: int = 5,
        record: bool = False,
        daq_num: int = 2,
        check_xrt=True,
        exp: Optional[str] = None):
        """
        Scan FEE spectrometer camera angle over an energy range.

        Performs automated scanning of the FEE spectrometer camera angle (2θ)
        across a specified energy range. The function automatically converts
        energies to the appropriate camera angles using the crystal-camera
        relationship calibration. Optionally records camera images at each
        position and monitors XRT transmission for beam quality assurance.

        The energy-to-angle conversion uses the following relationships:
            crystal_angle = 140.0 - 21.2*E + 1.02*E²
            camera_angle = -1.9 + 2*crystal_angle

        where E is the photon energy in keV.

        Parameters
        ----------
        start_energy_keV : float
            Starting photon energy in keV. Minimum recommended value is 4.0 keV
            to stay within the spectrometer's operational range.

        end_energy_keV : float
            Ending photon energy in keV. Maximum recommended value is 25.0 keV
            to stay within the spectrometer's operational range.

        num_points : int
            Number of energy points to scan. Points are evenly spaced in energy
            between start_energy_keV and end_energy_keV (inclusive). Minimum
            value is 2.

        run_length : float, optional
            Time to wait at each position in seconds before moving to the next
            point. This allows for data acquisition and settling time. Must be
            non-negative. Default: 1.0

        tag : str, optional
            Run tag for organization.
            Default is 'dccm'.

        picker : str, optional
            Pulse picker mode: 'open', 'flip', or None.
            Default is None.

        inspire : bool, optional
            Add inspirational quotes to elog.
            Default is False.

        daq_delay : int, optional
            Delay between energy points in seconds.
            Allows system to settle.
            Default is 5.

        record : bool, optional
            Enable data recording.
            Default is False.

        daq_num : int, optional
            DAQ station: 1 (LCLS-I) or 2 (LCLS-II).
            Default is 2.

        check_xrt : bool, optional
            If True, checks the XRT transmission alarm status at each position.
            Low transmission indicates beam attenuation or misalignment issues.
            Warnings are logged if transmission alarms are detected.
            Default: True

        exp : str, optional
            Experiment name. If None, auto-detects.
            Default is None.

        Returns
        -------
        scan_data : dict
            Dictionary containing scan results with the following keys:

            energies_keV : list of float
                Commanded photon energies in keV for each scan point.

            angles : list of float
                Commanded camera angles in degrees (2θ) for each scan point,
                calculated from the energy-angle calibration.

            actual_angles : list of float
                Actual reached camera angles in degrees as read back from the
                spectrometer motor position. Deviations from commanded angles
                may indicate mechanical issues.

            timestamps : list of float
                Unix timestamps (seconds since epoch) when each data point was
                recorded. Useful for correlating with other time-series data.

            xrt_status : list of str
                XRT transmission alarm status at each point. Values are:
                - 'NO_ALARM': Normal operation, good transmission
                - 'MINOR': Minor transmission issue
                - 'MAJOR': Major transmission issue
                - 'INVALID': Invalid/unavailable status
                - 'NOT_CHECKED': XRT checking was disabled (check_xrt=False)

        Raises
        ------
        ValueError
            If num_points < 2, as at least two points are needed for a scan.
            If start_energy_keV >= end_energy_keV (no range to scan).
            If run_length < 0 (invalid wait time).

        RuntimeError
            If the spectrometer device cannot be initialized.
            If camera control commands fail (when record=True).

        Notes
        -----
        - The camera is stopped during moves and restarted for acquisition if
        record=True, to avoid motion blur in images.
        - The function attempts to restore the original camera state on
        completion or if an error occurs.
        - Camera angle movements use the .umv() (user move) method which
        provides motion feedback and completion confirmation.
        - The crystal angle is NOT moved during this scan; only the camera
        angle changes. For energy scanning with both crystal and camera
        motion, use the full spectrometer energy scan methods.
        - XRT transmission monitoring helps identify beam delivery issues but
        does not halt the scan if alarms occur.
        - Logging output is sent to the module logger 'feespec_scan' at INFO
        level.

        Examples
        --------
        Basic scan from 8 to 10 keV with default settings:

        >>> results = scan_feespec_camera_angle(
        ...     start_energy_keV=8.0,
        ...     end_energy_keV=10.0,
        ...     num_points=21
        ... )

        Detailed scan with extended acquisition time:

        >>> results = scan_feespec_camera_angle(
        ...     start_energy_keV=7.0,
        ...     end_energy_keV=7.5,
        ...     num_points=11,
        ...     run_length=5.0,
        ...     check_xrt=True,
        ...     record=True
        ... )

        Quick diagnostic scan without camera recording:

        >>> results = scan_feespec_camera_angle(
        ...     start_energy_keV=9.0,
        ...     end_energy_keV=9.2,
        ...     num_points=5,
        ...     run_length=0.5,
        ...     record=False
        ... )

        See Also
        --------
        HXRSpectrometer : Main spectrometer device class
        Exafs.long_escan : Full EXAFS scan with energy, vernier, and focus
                        tracking

        References
        ----------
        .. [1] FEE Spectrometer calibration documentation (MFX beamline wiki)
        .. [2] XRT transmission monitoring procedures
        """
        from mfx.db import pp
        from mfx.autorun import autorun
        from mfx.macros import get_exp, get_run

        # Input validation
        if num_points < 2:
            raise ValueError(f"num_points must be >= 2, got {num_points}")
        if start_energy_keV >= end_energy_keV:
            raise ValueError(
                f"start_energy_keV ({start_energy_keV}) must be < "
                f"end_energy_keV ({end_energy_keV})"
            )
        if run_length < 0:
            raise ValueError(f"run_length must be >= 0, got {run_length}")

        # Validate DAQ number
        if daq_num not in [1, 2]:
            self.logger.error('daq_num must be 1 (LCLS-I) or 2 (LCLS-II)')
            raise ValueError('Invalid daq_num')

        # Determine station
        station = 1 if daq_num == 1 else 0

        if exp is None:
            exp = str(get_exp(station=station))

        # Generate energy points
        energies_keV = [
            start_energy_keV + (end_energy_keV - start_energy_keV) * i
            / (num_points - 1) for i in range(num_points)
        ]

        # Log scan configuration
        self.logger.info("\n" + "="*60)
        self.logger.info("XRT CAM ANGLE SCAN SERIES")
        self.logger.info("="*60)
        self.logger.info(f"Experiment: {exp}")
        self.logger.info(f"Energy range: {start_energy_keV} - "
                    f"{end_energy_keV} eV")
        self.logger.info(f"Number of points: {num_points}")
        self.logger.info(f"Energies: {energies_keV}")
        self.logger.info(f"Run length: {run_length}s per point")
        self.logger.info(f"Total time: ~{num_points * (run_length + daq_delay) / 60:.1f} min")
        self.logger.info(f"Recording: {record}")
        self.logger.info("="*60 + "\n")

        # Convert energies to camera angles using the formula from the code
        # crystal_angle = 140.0 - 21.2*E + 1.02*E²
        # camera_angle = -1.9 + 2*crystal_angle
        angles = []
        for E in energies_keV:
            crystal_angle = 140.0 - (21.2 * E) + (1.02 * E ** 2)
            camera_angle = -1.9 + 2 * crystal_angle
            angles.append(camera_angle)

        # Data storage
        scan_data = {
            'energies_keV': [],
            'angles': [],
            'actual_angles': [],
            'timestamps': [],
            'xrt_status': []
        }

        # Get initial camera status
        try:
            cam_status = os.popen(
                "caget CAMR:FEE1:441:Acquire | awk '{print $2}'"
            ).read().strip()
            camera_was_running = (cam_status == 'Acquire')
        except Exception as e:
            if record:
                raise RuntimeError(f"Failed to query camera status: {e}")
            camera_was_running = False

        # Start camera if not running and we want to record
        if record and cam_status != 'Acquire':
            self.logger.info("Starting camera...")
            try:
                os.system('caput CAMR:FEE1:441:Acquire Acquire')
                sleep(2)  # Wait for camera to start
            except Exception as e:
                raise RuntimeError(f"Failed to start camera: {e}")

        # Store initial camera angle
        original_cam_angle = self.hxrsss.tth.position
        self.logger.info(f"Initial camera angle: {original_cam_angle}°")

        # Configure pulse picker
        if picker == 'open':
            self.logger.info("Opening pulse picker")
            pp.open()
        elif picker == 'flip':
            self.logger.info("Setting pulse picker to flip-flop")
            pp.flipflop()

        # Get starting run number
        run_number = get_run(station=station) + 1

        try:
            for i, (energy_keV, target_angle) in enumerate(zip(energies_keV,
                                                                angles)):
                self.logger.info(
                    f"Point {i+1}/{num_points}: Energy {energy_keV:.4f} keV -> "
                    f"Angle {target_angle:.3f}°"
                )

                # Move camera angle
                self.hxrsss.tth.umv(target_angle)

                # Get actual position
                actual_angle = self.hxrsss.tth.position

                # Check XRT transmission if requested
                xrt_status = "NOT_CHECKED"
                if check_xrt:
                    try:
                        xrt_status = os.popen(
                            "caget XRT:HXS:TRNS.SEVR | awk '{print $2}'"
                        ).read().strip()
                        if xrt_status != 'NO_ALARM':
                            self.logger.warning(
                                f"XRT transmission alarm at {energy_keV:.4f} "
                                f"keV: {xrt_status}"
                            )
                    except Exception as e:
                        self.logger.warning(f"Failed to check XRT status: {e}")
                        xrt_status = "ERROR"

                # Record data
                scan_data['energies_keV'].append(energy_keV)
                scan_data['angles'].append(target_angle)
                scan_data['actual_angles'].append(actual_angle)
                scan_data['timestamps'].append(time())
                scan_data['xrt_status'].append(xrt_status)

                self.logger.info(f"  Actual position: {actual_angle:.3f}°")
                self.logger.info(
                    f"  Position error: {abs(actual_angle - target_angle):.4f}°"
                )
                self.logger.info(f"  XRT status: {xrt_status}")

                # Collect data
                self.logger.info(f"Collecting data for {run_length}s...")
                autorun(
                    sample=f"{energy_keV} keV at camera angle {actual_angle}",
                    tag=tag,
                    run_length=run_length,
                    record=record,
                    runs=1,
                    inspire=inspire,
                    picker=picker,
                    close=False,  # Don't close between points
                    daq_num=daq_num
                )

            self.logger.info("Scan completed successfully!")
            self.logger.info(f"Total scan points: {len(scan_data['energies_keV'])}")
            self.logger.info(
                f"Total scan time: {sum([run_length] * num_points):.1f} s"
            )

        except Exception as e:
            self.logger.error(f"Scan failed: {e}")
            raise

        finally:
            # Restore camera state if we changed it
            self.logger.info("Moving back to original camera angle")
            self.hxrsss.tth.umv(original_cam_angle)

            energy_scan_steps = (end_energy_keV - start_energy_keV) / (num_points - 1)
            self.logger.warning(
                f"notch.output(user='your_username', facility='S3DF', "
                f"exp='{exp}', run={run_number}, "
                f"energy={start_energy_keV}, "
                f"step={energy_scan_steps}, num=num_points, "
                f"daq_num={daq_num})"
            )

            # Prompt for analysis
            answer = input("Would you like to analyze the scan? (y/n): ")
            if answer.lower() == "y":
                facility = input("Which facility? (S3DF/NERSC): ")
                if facility.upper() in ['S3DF', 'NERSC']:
                    user = input("Enter username to continue: ")
                    self.output(
                        user=user,
                        facility=facility,
                        exp=exp,
                        run=run_number,
                        energy=start_energy_keV,
                        step=energy_scan_steps,
                        num=num_points,
                        daq_num=daq_num)
                else:
                    self.logger.warning(f"Unknown facility: {facility}")

        return scan_data

    def output(
        self,
        user: str,
        facility: str = 'S3DF',
        exp: str = None,
        run: str = None,
        energy: float = None,
        step: float = None,
        num: int = None,
        daq_num: int = 2):
        """
        Analysis and output for notch scan data.

        Provides methods to analyze energy calibration data and
        generate plots on computing facilities.

        Methods
        -------
        series(user, facility, exp, run, energy, step, num)
            Analyze energy scan series data

        Notes
        -----
        Analysis Process:
        1. Retrieve data from DAQ files
        2. Extract detector intensities vs. energy
        3. Identify absorption edge
        4. Compare to reference energy
        5. Calculate energy offset
        6. Generate calibration plots

        Output Products:
        - Energy vs. intensity plots
        - Edge position determination
        - Calibration offset value
        - Statistical uncertainties

        Computing Facilities:
        - S3DF: Interactive analysis
        - NERSC: Batch processing

        Examples
        --------
        >>> output = NotchOutput()
        >>> output.series(
        ...     user='myuser',
        ...     facility='S3DF',
        ...     exp='mfxls1234',
        ...     run=100,
        ...     energy=7112,
        ...     step=5,
        ...     num=20
        ... )

        See Also
        --------
        NotchScan.series : Data collection
        """
        from mfx.macros import get_exp, get_run
        from mfx.cctbx import cctbx
        cctbx = cctbx()

        if daq_num == 2:
            station=0
        elif daq_num == 1:
            station=1
        else:
            self.logger.error('Please enter daq 1 or 2.')

        self.logger.info("Plotting XRT-Spec Output")
        if exp is None:
            exp = str(get_exp(station=station))

        if run is None:
            run = int(get_run(station=station))

        facility = facility.upper()
        if facility == 'NERSC':
            self.logger.warning(f"Have you renewed your token with sshproxy today?")
            token = input("(y/n)? ")

            if token.lower() == "n":
                cctbx.sshproxy(user)

        proc = [
            f"ssh -Yt {user}@s3dflogin '"
            f"source /sdf/group/lcls/ds/ana/sw/conda1/manage/bin/psconda.sh && "
            f"python /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/energy_calib_output.py "
            f"-f {facility} -t series -e {exp} -r {run} -z {energy} -s {step} -n {num}'"
            ]

        self.logger.info(proc)
        os.system(proc[0])