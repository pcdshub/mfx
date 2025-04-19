# mfx
Repository for MFX specific code

# Documentation
The documentation is available on [github pages](https://pcdshub.github.io/mfx/) and on [S3DF pages](https://s3df.slac.stanford.edu/data/lcls/mfx/). 

# Usage
## Jupyter notebook
### Setting up the Jupyter server
Adapted from [PCDShub instructions](https://github.com/pcdshub/hutch-python/blob/master/docs/hutch_python.ipynb).

First, you need to source mfxenv to get the right env variables for the jupyter kernel. This makes the jupyter kernel find the mfx beamline files and makes the DAQ work. Note that this locks your terminal session to being compatible with exactly one particular version of the DAQ.
```bash
mfxopr@mfx-monitor:~$ source /cds/group/pcds/pyps/apps/hutch-python/mfx/mfxenv
Loading NFS python env pcds-5.9.1
```
This also lets you register the python env for use in the notebook if you haven't already done this:
```bash
mfxopr@mfx-monitor:~$ python -m ipykernel install --user --name=pcds-5.9.1
Installed kernelspec pcds-5.9.1 in /cds/home/opr/mfxopr/.local/share/jupyter/kernels/pcds-5.9.1
```
Then you can run the notebook from the same session. We store notebooks under `/cds/home/opr/mfxopr/jupyter`.
```bash
(pcds-5.9.1)mfxopr@mfx-monitor:jupyter$ jupyter-notebook
```
If you want to control the DAQ, then the jupyter-nootback process must be run on the same linux host that the DAQ is running on.