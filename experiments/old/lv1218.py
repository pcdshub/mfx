from epics import caget, caput
from mfx.db import daq, elog
import numpy as np
from pcdsdaq.daq import BEGIN_TIMEOUT
BEGIN_TIMEOUT = 15
import requests
ws_url = "https://pswww.slac.stanford.edu/ws/lgbk"



class User():
    def current_run(self):
        resp = requests.get(ws_url + "/lgbk/ws/activeexperiment_for_instrument_station", {"instrument_name": 'mfx', "station": 0})
        exp = resp.json().get("value", {}).get("name")
        rundoc = requests.get(ws_url + "/lgbk/" + exp  + "/ws/current_run").json()["value"]
        run_number = (int(rundoc['num']))
        return(run_number)


    def flame_scan_2D(self, x_start, x_stop, x_step, y_start, y_stop, y_step, duration=180, record=True):
        issue = False
        counter = 0
        for x in np.arange(x_start, x_stop, x_step):
            for y in np.arange(y_start, y_stop, y_step):
                caput('MFX:USR:MMN:31.VAL', x, wait=True)
                caput('MFX:USR:MMN:32.VAL', y, wait=True)
                x_val = caget('MFX:USR:MMN:31')
                y_val = caget('MFX:USR:MMN:32')
                print("scanning point x = ", x_val, "y = ", y_val);
                try:            
                    print("starting daq")               
                    daq.connect()               
                    daq.begin(record=record, duration=duration, wait=False, end_run=True)
                    daq.wait()
                    counter = 0 #succes 
                    print("scan point finished correctly")
                except TimeoutError:
                    daq.end_run()
                    daq.disconnect()
                    print("TimeoutError on previous run, starting the next run")
                    counter += 1
                    if counter > 3:
                        print("Multiple timeout errors exiting script")
                        issue = True
                except KeyboardInterrupt:
                    print("Experiment stopped by user")
                    daq.end_run()
                    daq.disconnect()
                    issue = True
                if issue: break
            if issue: break
        print("script is finished, have a nice day!")
        
    def flame_scan_Y(self, y_start, y_stop, y_step, msg='',duration=180, record=True):
        issue = False
        counter = 0
        for y in np.arange(y_start, y_stop, y_step):
            caput('MFX:USR:MMN:32.VAL', y, wait=True)
            y_val = caget('MFX:USR:MMN:32')
            print("scanning point y = ", y_val);
            try:            
                print("starting daq")               
                daq.connect()               
                daq.begin(record=record, duration=duration, wait=False, end_run=True)
                message = msg+'\ny = '+str(y_val)+' mm ('+str(3.85-y_val)+' mm height above burner)'
                elog.post(message, run=self.current_run())
                daq.wait()
                counter = 0 #succes 
                print("scan point finished correctly")
            except TimeoutError:
                daq.end_run()
                daq.disconnect()
                print("TimeoutError on previous run, starting the next run")
                counter += 1
                if counter > 3:
                    print("Multiple timeout errors exiting script")
                    issue = True
            except KeyboardInterrupt:
                print("Experiment stopped by user")
                daq.end_run()
                daq.disconnect()
                issue = True
            if issue: break
        print("script is finished, have a nice day!")
