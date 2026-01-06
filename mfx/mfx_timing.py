"""MFX timing and sequencer control for synchronized experiments."""

import logging
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)


class MFXTiming:
    """
    MFX timing controller for synchronized laser-X-ray experiments.

    Provides high-level control of event sequencers for precise timing
    of lasers, detectors, and pulse pickers relative to X-ray pulses.

    The timing system coordinates:
    - Laser triggers
    - Detector readout
    - Pulse picker operation
    - Sample environment triggers
    - Multi-shot experiments

    Components
    ----------
    seq1 : EventSequencer
        Main event sequencer (ECS:SYS0:7)
    seq2 : EventSequencer
        Spare event sequencer (ECS:SYS0:12)
    seq : EventSequencer
        Currently selected sequencer (seq1 or seq2)
    evt_code : Dict[str, int]
        Event code mapping
    sync_markers : Dict[float, int]
        Sync marker period mapping (Hz to marker ID)
    sequence : List[List]
        Current sequence being built

    Attributes
    ----------
    evt_code : dict
        Event codes for different triggers:
        - wait: 0 (no action)
        - pp_trig: 197 (pulse picker trigger)
        - daq_readout: 198 (DAQ readout trigger)
        - sample1-9: 201-209 (sample environment)
        - laser_on: 203 (laser Q-switch)
        - laser_off: 204 (laser blocked)
        - ray0-3: 210-213 (Rayonix detector)

    sync_markers : dict
        Synchronization periods (Hz):
        - 0.5 Hz: marker 0
        - 1 Hz: marker 1
        - 5 Hz: marker 2
        - 10 Hz: marker 3
        - 30 Hz: marker 4
        - 60 Hz: marker 5
        - 120 Hz: marker 6
        - 360 Hz: marker 7

    Notes
    -----
    Event Sequencer:
    - Generates event codes at precise times
    - Synchronized to accelerator RF
    - Sub-nanosecond jitter
    - Up to 2048 sequence steps

    Sequence Format:
    Each step: [event_code, delta_beam, fiducial, comment]
    - event_code: Trigger to send
    - delta_beam: Beam pulses to wait (120 Hz clock)
    - fiducial: Beam timing reference
    - comment: Sequence step ID

    Common Sequences:
    - 120 Hz: Full rep rate, all pulses
    - 60 Hz: Half rep rate, every other pulse
    - 30 Hz: Quarter rep rate, laser timing
    - Truncated: Reduced sequences for testing
    - Yano: Custom Yano-Kern group sequences

    Typical Applications:
    - Pump-probe experiments
    - Time-resolved studies
    - Multi-shot averaging
    - Background subtraction
    - Laser on/off comparison

    Examples
    --------
    Create timing controller:
    >>> from pcdsdevices.sequencer import EventSequencer
    >>> seq = EventSequencer('ECS:SYS0:7', name='mfx_seq')
    >>> timing = MFXTiming(seq)

    Load 120 Hz sequence:
    >>> timing.set_seq('120')

    Load 60 Hz sequence:
    >>> timing.set_seq('60')

    Load custom sequence with laser:
    >>> timing.set_seq('30', laser=['laser_on', 'laser_off'])

    Use spare sequencer:
    >>> timing.set_seq('120', sequencer='spare')

    See Also
    --------
    EventSequencer : Low-level sequencer control
    """

    def __init__(self, sequencer: Optional[object] = None):
        """
        Initialize MFX timing controller.

        Parameters
        ----------
        sequencer : EventSequencer or None, optional
            Main event sequencer object
            If None, creates sequencers internally
        """
        from pcdsdevices.sequencer import EventSequencer

        # Create or use provided sequencers
        if sequencer is None:
            self.seq1 = EventSequencer('ECS:SYS0:7', name='mfx_sequencer')
            self.seq2 = EventSequencer('ECS:SYS0:12', name='mfx_sequencer_spare')
        else:
            self.seq1 = sequencer
            self.seq2 = EventSequencer('ECS:SYS0:12', name='mfx_sequencer_spare')

        # Default to main sequencer
        self.seq = self.seq1

        # Event code mapping
        self.evt_code = {
            'wait': 0,
            'pp_trig': 197,
            'daq_readout': 198,
            'sample1': 201,
            'sample2': 202,
            'laser_on': 203,
            'laser_off': 204,
            'sample5': 205,
            'sample6': 206,
            'sample7': 207,
            'sample8': 208,
            'sample9': 209,
            'ray0': 210,
            'ray1': 211,
            'ray2': 212,
            'ray3': 213,
        }

        # Sync marker periods (Hz -> marker ID)
        self.sync_markers = {
            0.5: 0,
            1: 1,
            5: 2,
            10: 3,
            30: 4,
            60: 5,
            120: 6,
            360: 7
        }

        # Current sequence
        self.sequence = []

    def _seq_step(
            self,
            evt_code_name: Optional[str] = None,
            delta_beam: int = 0) -> List:
        """
        Create single sequence step.

        Parameters
        ----------
        evt_code_name : str or None, optional
            Event code name from self.evt_code
            If None, defaults to 'wait'
        delta_beam : int, optional
            Number of beam pulses to wait (default: 0)
            At 120 Hz, each count is 8.33 ms

        Returns
        -------
        List
            Sequence step: [event_code, delta_beam, fiducial, comment]

        Raises
        ------
        KeyError
            If evt_code_name not in self.evt_code

        Notes
        -----
        Sequence Step Format:
        - [0]: Event code (integer)
        - [1]: Beam pulse delay (integer)
        - [2]: Fiducial (always 0)
        - [3]: Comment (always 0)

        Beam Pulse Timing:
        - LCLS runs at 120 Hz max
        - 1 beam pulse = 1/120 s = 8.33 ms
        - delta_beam=0: Same beam pulse
        - delta_beam=1: Next beam pulse
        - delta_beam=2: Skip one pulse

        Examples
        --------
        Create wait step:
        >>> step = timing._seq_step('wait', 0)
        >>> print(step)
        [0, 0, 0, 0]

        Create laser trigger with delay:
        >>> step = timing._seq_step('laser_on', 1)
        >>> print(step)
        [203, 1, 0, 0]
        """
        if evt_code_name is None:
            evt_code_name = 'wait'

        try:
            event_code = self.evt_code[evt_code_name]
            return [event_code, delta_beam, 0, 0]
        except KeyError:
            logger.error(
                f"Event code '{evt_code_name}' not found. "
                f"Available codes: {list(self.evt_code.keys())}"
            )
            raise

    def _seq_init(self, sync_mark: float = 30):
        """
        Initialize sequence with sync marker.

        Clears current sequence and sets synchronization marker.
        Must be called before building new sequence.

        Parameters
        ----------
        sync_mark : float, optional
            Sync marker period in Hz (default: 30)
            Valid values: 0.5, 1, 5, 10, 30, 60, 120, 360

        Returns
        -------
        None

        Raises
        ------
        KeyError
            If sync_mark not in valid periods

        Notes
        -----
        Sync Marker:
        - Defines sequence repeat rate
        - Ensures timing synchronization
        - Must match desired rep rate

        Initialization:
        1. Set sync marker
        2. Clear sequence buffer
        3. Fill with wait steps
        4. Upload to sequencer

        Sequence Buffer:
        - 15 wait steps initially
        - Will be overwritten by actual sequence
        - Ensures clean start state

        Examples
        --------
        Initialize for 120 Hz:
        >>> timing._seq_init(sync_mark=120)

        Initialize for 30 Hz (laser timing):
        >>> timing._seq_init(sync_mark=30)
        """
        from time import sleep

        try:
            marker_id = self.sync_markers[sync_mark]
        except KeyError:
            logger.error(
                f"Invalid sync marker: {sync_mark} Hz. "
                f"Valid values: {list(self.sync_markers.keys())}"
            )
            raise

        # Set sync marker
        self.seq.sync_marker.put(marker_id)

        # Clear sequence
        self.sequence = []

        # Create empty sequence with wait steps
        sequence = []
        for _ in range(15):
            sequence.append(self._seq_step('wait', 0))

        # Upload to sequencer
        self.seq.sequence.put_seq(sequence)
        sleep(1)

        logger.info(f"Sequence initialized with {sync_mark} Hz sync marker")

    def _seq_put(self, steps: List[Tuple[str, int]]):
        """
        Add steps to sequence and upload.

        Parameters
        ----------
        steps : List[Tuple[str, int]]
            List of (event_code_name, delta_beam) tuples

        Returns
        -------
        None

        Notes
        -----
        Process:
        1. Convert each (name, delay) to full step
        2. Append to current sequence
        3. Upload complete sequence to hardware

        Sequence Upload:
        - Atomic operation
        - Replaces entire sequence
        - Takes effect immediately

        Examples
        --------
        Add laser on/off steps:
        >>> steps = [
        ...     ('laser_on', 1),
        ...     ('daq_readout', 0),
        ...     ('laser_off', 1),
        ...     ('daq_readout', 0)
        ... ]
        >>> timing._seq_put(steps)
        """
        for step in steps:
            self.sequence.append(self._seq_step(step[0], step[1]))

        self.seq.sequence.put_seq(self.sequence)
        logger.debug(f"Uploaded sequence with {len(self.sequence)} steps")

    # ==================== Predefined Sequences ====================

    def _seq_120hz(self) -> List[Tuple[str, int]]:
        """
        120 Hz sequence - full rep rate Rayonix readout.

        Returns
        -------
        List[Tuple[str, int]]
            Sequence steps for 120 Hz operation

        Notes
        -----
        Sequence Pattern (repeats every 33.3 ms):
        - ray0 trigger + 1 beam pulse delay
        - DAQ readout
        - ray1 trigger + 1 beam pulse delay
        - DAQ readout
        - ray2 trigger + 1 beam pulse delay
        - DAQ readout
        - ray3 trigger + 1 beam pulse delay
        - DAQ readout

        Use Cases:
        - Maximum data rate
        - Bright samples
        - Fast dynamics
        - High statistics needed

        Detector: Rayonix (4 readout channels)
        """
        steps = [
            ['ray0', 1],
            ['daq_readout', 0],
            ['ray1', 1],
            ['daq_readout', 0],
            ['ray2', 1],
            ['daq_readout', 0],
            ['ray3', 1],
            ['daq_readout', 0]
        ]
        return steps

    def _seq_120hz_truncated(self) -> List[Tuple[str, int]]:
        """
        120 Hz truncated sequence - single channel readout.

        Returns
        -------
        List[Tuple[str, int]]
            Truncated sequence steps

        Notes
        -----
        Sequence Pattern (repeats every 8.33 ms):
        - ray0 trigger + 1 beam pulse delay
        - DAQ readout

        Use Cases:
        - Testing
        - Single channel operation
        - Reduced data rate

        Detector: Rayonix channel 0 only
        """
        steps = [
            ['ray0', 1],
            ['daq_readout', 0]
        ]
        return steps

    def _seq_120hz_yano(self) -> List[Tuple[str, int]]:
        """
        120 Hz Yano sequence - single Rayonix channel.

        Returns
        -------
        List[Tuple[str, int]]
            Yano sequence steps for 120 Hz

        Notes
        -----
        Sequence Pattern:
        - ray1 trigger + 1 beam pulse delay
        - DAQ readout

        Use Cases:
        - Yano-Kern group experiments
        - Channel 1 readout
        - Custom triggering

        Detector: Rayonix channel 1
        """
        steps = [
            ['ray1', 1],
            ['daq_readout', 0]
        ]
        return steps

    def _seq_90hz_yano(self) -> List[Tuple[str, int]]:
        """
        90 Hz Yano sequence with pulse picker.

        Returns
        -------
        List[Tuple[str, int]]
            Yano sequence steps for 90 Hz

        Notes
        -----
        Sequence Pattern (repeats every 44.4 ms):
        - ray1 trigger + 1 beam pulse
        - Pulse picker trigger
        - sample1 trigger + 1 beam pulse
        - DAQ readout
        - ray1 trigger + 1 beam pulse
        - DAQ readout
        - wait + 1 beam pulse
        - DAQ readout

        Use Cases:
        - 90 Hz operation (3/4 of 120 Hz)
        - Pulse picker synchronization
        - Sample environment triggering

        Timing:
        - 3 active pulses per 4 beam pulses
        - 27 ms period
        """
        steps = [
            ['ray1', 1],
            ['pp_trig', 0],
            ['sample1', 1],
            ['daq_readout', 0],
            ['ray1', 1],
            ['daq_readout', 0],
            ['wait', 1],
            ['daq_readout', 0]
        ]
        return steps

    def _seq_60hz(self) -> List[Tuple[str, int]]:
        """
        60 Hz sequence - half rep rate with pulse picker.

        Returns
        -------
        List[Tuple [str, int]]
            Sequence steps for 60 Hz operation

        Notes
        -----
        Sequence Pattern (repeats every 66.7 ms):
        - ray0 trigger + 1 beam pulse
        - Pulse picker trigger
        - ray1 trigger + 1 beam pulse
        - DAQ readout
        - ray2 trigger + 1 beam pulse
        - Pulse picker trigger
        - ray3 trigger + 1 beam pulse
        - DAQ readout

        Use Cases:
        - Standard pump-probe
        - Laser synchronization
        - Background subtraction (flipflop)
        - Reduced data rate

        Detector: Rayonix (4 channels)
        Pulse Picker: Active every other pulse
        """
        steps = [
            ['ray0', 1],
            ['pp_trig', 0],
            ['ray1', 1],
            ['daq_readout', 0],
            ['ray2', 1],
            ['pp_trig', 0],
            ['ray3', 1],
            ['daq_readout', 0]
        ]
        return steps

    def _seq_60hz_truncated(self) -> List[Tuple[str, int]]:
        """
        60 Hz truncated sequence - simplified readout.

        Returns
        -------
        List[Tuple[str, int]]
            Truncated sequence steps

        Notes
        -----
        Sequence Pattern (repeats every 33.3 ms):
        - ray0 trigger + 1 beam pulse
        - ray1 readout
        - ray2 trigger + 1 beam pulse
        - DAQ readout

        Use Cases:
        - Testing
        - Simplified operation
        - Two-channel readout
        """
        steps = [
            ['ray0', 1],
            ['ray1', 0],
            ['ray2', 1],
            ['daq_readout', 0]
        ]
        return steps

    def _seq_60hz_yano(self) -> List[Tuple[str, int]]:
        """
        60 Hz Yano sequence - dual channel readout.

        Returns
        -------
        List[Tuple[str, int]]
            Yano sequence steps for 60 Hz

        Notes
        -----
        Sequence Pattern:
        - ray1 trigger + 1 beam pulse
        - ray2 trigger + 1 beam pulse
        - DAQ readout

        Use Cases:
        - Yano-Kern group 60 Hz
        - Two-channel operation
        """
        steps = [
            ['ray1', 1],
            ['ray2', 1],
            ['daq_readout', 0]
        ]
        return steps

    def _seq_30hz(self) -> List[Tuple[str, int]]:
        """
        30 Hz sequence - quarter rep rate for laser timing.

        Returns
        -------
        List[Tuple[str, int]]
            Sequence steps for 30 Hz operation

        Notes
        -----
        Sequence Pattern (repeats every 133 ms):
        - ray0 trigger + 1 beam pulse
        - Pulse picker trigger
        - ray1 trigger + 1 beam pulse
        - ray2 trigger + 1 beam pulse
        - DAQ readout
        - ray3 trigger + 1 beam pulse

        Use Cases:
        - Laser pump-probe (30 Hz lasers)
        - Time-resolved studies
        - Damage-sensitive samples
        - Lower data rates

        Timing:
        - 1 pulse per 4 beam pulses
        - 33.3 ms period
        - Matches 30 Hz laser rep rate
        """
        steps = [
            ['ray0', 1],
            ['pp_trig', 0],
            ['ray1', 1],
            ['ray2', 1],
            ['daq_readout', 0],
            ['ray3', 1]
        ]
        return steps

    def _seq_20hz(self) -> List[Tuple[str, int]]:
        """
        20 Hz sequence - reduced rep rate.

        Returns
        -------
        List[Tuple[str, int]]
            Sequence steps for 20 Hz operation

        Notes
        -----
        Sequence Pattern (repeats every 200 ms):
        - ray0 trigger + 1 beam pulse
        - Pulse picker trigger
        - ray1 trigger + 1 beam pulse
        - ray2 trigger + 1 beam pulse
        - DAQ readout
        - wait + 1 beam pulse (x2)
        - ray3 trigger + 1 beam pulse

        Use Cases:
        - Very slow processes
        - Damage-sensitive samples
        - Low flux requirements

        Timing:
        - 1 pulse per 6 beam pulses
        - 50 ms period
        """
        steps = [
            ['ray0', 1],
            ['pp_trig', 0],
            ['ray1', 1],
            ['ray2', 1],
            ['daq_readout', 0],
            ['wait', 1],
            ['wait', 1],
            ['ray3', 1]
        ]
        return steps

    def _seq_10hz(self) -> List[Tuple[str, int]]:
        """
        10 Hz sequence - very low rep rate.

        Returns
        -------
        List[Tuple[str, int]]
            Sequence steps for 10 Hz operation

        Notes
        -----
        Sequence Pattern (repeats every 400 ms):
        - ray0 trigger + 1 beam pulse
        - Pulse picker trigger
        - ray1 trigger + 1 beam pulse
        - ray2 trigger + 1 beam pulse
        - DAQ readout
        - wait + 1 beam pulse (x8)
        - ray3 trigger + 1 beam pulse

        Use Cases:
        - Extremely slow processes
        - Maximum damage prevention
        - Minimal flux

        Timing:
        - 1 pulse per 12 beam pulses
        - 100 ms period
        """
        steps = [
            ['ray0', 1],
            ['pp_trig', 0],
            ['ray1', 1],
            ['ray2', 1],
            ['daq_readout', 0],
            ['wait', 1],
            ['wait', 1],
            ['wait', 1],
            ['wait', 1],
            ['wait', 1],
            ['wait', 1],
            ['wait', 1],
            ['wait', 1],
            ['ray3', 1]
        ]
        return steps

    # ==================== High-Level Sequence Control ====================

    def set_seq(
            self,
            rep: Optional[str] = None,
            sequencer: Optional[str] = None,
            laser: Optional[List[str]] = None):
        """
        Set event sequencer with predefined pattern.

        Loads and activates one of the predefined timing sequences.
        Optionally adds laser triggers for pump-probe experiments.

        Parameters
        ----------
        rep : str or None, optional
            Repetition rate pattern:
            - '120': Full 120 Hz
            - '120_truncated': Single channel 120 Hz
            - '120_yano': Yano 120 Hz
            - '90_yano': Yano 90 Hz
            - '60': Standard 60 Hz
            - '60_truncated': Simplified 60 Hz
            - '60_yano': Yano 60 Hz
            - '30': Laser timing 30 Hz
            - '20': Low rate 20 Hz
            - '10': Minimal rate 10 Hz
        sequencer : str or None, optional
            Sequencer selection:
            - 'main' or None: Use seq1
            - 'spare': Use seq2
        laser : List[str] or None, optional
            Laser event codes to add
            Example: ['laser_on', 'laser_off']

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If rep not recognized
            If sequencer not recognized
            If laser event code not found

        Notes
        -----
        Sequence Selection:
        - Each rep rate has optimized pattern
        - Automatically sets sync marker
        - Clears previous sequence
        - Uploads new sequence

        Sequencer Selection:
        - Main (seq1): Standard use
        - Spare (seq2): Testing or backup

        Laser Integration:
        - Adds laser triggers to sequence
        - Maintains timing relationships
        - Common patterns:
          - ['laser_on', 'laser_off']: Alternating
          - ['laser_on']: Continuous
          - ['laser_off']: Blocked

        Sync Markers by Rep Rate:
        - 120 Hz: 120 Hz marker
        - 90 Hz: 60 Hz marker
        - 60 Hz: 60 Hz marker
        - 30 Hz: 30 Hz marker
        - 20/10 Hz: 10 Hz marker

        Examples
        --------
        Standard 120 Hz:
        >>> timing.set_seq('120')

        60 Hz with laser:
        >>> timing.set_seq('60', laser=['laser_on', 'laser_off'])

        Use spare sequencer:
        >>> timing.set_seq('30', sequencer='spare')

        Yano sequence:
        >>> timing.set_seq('120_yano')

        See Also
        --------
        _seq_init : Initialize sequence
        _seq_put : Upload sequence
        """
        # Select sequencer
        if sequencer is None or sequencer == 'main':
            self.seq = self.seq1
            logger.info("Using main sequencer (seq1)")
        elif sequencer == 'spare':
            self.seq = self.seq2
            logger.info("Using spare sequencer (seq2)")
        else:
            logger.error(
                f"Unknown sequencer: {sequencer}. Use 'main' or 'spare'"
            )
            raise ValueError("Invalid sequencer")

        # Load sequence based on rep rate
        if rep == '120':
            self._seq_init(sync_mark=120)
            self._seq_put(self._seq_120hz())
            logger.info("Loaded 120 Hz sequence")

        elif rep == '120_truncated':
            self._seq_init(sync_mark=120)
            self._seq_put(self._seq_120hz_truncated())
            logger.info("Loaded 120 Hz truncated sequence")

        elif rep == '120_yano':
            self._seq_init(sync_mark=120)
            self._seq_put(self._seq_120hz_yano())
            logger.info("Loaded 120 Hz Yano sequence")

        elif rep == '90_yano':
            self._seq_init(sync_mark=60)
            self._seq_put(self._seq_90hz_yano())
            logger.info("Loaded 90 Hz Yano sequence")

        elif rep == '60':
            self._seq_init(sync_mark=60)
            self._seq_put(self._seq_60hz())
            logger.info("Loaded 60 Hz sequence")

        elif rep == '60_truncated':
            self._seq_init(sync_mark=60)
            self._seq_put(self._seq_60hz_truncated())
            logger.info("Loaded 60 Hz truncated sequence")

        elif rep == '60_yano':
            self._seq_init(sync_mark=120)
            self._seq_put(self._seq_60hz_yano())
            logger.info("Loaded 60 Hz Yano sequence")

        elif rep == '30':
            self._seq_init(sync_mark=30)
            self._seq_put(self._seq_30hz())
            logger.info("Loaded 30 Hz sequence")

        elif rep == '20':
            self._seq_init(sync_mark=10)
            self._seq_put(self._seq_20hz())
            logger.info("Loaded 20 Hz sequence")

        elif rep == '10':
            self._seq_init(sync_mark=10)
            self._seq_put(self._seq_10hz())
            logger.info("Loaded 10 Hz sequence")

        else:
            logger.error(
                f"Unknown rep rate: {rep}. "
                "Valid options: 120, 120_truncated, 120_yano, 90_yano, "
                "60, 60_truncated, 60_yano, 30, 20, 10"
            )
            raise ValueError("Invalid rep rate")

        # Add laser triggers if requested
        if laser is not None:
            logger.info(f"Adding laser triggers: {laser}")
            laser_steps = []
            for laser_code in laser:
                if laser_code not in self.evt_code:
                    logger.error(
                        f"Unknown laser code: {laser_code}. "
                        f"Available: {list(self.evt_code.keys())}"
                    )
                    raise ValueError("Invalid laser event code")
                laser_steps.append([laser_code, 0])

            self._seq_put(laser_steps)
            logger.info("Laser triggers added to sequence")

        self.seq.start()


# Convenience instance for direct import
mfx_timing = None  # Will be initialized with sequencer in beamline.py


def set_timing(
        rep: str,
        sequencer: Optional[str] = None,
        laser: Optional[List[str]] = None):
    """
    Convenience function to set timing sequence.

    Parameters
    ----------
    rep : str
        Repetition rate: '120', '60', '30', etc.
    sequencer : str or None, optional
        'main' or 'spare'
    laser : List[str] or None, optional
        Laser event codes

    Returns
    -------
    None

    Examples
    --------
    >>> set_timing('120')
    >>> set_timing('60', laser=['laser_on', 'laser_off'])

    See Also
    --------
    MFXTiming.set_seq : Full implementation
    """
    if mfx_timing is None:
        logger.error("MFX timing not initialized. Use MFXTiming class directly.")
        return

    mfx_timing.set_seq(rep=rep, sequencer=sequencer, laser=laser)