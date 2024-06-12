def xfel_gui():
    import subprocess
    import logging
    from mfx.macros import get_exp

    logging.info("Checking xfel gui phil File")
    cctbx_settings = open("/cds/home/opr/mfxopr/.cctbx.xfel/settings_old.phil", "r", encoding="UTF-8")
    setting_lines = cctbx_settings.readlines()
    change = False

    if setting_lines[10] != f'name = "{get_exp()}"':
        logging.warning(f"Changing experiment to current: {get_exp()}")
        setting_lines[10] = f'  name = "{get_exp()}"\n'
        change = True

    if setting_lines[11] != f'user = "{get_exp()}"':
        logging.warning(f"Changing experiment to current: {get_exp()}")
        setting_lines[11] = f'  user = "{get_exp()}"\n'
        change = True

    if change:
        cctbx_settings = open("/cds/home/opr/mfxopr/.cctbx.xfel/settings.phil", "w", encoding="UTF-8")
        cctbx_settings.writelines(setting_lines)
        cctbx_settings.close

    subprocess.Popen(
        [". /reg/g/cctbx/brewster/working/build/conda_setpaths.sh;cctbx.xfel &"],
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    

def takepeds():
    import os
    import logging
    logging.info("Taking Pedestals")
    os.system(f"/reg/g/pcds/engineering_tools/latest-released/scripts/takepeds")


def makepeds(username, run_number=None):
    import os
    import logging
    from mfx.db import daq
    from mfx.macros import get_exp
    logging.info("Making Pedestals")
    if run_number is None:
        run_number = daq.run_number()
    username = str(username)
    run_number = str(int(run_number))
    os.system(f"ssh -Y {username}@s3dflogin ssh -Y psana /sdf/group/lcls/ds/tools/engineering_tools/engineering_tools/scripts/makepeds_psana --queue milano --run {run_number} --experiment {get_exp()}")


def awr(hutch='mfx'):
    import os
    import logging
    logging.info(f"{hutch} Beamline Check")
    os.system(f"/cds/home/opr/mfxopr/bin/awr {hutch}")


def restartdaq():
    import subprocess
    import logging
    logging.info("Restarting the DAQ")
    subprocess.Popen(
        ["/reg/g/pcds/engineering_tools/latest-released/scripts/restartdaq -w"],
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    #os.system("/reg/g/pcds/engineering_tools/latest-released/scripts/restartdaq -w")

 
def cameras(time=12):   
    import subprocess
    import logging
    logging.info("Opening Cam Viewer")
    subprocess.Popen(
        [f"/reg/g/pcds/engineering_tools/latest-released/scripts/camViewer -w {time}"],
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    #os.system(f"/reg/g/pcds/engineering_tools/latest-released/scripts/camViewer -w {time}")