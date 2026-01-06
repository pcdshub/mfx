from ophyd import Component as Cpt
from ophyd.sim import SynAxis, FakeEpicsSignal, make_fake_device
from tfs.transfocator import Transfocator
from tfs.lens import MFXLens as RealLens

class SimLens(RealLens):
    _sig_z      = Cpt(FakeEpicsSignal,  ":Z",      auto_monitor=True)
    _sig_radius = Cpt(FakeEpicsSignal,  ":RADIUS", auto_monitor=True)
    _sig_focus  = Cpt(FakeEpicsSignal,  ":FOCUS",  auto_monitor=True)
    _inserted   = Cpt(FakeEpicsSignal,  ":STATE")
    _removed    = Cpt(FakeEpicsSignal,  ":OUT")
    _insert     = Cpt(FakeEpicsSignal,  ":INSERT")
    _remove     = Cpt(FakeEpicsSignal,  ":REMOVE")
    _state_logic = {'_inserted': {0: 'defer',  1: 'IN'},
                    '_removed': {0: 'defer', 1: 'OUT'}}

    def _do_move(self, state):
        if state.name == 'IN':
            self._insert.put(1)
            self._inserted.put(1)
            self._remove.put(0)
            self._removed.put(0)
        elif state.name == 'OUT':
            self._removed.put(1)
            self._remove.put(1)
            self._insert.put(0)
            self._inserted.put(0)
        else:
            raise ValueError("Invalid State {}".format(state))

class Stage(SynAxis):
    def attach(self, tfs_dev):
        self._lenses = [
            getattr(tfs_dev, nm)
            for nm in tfs_dev.component_names
            if isinstance(getattr(tfs_dev, nm), SimLens)
        ]

    def mv(self, value):
        delta = (value - self.position) / 1000 # lenses z are in m.
        st = self.set(value); st.wait()
        for l in getattr(self, "_lenses", []):
            l._sig_z.set(l._sig_z.get() + delta).wait()
        return st

FakeTransfocator = make_fake_device(Transfocator)

class SimTransfocator(FakeTransfocator):
    prefocus_top = Cpt(SimLens, ":DIA:03")
    prefocus_mid = Cpt(SimLens, ":DIA:02")
    prefocus_bot = Cpt(SimLens, ":DIA:01")
    tfs_02 = Cpt(SimLens, ":TFS:02")
    tfs_03 = Cpt(SimLens, ":TFS:03")
    tfs_04 = Cpt(SimLens, ":TFS:04")
    tfs_05 = Cpt(SimLens, ":TFS:05")
    tfs_06 = Cpt(SimLens, ":TFS:06")
    tfs_07 = Cpt(SimLens, ":TFS:07")
    tfs_08 = Cpt(SimLens, ":TFS:08")
    tfs_09 = Cpt(SimLens, ":TFS:09")
    tfs_10 = Cpt(SimLens, ":TFS:10")

def make_tfs_sim(tfs, prefix="SIM:", name="tfs_sim"):
    stage = Stage(name="stage")
    stage.set(tfs.translation.position).wait()
    stage.high_limit = tfs.translation.high_limit
    stage.low_limit  = tfs.translation.low_limit

    def _translation(self):
        return stage
    SimTransfocator.translation = property(_translation)

    tfs_sim = SimTransfocator(prefix=prefix, name=name)
    stage.attach(tfs_sim)

    for i in range(2, 10):
        real, sim = getattr(tfs, f"tfs_0{i}"), getattr(tfs_sim, f"tfs_0{i}")
        sim._sig_z.set(float(real.z)).wait()
        sim._sig_radius.set(float(real.radius)).wait()

    real, sim = getattr(tfs, "tfs_10"), getattr(tfs_sim, "tfs_10")
    sim._sig_z.set(float(real.z)).wait()
    sim._sig_radius.set(float(real.radius)).wait()

    for nm in ("prefocus_bot", "prefocus_mid", "prefocus_top"):
        real, sim = getattr(tfs, nm), getattr(tfs_sim, nm)
        sim._sig_z.set(float(real.z)).wait()
        sim._sig_radius.set(float(real.radius)).wait()

    return tfs_sim

