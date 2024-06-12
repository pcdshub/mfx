class cctbx:
    def __init__(self):
        from mfx.macros import get_exp
        self.settings = "~/.cctbx.xfe/settings_old.phil"
        self.experiment = str(get_exp())


    def check_settings(self):
        import logging
        import subprocess
        exp = self.experiment
        logging.info("Checking xfel gui phil File")
        cctbx_settings = open("/cds/home/opr/mfxopr/.cctbx.xfel/settings_s3df.phil", "r", encoding="UTF-8")
        setting_lines = cctbx_settings.readlines()
        change = False
        if setting_lines[4] != f'experiment =  "{exp}"':
            logging.warning(f"Changing experiment to current: {exp}")
            change = True
            settings = f'''\
facility {{
  name = *lcls standalone
  lcls {{
    experiment = "{exp}"
    web {{
      location = "S3DF"
    }}
  }}
}}
output_folder = "/sdf/data/lcls/ds/mfx/{exp}/results/common/results"
mp {{
  method = local lsf sge pbs *slurm shifter htcondor custom
  nnodes_index = 2
  nnodes_scale = 1
  nnodes_merge = 1
  nproc_per_node = 120
  queue = "milano"
  extra_options = " --account=lcls:{exp}  --reservation=lcls:onshift"
  env_script = "/sdf/group/lcls/ds/tools/cctbx/build/conda_setpaths.sh"
  phenix_script = "/sdf/group/lcls/ds/tools/cctbx/phenix/phenix-1.20.1-4487/phenix_env.sh"
}}
experiment_tag = "common"
db {{
  host = "172.24.5.182"
  name = "{exp}"
  user = "{exp}"
}}\
'''
        if change:
            cctbx_settings = open("/cds/home/opr/mfxopr/.cctbx.xfel/settings_s3df.phil", "w", encoding="UTF-8")
            cctbx_settings.writelines(settings)
            cctbx_settings.close

            subprocess.Popen(
                ["rsync -avze ssh ~/.cctbx.xfel/settings_s3df.phil djr@s3dflogin:~/.cctbx.xfel/settings_old.phil "],
                shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


    def xfel_gui(self):
        import logging
        import subprocess

        proc = [
            f"ssh -YAC mfxopr@daq-mfx-mon0{str(node)} "
            f"/cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/"
            f"detector_image.sh {experiment} {str(det)} {str(calibdir)} {str(ave)}"
            ]
        
        logging.info(proc)
        
        subprocess.Popen(
            proc, shell=True, 
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


        subprocess.Popen(
            [". /reg/g/cctbx/brewster/working/build/conda_setpaths.sh;cctbx.xfel &"],
            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)