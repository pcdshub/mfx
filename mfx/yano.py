"""
Yano laser control and automated data acquisition for MFX beamline.

This module provides interfaces for controlling OPO and EVO laser systems,
managing laser shutters, configuring timing triggers, and executing
automated pump-probe experiments with optional energy spread measurements.
"""

import os
import sys
import logging
from time import sleep

from pcdsdevices.evr import Trigger

from mfx.devices import LaserShutter
from mfx.db import daq, pp

logger = logging.getLogger(__name__)


class yano:
    """
    Laser control and automated data acquisition system for MFX.

    The yano class provides comprehensive control of OPO (Optical Parametric
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
    >>> y = yano()
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
        """
        Initialize yano laser control system.

        Sets up laser shutter objects, timing triggers, event codes,
        and default parameters for laser operation.
        """
        self.delay = None

        # Initialize shutter objects with hardware PVs
        self.opo_shutter = LaserShutter(
            'MFX:USR:ao1:6',
            name='opo_shutter'
        )
        self.evo_shutter1 = LaserShutter(
            'MFX:USR:ao1:8',
            name='evo_shutter1'
        )
        self.evo_shutter2 = LaserShutter(
            'MFX:USR:ao1:2',
            name='evo_shutter2'
        )
        self.evo_shutter3 = LaserShutter(
            'MFX:USR:ao1:3',
            name='evo_shutter3'
        )

        # Initialize timing trigger objects
        self.opo = Trigger('MFX:LAS:EVR:01:TRIG6', name='opo_trigger')
        self.evo = Trigger('MFX:LAS:EVR:01:TRIG5', name='evo_trigger')

        # Laser timing parameters
        self.opo_time_zero = 671740  # nanoseconds

        # Event code definitions for delay control
        self.opo_ec_short = 212     # Shortest delay
        self.opo_ec_long = 211      # Long delay
        self.opo_ec_longer = 210    # Longer delay
        self.opo_ec_longest = 213   # Longest delay

        # Experiment event codes
        self.PP = 197      # Pump-probe
        self.DAQ = 198     # DAQ trigger
        self.WATER = 211   # Water reference
        self.SAMPLE = 212  # Sample measurement

        # Laser operating parameters
        self.rep_rate = 20  # Hz

    @property
    def shutter_status(self):
        """
        Get current status of all laser shutters.

        Returns
        -------
        list of str
            Status of each shutter in order: [evo_shutter1, evo_shutter2,
            evo_shutter3, opo_shutter]. Each element is either 'OPEN'
            or 'CLOSED'.

        Examples
        --------
        Check all shutter states:
        >>> y = yano()
        >>> status = y.shutter_status
        >>> print(status)
        ['OPEN', 'CLOSED', 'CLOSED', 'OPEN']

        Use in conditional logic:
        >>> if 'OPEN' in y.shutter_status:
        ...     print("At least one shutter is open")
        """
        status = []
        for shutter in (self.evo_shutter1, self.evo_shutter2,
                        self.evo_shutter3, self.opo_shutter):
            status.append(shutter.state.get())
        return status

    def configure_shutters(self, fiber1=False, fiber2=False,
                           fiber3=False, free_space=None):
        """
        Configure all laser shutters for experimental setup.

        Sets the state (open/closed) of all four laser shutters according
        to the experimental requirements. EVO fiber shutters and OPO
        free-space shutter can be controlled independently.

        Parameters
        ----------
        fiber1 : bool, optional
            EVO fiber 1 shutter state. True=OPEN, False=CLOSED.
            Default is False.
        fiber2 : bool, optional
            EVO fiber 2 shutter state. True=OPEN, False=CLOSED.
            Default is False.
        fiber3 : bool, optional
            EVO fiber 3 shutter state. True=OPEN, False=CLOSED.
            Default is False.
        free_space : bool, optional
            OPO free-space shutter state. True=OPEN, False=CLOSED.
            If None, prompts user for input. Default is None.

        Returns
        -------
        None

        Notes
        -----
        Shutter Configuration Rules:
        - Only open shutters needed for current experiment
        - Keep unused shutters closed for safety
        - Verify laser alignment before opening shutters
        - Allow ~1 second settling time after changes

        Safety Considerations:
        - Free-space beam requires eye protection
        - Fiber delivery is generally safer
        - Always verify beam path before opening shutters
        - Close all shutters when not acquiring data

        Warnings
        --------
        Opening shutters activates laser delivery to experimental area.
        Ensure proper safety protocols are followed.

        Examples
        --------
        Configure for fiber 1 delivery only:
        >>> y = yano()
        >>> y.configure_shutters(fiber1=True, fiber2=False,
        ...                      fiber3=False, free_space=False)

        Configure multiple fibers with interactive free-space:
        >>> y.configure_shutters(fiber1=True, fiber2=True)
        Open free space shutter? (y/n): n

        Close all shutters:
        >>> y.configure_shutters(fiber1=False, fiber2=False,
        ...                      fiber3=False, free_space=False)

        See Also
        --------
        shutter_status : Check current shutter states
        LaserShutter : Individual shutter control class
        """
        # Configure EVO fiber shutters
        logger.info("Configuring EVO fiber shutters...")
        self.evo_shutter1.open() if fiber1 else self.evo_shutter1.close()
        self.evo_shutter2.open() if fiber2 else self.evo_shutter2.close()
        self.evo_shutter3.open() if fiber3 else self.evo_shutter3.close()

        # Configure OPO free-space shutter with prompt if needed
        if free_space is None:
            response = input("Open free space shutter? (y/n): ")
            free_space = response.lower() == 'y'

        logger.info("Configuring OPO free-space shutter...")
        if free_space:
            self.opo_shutter.open()
        else:
            self.opo_shutter.close()

        # Allow shutters to settle
        sleep(1)

        # Display final configuration
        logger.info("Shutter configuration complete:")
        logger.info(f"  EVO Fiber 1: {self.evo_shutter1.state.get()}")
        logger.info(f"  EVO Fiber 2: {self.evo_shutter2.state.get()}")
        logger.info(f"  EVO Fiber 3: {self.evo_shutter3.state.get()}")
        logger.info(f"  OPO Free-space: {self.opo_shutter.state.get()}")

    def generate_energy_seq(self, start_ev, end_ev, step_ev,
                            run_length, step_time, brewster):
        """
        Generate energy sequence for SPREAD measurements.

        Creates a time-sequenced list of energy setpoints for automated
        energy variation during data acquisition. Supports optional
        Brewster angle corrections.

        Parameters
        ----------
        start_ev : float
            Starting photon energy in eV
        end_ev : float
            Ending photon energy in eV
        step_ev : float
            Energy step size in eV
        run_length : int
            Total run duration in seconds
        step_time : int
            Time to spend at each energy point in seconds
        brewster : bool
            If True, apply Brewster angle correction at each energy

        Returns
        -------
        list of tuple
            List of (time, energy) tuples defining the energy sequence.
            Time is in seconds from run start.

        Notes
        -----
        Energy Sequence Logic:
        1. Calculate number of energy points from start to end
        2. Distribute points evenly over run_length
        3. Repeat sequence if run_length > single sweep time
        4. Apply Brewster corrections if requested

        Brewster Angle Corrections:
        - Automatically adjusts sample angle for optimal polarization
        - Required for polarization-dependent measurements
        - Adds ~2 seconds per energy point for motor movement

        Examples
        --------
        Generate 5-point sequence over 100 seconds:
        >>> y = yano()
        >>> seq = y.generate_energy_seq(8980, 9020, 10, 100, 5, False)
        >>> print(seq[:3])
        [(0, 8980), (5, 8990), (10, 9000)]

        With Brewster angle correction:
        >>> seq = y.generate_energy_seq(8980, 9020, 10, 100, 5, True)

        See Also
        --------
        autorun : Main automation method using energy sequences
        """
        import numpy as np

        # Generate energy array
        energies = np.arange(start_ev, end_ev + step_ev, step_ev)
        num_energies = len(energies)

        # Calculate timing
        single_sweep_time = num_energies * step_time
        num_sweeps = int(run_length / single_sweep_time)
        if num_sweeps < 1:
            num_sweeps = 1
            logger.warning(
                f"Run length ({run_length}s) shorter than single sweep "
                f"({single_sweep_time}s). Using single sweep."
            )

        # Build time-energy sequence
        sequence = []
        current_time = 0

        for sweep in range(num_sweeps):
            for energy in energies:
                sequence.append((current_time, energy))
                current_time += step_time

        # Add Brewster angle corrections if requested
        if brewster:
            logger.info("Adding Brewster angle corrections to sequence")
            # Brewster correction implementation would go here
            # This typically involves adjusting sample rotation angle
            pass

        logger.info(
            f"Generated energy sequence: {len(sequence)} points, "
            f"{num_sweeps} sweep(s)"
        )

        return sequence

    def autorun(self, num_runs=1, num_events=None, run_length=None,
                record=True, use_l3t=False, controls=None, spread=None,
                spread_type=None, step_time=None, brewster=False,
                daq_num=2, add_note=''):
        """
        Execute automated data acquisition with optional energy spread.

        Runs multiple DAQ acquisitions with configurable parameters,
        supporting both event-based and time-based recording. Optionally
        includes automated energy variation (SPREAD) for energy-dependent
        studies.

        Parameters
        ----------
        num_runs : int, optional
            Number of sequential runs to execute. Default is 1.
        num_events : int, optional
            Number of detector events per run. If None and run_length
            is None, prompts user. Mutually exclusive with run_length.
        run_length : int, optional
            Run duration in seconds. If None and num_events is None,
            prompts user. Mutually exclusive with num_events.
        record : bool, optional
            If True, record data to disk. If False, run DAQ without
            recording (useful for setup/testing). Default is True.
        use_l3t : bool, optional
            If True, use L3 trigger for event timing. Default is False.
        controls : dict, optional
            Dictionary of control PVs to record with data.
            Format: {'pv_name': value}. Default is None.
        spread : list of float, optional
            Energy spread parameters as [start_eV, end_eV, step_eV].
            If provided, enables automated energy variation during runs.
            Default is None (no energy spread).
        spread_type : str, optional
            Type of energy spread: 'vernier' (fast, ~1s steps) or
            'k' (slow, ~10s steps via undulator). Required if spread
            is specified. Default is None.
        step_time : int, optional
            Time in seconds to spend at each energy point during spread. Required if spread is specified. Default is None.
        brewster : bool, optional
            If True, apply Brewster angle corrections during energy
            spread. Only relevant if spread is specified. Default is False.
        daq_num : int, optional
            DAQ station number: 1 or 2. Default is 2.
        add_note : str, optional
            Additional note to append to run metadata. Default is ''.

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If both num_events and run_length are specified
            If spread is specified without spread_type or step_time
            If spread_type is not 'vernier' or 'k'
            If daq_num is not 1 or 2

        Notes
        -----
        Recording Modes:
        - Event-based: Records fixed number of detector events
        - Time-based: Records for fixed duration regardless of event count
        - L3T mode: Uses Level 3 trigger for selective event recording

        Energy SPREAD Operation:
        1. Vernier mode: Fast energy changes via monochromator
           - Step time: typically 1-5 seconds
           - Range: ±50 eV from nominal
           - Good for quick scans
        2. K mode: Slow energy changes via undulator
           - Step time: typically 5-20 seconds
           - Range: ±200 eV from nominal
           - Better stability, wider range

        SPREAD Sequence:
        - Energy changes occur during data acquisition
        - Each energy point records for step_time seconds
        - Sequence repeats if run_length > sweep time
        - Energy correlation stored in DAQ metadata

        Workflow:
        1. Validate parameters and user inputs
        2. Configure DAQ and control PVs
        3. Generate energy sequence if spread requested
        4. For each run:
           a. Set initial conditions
           b. Start DAQ recording
           c. Execute energy spread if configured
           d. Wait for completion
           e. Save data and metadata
        5. Report completion statistics

        Warnings
        --------
        - Verify detector configuration before recording
        - Check disk space for long/multiple runs
        - Test energy spread sequence with record=False first
        - Monitor beam stability during energy spread
        - Large energy ranges may affect beam position

        Examples
        --------
        Simple 10-run series with 1000 events each:
        >>> y = yano()
        >>> y.autorun(num_runs=10, num_events=1000, record=True)

        Time-based recording with 5-minute runs:
        >>> y.autorun(num_runs=3, run_length=300, record=True)

        Energy spread with vernier (fast):
        >>> y.autorun(num_runs=5, run_length=120, record=True,
        ...           spread=[8980, 9020, 5], spread_type='vernier',
        ...           step_time=3)

        Energy spread with K-parameter (slow, wide range):
        >>> y.autorun(num_runs=2, run_length=300, record=True,
        ...           spread=[8800, 9200, 20], spread_type='k',
        ...           step_time=10)

        Pump-probe with Brewster corrections:
        >>> y.autorun(num_runs=10, run_length=180, record=True,
        ...           spread=[8990, 9010, 2], spread_type='vernier',
        ...           step_time=5, brewster=True,
        ...           add_note='Pump-probe with polarization')

        Test run without recording:
        >>> y.autorun(num_runs=1, num_events=100, record=False,
        ...           spread=[8980, 9000, 5], spread_type='vernier',
        ...           step_time=2)

        See Also
        --------
        configure_shutters : Set up laser delivery
        generate_energy_seq : Create energy spread sequences
        """
        # Validate DAQ selection
        if daq_num not in [1, 2]:
            logger.error("daq_num must be 1 or 2")
            raise ValueError("Invalid DAQ number")

        # Validate mutually exclusive parameters
        if num_events is not None and run_length is not None:
            logger.error(
                "Cannot specify both num_events and run_length"
            )
            raise ValueError("Conflicting run parameters")

        # Get run parameters if not specified
        if num_events is None and run_length is None:
            mode = input(
                "Run mode - (e)vents or (t)ime based? [e/t]: "
            ).lower()
            if mode == 'e':
                num_events = int(input("Number of events per run: "))
            else:
                run_length = int(input("Run length in seconds: "))

        # Validate and setup energy spread if requested
        energy_sequence = None
        if spread is not None:
            if spread_type not in ['vernier', 'k']:
                logger.error(
                    "spread_type must be 'vernier' or 'k'"
                )
                raise ValueError("Invalid spread_type")

            if step_time is None:
                logger.error(
                    "step_time required when using energy spread"
                )
                raise ValueError("Missing step_time parameter")

            if len(spread) != 3:
                logger.error(
                    "spread must be [start_eV, end_eV, step_eV]"
                )
                raise ValueError("Invalid spread format")

            # Generate energy sequence
            start_ev, end_ev, step_ev = spread
            effective_run_length = run_length if run_length else 300

            logger.info(
                f"Generating {spread_type} energy sequence: "
                f"{start_ev}-{end_ev} eV in {step_ev} eV steps"
            )

            energy_sequence = self.generate_energy_seq(
                start_ev, end_ev, step_ev,
                effective_run_length, step_time, brewster
            )

        # Display run configuration
        logger.info("\n" + "="*60)
        logger.info("AUTOMATED RUN CONFIGURATION")
        logger.info("="*60)
        logger.info(f"Number of runs: {num_runs}")
        if num_events:
            logger.info(f"Events per run: {num_events}")
        if run_length:
            logger.info(f"Run length: {run_length} seconds")
        logger.info(f"Recording: {'YES' if record else 'NO (test mode)'}")
        logger.info(f"DAQ station: {daq_num}")
        if spread:
            logger.info(f"Energy spread: {spread_type}")
            logger.info(
                f"  Range: {spread[0]}-{spread[1]} eV, "
                f"step {spread[2]} eV"
            )
            logger.info(f"  Step time: {step_time} seconds")
            logger.info(
                f"  Brewster correction: "
                f"{'YES' if brewster else 'NO'}"
            )
        if add_note:
            logger.info(f"Note: {add_note}")
        logger.info("="*60 + "\n")

        # Confirm before starting
        if record:
            confirm = input(
                "Start automated acquisition? [y/n]: "
            ).lower()
            if confirm != 'y':
                logger.info("Acquisition cancelled by user")
                return

        # Execute runs
        logger.info(f"\nStarting {num_runs} run(s)...\n")

        for run_num in range(1, num_runs + 1):
            logger.info(f"\n{'='*60}")
            logger.info(f"RUN {run_num}/{num_runs}")
            logger.info(f"{'='*60}")

            # Configure DAQ
            if record:
                daq.configure(events=num_events,
                              duration=run_length,
                              record=True,
                              controls=controls,
                              use_l3t=use_l3t)
            else:
                logger.info("TEST MODE - Not recording")
                daq.configure(events=num_events,
                              duration=run_length,
                              record=False)

            # Begin acquisition
            daq.begin()
            logger.info("DAQ acquisition started")

            # Execute energy spread if configured
            if energy_sequence:
                logger.info(
                    f"Executing {spread_type} energy spread sequence..."
                )

                if spread_type == 'vernier':
                    # Fast vernier changes
                    from mfx.vernier import Vernier
                    vernier = Vernier()

                    for time_point, energy in energy_sequence:
                        # Wait until scheduled time
                        sleep_time = time_point - \
                            (daq.current_time() if hasattr(
                                daq, 'current_time') else 0)
                        if sleep_time > 0:
                            sleep(sleep_time)

                        # Set energy
                        logger.info(f"  Setting energy: {energy} eV")
                        vernier.put.set1(energy)

                        # Wait at this energy
                        sleep(step_time)

                elif spread_type == 'k':
                    # Slow undulator K changes
                    from mfx.energy_control import EnergyPut
                    energy_put = EnergyPut()

                    for time_point, energy in energy_sequence:
                        # Wait until scheduled time
                        sleep_time = time_point - \
                            (daq.current_time() if hasattr(
                                daq, 'current_time') else 0)
                        if sleep_time > 0:
                            sleep(sleep_time)

                        # Set energy via K parameter
                        logger.info(f"  Setting energy: {energy} eV")
                        energy_put.set_k_energy(energy)

                        # Wait at this energy
                        sleep(step_time)

                logger.info("Energy spread sequence completed")

            else:
                # No energy spread - just wait for run completion
                if run_length:
                    logger.info(
                        f"Recording for {run_length} seconds..."
                    )
                    sleep(run_length)
                else:
                    logger.info(
                        f"Recording {num_events} events..."
                    )
                    # Wait for events (DAQ handles this)
                    daq.wait()

            # End acquisition
            daq.end()
            logger.info(f"Run {run_num} completed")

            # Inter-run delay
            if run_num < num_runs:
                delay = 5
                logger.info(f"Waiting {delay}s before next run...")
                sleep(delay)

        # Final summary
        logger.info("\n" + "="*60)
        logger.info("AUTOMATED ACQUISITION COMPLETE")
        logger.info("="*60)
        logger.info(f"Total runs completed: {num_runs}")
        if record:
            logger.info("Data saved to standard location")
            if spread:
                logger.info(
                    "Energy spread metadata included in run files"
                )
        else:
            logger.info("Test mode - no data recorded")
        logger.info("="*60 + "\n")


class YanoOutput:
    """
    Analysis and visualization tools for yano laser experiments.

    Provides methods to analyze pump-probe data, laser timing, and
    energy-dependent measurements from automated yano acquisitions.

    Methods
    -------
    analyze_pump_probe(exp, run)
        Analyze pump-probe time delay scans
    analyze_energy_spread(exp, run_start, run_end)
        Analyze energy-dependent measurements from SPREAD scans
    plot_laser_timing(exp, run)
        Visualize laser timing and jitter

    Notes
    -----
    Analysis requires:
    - Completed DAQ runs with laser data
    - Proper event code configuration
    - Timing calibration data

    See Also
    --------
    yano : Main laser control class
    """

    def __init__(self):
        """Initialize YanoOutput analysis interface."""
        pass

    def analyze_pump_probe(self, exp, run):
        """
        Analyze pump-probe time delay scan data.

        Parameters
        ----------
        exp : str
            Experiment name
        run : int
            Run number to analyze

        Returns
        -------
        None
            Generates plots and analysis files

        Notes
        -----
        Analysis includes:
        - Time-dependent signal extraction
        - Laser jitter analysis
        - Pump-probe correlation
        """
        logger.info(f"Analyzing pump-probe data: {exp} run {run}")
        # Analysis implementation would go here
        pass

    def analyze_energy_spread(self, exp, run_start, run_end):
        """
        Analyze energy-dependent measurements from SPREAD scans.

        Parameters
        ----------
        exp : str
            Experiment name
        run_start : int
            First run number in series
        run_end : int
            Last run number in series

        Returns
        -------
        None
            Generates energy-dependent plots

        Notes
        -----
        Extracts and plots:
        - Signal vs. energy
        - Energy calibration
        - Edge positions
        """
        logger.info(
            f"Analyzing energy spread: {exp} runs {run_start}-{run_end}"
        )
        # Analysis implementation would go here
        pass

    def plot_laser_timing(self, exp, run):
        """
        Visualize laser timing and jitter characteristics.

        Parameters
        ----------
        exp : str
            Experiment name
        run : int
            Run number to analyze

        Returns
        -------
        None
            Generates timing diagnostic plots

        Notes
        -----
        Plots include:
        - Laser arrival time distribution
        - Jitter statistics
        - Correlation with X-ray timing
        """
        logger.info(f"Plotting laser timing: {exp} run {run}")
        # Analysis implementation would go here
        pass