def xfel_gui():
    import subprocess
    subprocess.Popen(
        [". /reg/g/cctbx/brewster/working/build/conda_setpaths.sh;cctbx.xfel &"],
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)