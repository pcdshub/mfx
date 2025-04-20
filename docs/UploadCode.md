**Version:** April 2025  

This is a procedure for uploading and testing scripts on MFX-DAQ

### Test a branch 
These are the steps to test a branch while not affecting the main hutch python setup on mfx-daq  

1. Clone the `mfx` repository into home, e.g. `/cds/home/f/fpoitevi/mfx`

2. Checkout the branch you want to work on

	a. `git fetch --all`

	b. `git checkout -b <branch name>`

3. Put local repo in python path: `export PYTHONPATH={PWD}:$PYTHONPATH`

4. Edit the `conf.yaml` file to speed up hutch python session loading. For example:

```py
hutch: mfx

# Locate happi database
db: /reg/g/pcds/pyps/apps/hutch-python/device_config/db.json

# Hutch-specific imports
#load: mfx.beamline

#daq_platform:
#  default: 0

#experiment: lu5017
``` 
5. Source the mfx environment: `source /cds/group/pcds/pyps/apps/hutch-python/mfx/mfxenv`  
6. Launch a hutch python session with their edited configuration: `hutch-python --cfg conf.yaml` (or `conf.yml`)

```python
In [1]: from mfx.macros import FakeDetector

In [2]: jf16m = FakeDetector('jungfrau16M')

In [3]: jf16m.resolution_coverage(energy_kev=9.8, det_dist_mm=100)
### FakeDetector jungfrau16M resolution range:
### - Energy: 9.8 keV
### - Distance: 100 mm
>>> Low q    :  0.45 Å⁻¹ | 14.10 Å
>>> High q   :  4.73 Å⁻¹ |  1.33 Å (detector edge)
>>> Highest q:  5.36 Å⁻¹ |  1.17 Å (detector corner)
```

###Troubleshooting 🛠️

Accessing your home directory

1. `ssh` into `s3df`, e.g. `ssh <username>@s3dflogin.slac.stanford.edu`

2. `ssh` into `ps` nodes, e.g. `psdev`, `psbuild-rhel7`, etc.
Alternatively, you can access `cds` home directory on `mfx-daq` or `mfx-monitor`

Configure web proxy settings on a per-host basis.
```bash
# Tools like ``wget`` or ``curl`` will use the environment variable settings to
# proxy requests through the host "psproxy.pcdsn".
case $(hostname -s) in
    # Hosts with direct Internet access
    psbuild-* | pslogin* | cent7* )
        unset http_proxy;
        unset https_proxy;
        ;;

    # Hosts with no access to psproxy.pcdsn
     mcclogin | lcls-* )
        unset http_proxy;
        unset https_proxy;
        ;;

    # Other hosts likely do not have direct Internet access
    * )
        export http_proxy=http://psproxy.pcdsn:3128;
        export https_proxy=http://psproxy.pcdsn:3128;
        ;;
esac
```

Add the following to `~/.ssh/cofig`

```python
Host s3df
    Hostname s3dflogin.slac.stanford.edu
    User <user name>
    ForwardAgent yes

Host psana
    Hostname psana
    User pam
    ProxyCommand ssh s3df -W %h:%p
    ForwardAgent yes

# PCDS: https://github.com/pcdshub/shared-dotfiles/blob/master/on_site/ssh/config

Match host github.com exec "echo ${http_proxy} | grep psproxy"
    ProxyJump psproxy.pcdsn

Host github.com
    HostName github.com
    User git
    ForwardAgent no
    ForwardX11 no
    ForwardX11Trusted no
    PreferredAuthentications=publickey
    RequestTTY no
    UpdateHostKeys yes

Host *
    ForwardAgent yes
    ForwardX11 yes
    ForwardX11Trusted yes
    PreferredAuthentications=gssapi-with-mic,publickey,password

#### other sutff

ServerAliveInterval 10
```




