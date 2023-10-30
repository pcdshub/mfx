def xfel_gui():
    import subprocess
    import logging
    from mfx.macros import get_exp

    logging.info("Checking ExptParams File")
    cctbx_settings = open("/cds/home/opr/mfxopr/.cctbx.xfel/settings_old.phil", "r", encoding="UTF-8")
    setting_lines = cctbx_settings.readlines()
    change = False

    if setting_lines[10] != f'name = "{get_exp()}"':
        logging.warning(f"Changing experiment to current: {get_exp()}")
        setting_lines[10] = f'name = "{get_exp()}"'
        change = True

    if setting_lines[11] != f'user = "{get_exp()}"':
        logging.warning(f"Changing experiment to current: {get_exp()}")
        setting_lines[11] = f'user = "{get_exp()}"'
        change = True

    if change:
        cctbx_settings = open("/cds/home/opr/mfxopr/.cctbx.xfel/settings_old.phil", "w", encoding="UTF-8")
        cctbx_settings.writelines(setting_lines)
        cctbx_settings.close

    subprocess.Popen(
        [". /reg/g/cctbx/brewster/working/build/conda_setpaths.sh;cctbx.xfel &"],
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)