"""
Take a pedestal for the Jungfrau
"""
import time
import socket
import argparse

from pydaq import Control
from blbase.daq_config_device import Dcfg
from pswww import pypsElog


gainmodes = ['Normal','ForcedGain1','ForcedGain2']
daq = Control(socket.gethostname(), 4)
#elog = pypElog.pypsElog()
hutch = 'mfx'
aliases = ['BEAM']


class Jungfrau(Dcfg):
    """
    Class for the Jungfrau. Provides a way to Jungfrau
    configurations from within a hutch python session.
    """
    def __init__(self, hutch, src, *aliases):
        """
        Programatically sets up get_name and set_name methods during init.
        """
        # Need to pass src if not MfxEndstation.0:Jungfrau.0
        #In [34]: psana.DetInfo(48,0,43,1)
        # Out[34]: DetInfo(MfxEndstation.0:Jungfrau.1)
        self.src = src
        Dcfg.__init__(self, hutch, *aliases, src=src, typeid=0x3006b)
        self._add_methods("gainMode", "gainMode")
        self._jfGainMode = {'FixedGain1': 1,
                           'FixedGain2': 2,
                           'ForcedGain1': 3,
                           'ForcedGain2': 4,
                           'HighGain0': 5,
                           'Normal': 0}

    def gainName(self, gain=0):
        for key in self._jfGainMode:
            if self._jfGainMode[key]==gain:
                return key


    def commit(self):
        """
        Commits all changes to the database using the current stored config dict
        """
        Dcfg.commit(self)


def takeJungfrauPedestals(record=True, nEvts=1000):
    """
    Take Jungfrau Pedestals for all Jungfrau detectors.
    """
    daq.connect()

    srcs = []
    # get the list of Jungfrau in the partition
    for node in daq.partition()['nodes']:
        if node['record'] and (((node['phy'] & 0xff00) >> 8) ==43):
            srcs.append(node['phy'])
    jfs = [ Jungfrau(hutch, src, *aliases) for src in srcs ]

    for jf in jfs:
        currMode=jf.get_gainmode()
        print('current mode for {} : {}'.format(jf.src, jf.gainName(currMode)))
    for thisgainmode in gainmodes:
        for jf in jfs:
            print('Collecting pedestal for {} with mode {}'.format(jf.src,  thisgainmode))
            if isinstance(thisgainmode, basestring):
                thisgainmode_string = thisgainmode
                thisgainmode = jf._jfGainMode[thisgainmode]
            else:
                thisgainmode_string = jf.gainName(thisgainmode)
            print('switching gainmode to ',thisgainmode_string)
            if jf.get_gainmode()!= thisgainmode:
                jf.set_gainmode(thisgainmode)
                jf.commit()

                if jf.get_gainmode() != thisgainmode:
                    print('waiting for gain to switch from ',jf.gainName(jf.get_gainmode()),' to ', thisgainmode_string)
                while jf.get_gainmode() != thisgainmode:
                    time.sleep(0.5)

        daq.configure(events=0, record=record)
        print('take run for gain ',thisgainmode_string)
        daq.begin(events=nEvts)
        daq.end()
        daq.endrun()
        print('took run %d for gain %s with %d events'%(daq.runnumber(),thisgainmode_string, nEvts))

    for jf in jfs:
        jf.set_gainmode(0)
        jf.commit()
    print('now call makepeds -J -r ',int(daq.runnumber())-2)
    daq.disconnect()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('nevents', type=int, help='Number of events')
    parser.add_argument('--record', action='store_true',
                        help='Option to record')
    args = parser.parse_args()
    takeJungfrauPedestals(record=args.record, nEvts=args.nevents)
