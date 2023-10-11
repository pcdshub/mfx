def detector_image(node=5, det='Rayonix', calibdir=None, ave=1):
    """
    Launches detector monitor
    Parameters
    ----------
    node: int, optional
        Node to run detector monitor 1-9 only

    det: str, optional
        Detector name. Example 'Rayonix'

    calibdir: str, optional
        path to calib directory

    ave: int, optional
        Average over this number of events

    Operations
    ----------

    """
    import logging
    import subprocess
    from mfx.macros import get_exp

    proc = [
        f"ssh -YAC daq-mfx-mon0{node} "
        f". /reg/g/psdm/sw/conda1/manage/bin/psconda.sh -py3; "
        f"/cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/"
        f"detector_image.py -e {get_exp()} -d {det} -c {calibdir} -a {ave} &"
        ]
    
    logging.info(proc)

    subprocess.Popen(
        [proc], shell=True, 
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)