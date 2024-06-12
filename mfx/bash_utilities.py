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
    import subprocess
    import logging
    logging.info("Taking Pedestals")
    subprocess.Popen(
        ["/reg/g/pcds/engineering_tools/latest-released/scripts/takepeds"],
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def makepeds(username, run_number):
    import subprocess
    import logging
    logging.info("Making Pedestals")
    username = str(username)
    run_number = str(int(run_number))
    subprocess.Popen(
        [f"/reg/g/pcds/engineering_tools/latest-released/scripts/makepeds -q milano -r {run_number} -u {username}"],
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def awr(hutch='mfx'):
    import subprocess
    import logging
    logging.info("Making Pedestals")
    subprocess.Popen(
        [f"/cds/home/opr/mfxopr/bin/awr {hutch}"],
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)