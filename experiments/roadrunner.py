import numpy as np

from pcdsdevices.sequencer import EventSequencer


sequencer = EventSequencer('ECS:SYS0:7', name='mfx_sequencer')



def galil_sequence(pores_per_row, trig_delta=15, window_delta=5, neg_row_delta=20, pos_row_delta=25, n_windows=1):
    """ See GalilSequence for documentation """
    gseq = GalilSequence(trig_delta=15, window_delta=5, neg_row_delta=20, pos_row_delta=25, n_windows=1)
    return gseq.configure_sequencer(pores_per_row)


class GalilSequence:
    def __init__(self, trig_delta=15, window_delta=5, neg_row_delta=20, pos_row_delta=25, n_windows=1):
        """
        Parameters
        ----------
        trig_delay: int
            Delta_beam between Galil trigger and first pore aligned with beam
        window_delay: int
            Delta_beam between one window to the next in a row scan
        neg_row_delta: int
            Delta_beam when going to the end of an odd row to the next even row (before a right to left path)
        pos_row_delta: int
            Delta_beam between ending an even ro and reaching the first pore of the next odd row (before a left to right path)
        n_windows: int
            Nmber of windows that are being scanned in a single row pass.
        """
        self.trig_delta = trig_delta
        self.window_delta = window_delta
        self.neg_row_delta = neg_row_delta
        self.pos_row_delta = pos_row_delta
        self.n_windows = n_windows

        self.sequencer = sequencer

    @property
    def pos_row_delta(self):
        return self._pos_row_delta

    @pos_row_delta.setter
    def pos_row_delta(self, new_delta):
        """
        The trig_delta at the beginning of the sequence must be accounted for when
        looping the sequence.
        """
        self._pos_row_delta = new_delta - self.trig_delta

    def define_seq_elements(self):
        DAQ = [198, 0, 0, 0]
        DAQ_NEXT = [198, 1, 0, 0]
        TRIG_GALIL = [208, 0, 0, 0]
        TRIG_DELTA = [0, self.trig_delta, 0, 0]
        WINDOW = [0, self.window_delta, 0, 0]
        NEG = [0, self.neg_row_delta, 0, 0]
        POS = [0, self.pos_row_delta, 0, 0]
        return DAQ, DAQ_NEXT, TRIG_GALIL, TRIG_DELTA, WINDOW, NEG, POS

    def configure_sequencer(self, pores_per_row):
        # Clean up current sequence
        EMPTY = [0, 0, 0, 0]
        self.sequencer.sequence.put_seq([EMPTY for ii in range(2000)])

        DAQ, DAQ_NEXT, TRIG_GALIL, TRIG_DELTA, WINDOW, NEG, POS = self.define_seq_elements()

        # Trigger Galil and wait to reach the first pore
        sequence = [TRIG_GALIL, TRIG_DELTA]

        # Back and forth once
        for n_win in range(self.n_windows):
            sequence.append(DAQ)
            for ii in range(pores_per_row-1):
                sequence.append(DAQ_NEXT)
            if n_win != self.n_windows-1:  # we don't wait for the next window on the last window
                sequence.append(WINDOW)

        sequence.append(NEG)  # Wait to reach the first pore on the next line

        for n_win in range(self.n_windows):
            sequence.append(DAQ)
            for ii in range(pores_per_row-1):
                sequence.append(DAQ_NEXT)
            if n_win != self.n_windows-1:  # we don't wait for the next window on the last window
                sequence.append(WINDOW)

        sequence.append(POS)  # Wait to reach the first pore on the next line
        self.sequence = sequence
        #self.sequencer.sequence.put_seq(sequence)
        return sequence










