class MFX_Timing:
    def __init__(self,sequencer=None):
        from pcdsdevices.sequencer import EventSequencer
        from time import sleep
        self.seq1 = EventSequencer('ECS:SYS0:7', name='mfx_sequencer')
        self.seq2 = EventSequencer('ECS:SYS0:12', name='mfx_sequencer_spare')

        self.evt_code = {
            'wait':0,
            'pp_trig':197,
            'daq_readout':198,
            'laser_on':203,
            'laser_off':204,
            'ray_readout':210,
            'ray1':211,
            'ray2':212,
            'ray3':213,
        }
        self.sync_markers = {0.5:0, 1:1, 5:2, 10:3, 30:4, 60:5, 120:6, 360:7}
        self.sequence = []


    def _seq_step(self, evt_code_name=None, delta_beam=0):
        try:
            return [self.evt_code[evt_code_name], delta_beam, 0, 0]
        except:
            print('Error: event sequencer step not recognized.')


    def _seq_init(self, sync_mark=30):
        self.seq.sync_marker.put(self.sync_markers[sync_mark])
        self.sequence = []
        sequence = []
        for ii in range(15):
            sequence.append(self._seq_step('wait', 0))
        self.seq.sequence.put_seq(sequence)
        sleep(1)


    def _seq_put(self, steps):
        for step in steps:
            self.sequence.append(self._seq_step(step[0], step[1]))
        self.seq.sequence.put_seq(self.sequence)


    def _seq_120hz(self):
        steps = [['ray_readout', 1],
                 ['daq_readout',0],
                 ['ray1',1],
                 ['daq_readout',0],
                 ['ray2',1],
                 ['daq_readout',0],
                 ['ray3',1],
                 ['daq_readout', 0]]
        return steps


    def _seq_120hz_trucated(self):
        steps = [['ray_readout', 1],
                 ['daq_readout',0]]
        return steps


    def _seq_60hz(self):
        steps = [['ray_readout', 1],
                 ['pp_trig', 0],
                 ['ray1', 1],
                 ['daq_readout', 0],
                 ['ray2', 1],
                 ['pp_trig', 0],
                 ['ray3', 1],
                 ['daq_readout', 0]]
        return steps


    def _seq_60hz_trucated(self):
        steps = [['ray_readout', 1],
                 ['ray1', 0],
                 ['ray2', 1],
                 ['daq_readout', 0]]
        return steps


    def _seq_30hz(self):
        steps = [['ray_readout', 1],
                 ['pp_trig', 0],
                 ['ray1', 1],
                 ['ray2', 1],
                 ['daq_readout', 0],
                 ['ray3', 1]]
        return steps


    def _seq_20hz(self):
        steps = [['ray_readout', 1],
                 ['pp_trig', 0],
                 ['ray1', 1],
                 ['ray2', 1],
                 ['daq_readout', 0],
                 ['ray3', 1],
                 ['ray3', 1],
                 ['ray3', 1]]
        return steps


    def set_seq(self, rep=None, sequencer=None, laser=None):
        if sequencer == 2:
            self.seq = self.seq1
        else:
            self.seq = self.seq2
        if laser:
            if rep is None or rep == 120:
                self._seq_init(sync_mark=120)
                for laser_evt in laser_evt_list:
                    sequence = self._seq_120hz_trucated()
                    block = sequence[:-1]
                    block.append(laser_evt)
                    block.append(sequence[-1])
                    self._seq_put(block)
            elif rep == 60:
                self._seq_init(sync_mark=120)
                for laser_evt in laser_evt_list:
                    sequence = self._seq_60hz_trucated()
                    block = sequence[:-1]
                    block.append(laser_evt)
                    block.append(sequence[-1])
                    self._seq_put(block)
            elif rep == 30:
                self._seq_init(sync_mark=30)
                for laser_evt in laser_evt_list:
                    sequence = self._seq_30hz()
                    block = sequence[:-1]
                    block.append(laser_evt)
                    block.append(sequence[-1])
                    self._seq_put(block)
            elif rep == 20:
                self._seq_init(sync_mark=60)
                for laser_evt in laser_evt_list:
                    sequence = self._seq_20hz()
                    block = sequence[:-1]
                    block.append(laser_evt)
                    block.append(sequence[-1])
                    self._seq_put(block)
        else:
            if rep is None or rep == 120:
                self._seq_init(sync_mark=120)
                self._seq_put(self._seq_120hz())
            elif rep == 60:
                self._seq_init(sync_mark=60)
                self._seq_put(self._seq_60hz())
            elif rep == 30:
                self._seq_init(sync_mark=30)
                self._seq_put(self._seq_30hz())
            elif rep == 20:
                self._seq_init(sync_mark=20)
                self._seq_put(self._seq_20hz())

        self.seq.start()
        return self.sequence

    def check_seq(self):
        for line in self.sequence:
            print(line)