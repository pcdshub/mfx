**Version:** March 2025  

### Pedestals
1. Insert the shutter
2. Take pedestals using the [bs.takepeds](bash_utilities.html) command
``` py
bs.takepeds() # Press enter when prompted
```
3. Make pedestals [bs.makepeds](bash_utilities.html) command
``` py
bs.makepeds("USERNAME",onshift=True) # Enter unix account password when prompted  
```
4. Re-allocate the DAQ
    - From the DAQ control window dropdown menu select "shutdown", then select "allocate", and then "begin running"
5. Remove the shutter

### Autorun Command
1. Run the [autorun](autorun.html) command providing the following parameters:
    - The `sample` details
    - The `tag` details
    - the `run_length` in seconds
    - The number of `runs` to record

``` py
autorun(sample="SAMPLE DETAILS", tag="TAG", run_length=300, record=True, runs=3, picker="flip")
```
2. Stopping autorun: ctrl+C once

### Free Running the DAQ
1. In DAQ control window, from dropdown menu select "begin running"

### Restart the DAQ
1. From the hutch python session run the [bs.restartdaq](bash_utilities.html) command
``` py
bs.restartdaq()
```
2. Load ami/ami2 configurations
    1. In DAQ Online Monitoring window under Setup: Load **Daniel3.ami**
    2. In AMI client window: open **test_kern.fc**

### Shut Down
1. Open the hutch
2. Remove mirror (MR1L4 OUT)
3. Remove XRT spectrometer (Move OUT!)
4. Turn off epix detectors (first idle, then off)
5. Close gas canisters

### Attenuate Beam
1. From hutch python use the command `att([fraction transmitted])`, for example:
``` py
# Full beam
att(1)
# 1% beam
att(0.01)
```

### Contact Staff
Call staff **ONLY** using the phone next to the hutch access panel. 
