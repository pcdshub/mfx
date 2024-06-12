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


def makepeds(username, run_number):
    import os
    import logging
    logging.info("Making Pedestals")
    username = str(username)
    run_number = str(int(run_number))
    os.system(f"/reg/g/pcds/engineering_tools/latest-released/scripts/makepeds -q milano -r {run_number} -u {username}")


def awr(hutch='mfx'):
    import os
    import logging
    logging.info(f"{hutch} Beamline Check")
    os.system(f"/cds/home/opr/mfxopr/bin/awr {hutch}")


def restartdaq():
    import os
    import logging
    logging.info("Restarting the DAQ")
    os.system("/reg/g/pcds/engineering_tools/latest-released/scripts/restartdaq -w")

 
def cameras(time=12):   
    import os
    import logging
    logging.info("Opening Cam Viewer")
    os.system(f"/reg/g/pcds/engineering_tools/latest-released/scripts/camViewer -w {time}")