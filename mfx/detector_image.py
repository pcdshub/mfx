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

    experiment = str(get_exp())

    proc = [
        f"ssh -YAC mfxopr@daq-mfx-mon0{str(node)} "
        f"/cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/"
        f"detector_image.sh {experiment} {str(det)} {str(calibdir)} {str(ave)}"
        ]
    
    logging.info(proc)
	
    subprocess.Popen(
        proc, shell=True, 
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def detector_image_kill(node=5):
    """
    Kills all detector monitors made with this script

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

    proc = [
        f"ssh -YAC mfxopr@daq-mfx-mon0{str(node)} " +
        f"/cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/"
        f"detector_image_kill.sh"
        ]
    
    logging.info(proc)
	
    subprocess.Popen(
        proc, shell=True)
