import time

from ophyd.signal import EpicsSignal, EpicsSignalRO


class Watchman:
    cbid = None
    retries = 3

    def __init__(self, door_state, voltage_read, voltage_write):
        self.door_state = EpicsSignalRO(door_state)
        self.mesh_voltage = EpicsSignal(voltage_read,
                                        write_pv=voltage_write)
        print('Using door pv {}'.format(door_state))

    def start(self):
        """Sets up self.callback to be run when door state changes"""
        # Make sure we don't start 2 processes
        self.stop()
        print('Starting door watcher')
        self.door_state.subscribe(self.callback)

    def callback(self, old_value=None, value=None, **kwargs):
        """To be run every time the door state changes"""
        print('Door PV changed from {} to {}'.format(old_value, value))
        if old_value == 1 and value == 0:
            print('Zeroing the mesh voltage because door was opened')
            # Let's retry a few times in case of a network error
            for i in range(self.retries):
                try:
                    self.mesh_voltage.put(0)
                except Exception:
                    pass

    def stop(self):
        """Shutdown the watcher"""
        if self.cbid is not None:
            print('Stopping door watcher')
            self.door_state.unsubscribe(self.cbid)
            self.cbid = None


def main():
    watcher = Watchman(
        'PPS:FEH1:45:DOORA',
        'MFX:USR:ai1:1',
        'MFX:USR:ao1:0')

    # If door already open, maybe we crashed? Let's be safe and turn it off.
    if watcher.door_state.get() == 0:
        print('Door is already open! Setting to zero at startup')
        watcher.mesh_voltage.put(0)

    watcher.start()
    try:
        # Start a loop for user text feedback.
        # We want reassurance that the program is still running.
        while True:
            print('Door watcher still running. Door PV is {}, '
                  'mesh voltage is {}'.format(watcher.door_state.get(),
                                              watcher.mesh_voltage.get()*1000))
            time.sleep(5)
    except KeyboardInterrupt:
        print('Watcher shutting down')
    finally:
        watcher.stop()


if __name__ == '__main__':
    main()
