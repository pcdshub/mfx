# -*- coding: utf-8 -*-
"""
cctbx_start
"""
import argparse
import sys
import logging
import os
import subprocess

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)

def check_settings(exp, facility, cctbx_dir):
    logging.info("Checking xfel gui phil File")
    settings_S3DF = f'''\
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
  extra_options = " --account=lcls:{exp} --reservation=lcls:onshift"
  env_script = "/sdf/group/lcls/ds/tools/cctbx/build/conda_setpaths.sh"
  phenix_script = "/sdf/group/lcls/ds/tools/cctbx/phenix/phenix-1.20.1-4487/phenix_env.sh"
}}
experiment_tag = "common"
db {{
  host = "172.24.5.182"
  name = "{exp}"
  user = "{exp}"
  password = "lcls"
}}\
'''
    setting_NERSC = f'''\
facility {{
  name = *lcls standalone
  lcls {{
    experiment = "{exp}"
    web {{
      location = "NERSC"
    }}
  }}
}}
output_folder = "/pscratch/sd/c/cctbx/{exp[3:-2]}/common/results"
mp {{
  method = local lsf sge pbs *slurm shifter htcondor custom
  mpi_command = "srun"
  nnodes_index = 2
  nnodes_tder = 1
  nnodes_scale = 2
  nnodes_merge = 1
  nproc_per_node = 128
  queue = "realtime"
  wall_time = 45
  extra_options = "--account=lcls "
  extra_options = "--constraint=cpu"
  extra_options = "--time=120"
  env_script = "/global/common/software/cctbx/alcc-recipes/cctbx/activate.sh"
  phenix_script = ""
}}
experiment_tag = "common"
db {{
  host = "db-lb.{exp}.production.svc.spin.nersc.org"
  name = "{exp}"
  user = "user"
  password = "JohanWah1"
  server {{
    basedir = "/pscratch/sd/c/cctbx/p10033/common/results/MySql"
    root_password = ""
  }}
}}\
'''

    phil_file = f"{cctbx_dir}/settings.phil"
    if os.path.isfile(phil_file):
        cctbx_settings = open(phil_file, "r", encoding="UTF-8")
        setting_lines = cctbx_settings.readlines()
        change = False
        if setting_lines[3] != f'    experiment = "{exp}"\n':
            logging.warning(f"Changing experiment to current: {exp}")
            change = True
    else:
        logging.warning(f"settings.phil file doesn't exist. Writing new one for {exp}")
        change = True

    if change:
        settings = None
        if facility=='S3DF':
            settings = settings_S3DF
        elif facility=='NERSC':
            settings = setting_NERSC
        else:
            logging.warning("Facility not recognized.")
        if settings is not None:
            cctbx_settings = open(
                phil_file, "w", encoding="UTF-8")
            cctbx_settings.writelines(settings)
            cctbx_settings.close

def parse_args(args):
    """Parse command line parameters

    Args:
      args ([str]): command line parameters as list of strings

    Returns:
      :obj:`argparse.Namespace`: command line parameters namespace
    """
    parser = argparse.ArgumentParser(
        description="startup script for cctbx on iana."
    )
    parser.add_argument(
        "--username",
        "-u",
        dest="username",
        default=None,
        help="Enter -u to specify username",
    )
    parser.add_argument(
        "--experiment",
        "-e",
        dest="experiment",
        default=None,
        help="Enter -e to specify experiment number",
    )
    parser.add_argument(
        "--facility",
        "-f",
        dest="facility",
        default=None,
        help="Enter -f to specify facility",
    )
    parser.add_argument(
        "--debug",
        "-d",
        dest="debug",
        default=str(False),
        help="Enter -d to set debugging mode",
    )
    parser.add_argument(
        "--step",
        "-s",
        dest="step",
        default=None,
        help="Enter -s to setup step",
    )

    return parser.parse_args(args)


def main(args):
    """
    Main entry point allowing external calls
    Entry point for console_scripts
    Args:
      args ([str]): command line parameter list
    """
    args = parse_args(args)
    user = args.username
    exp = args.experiment
    facility = args.facility
    debug = bool(args.debug)
    step = args.step

    if int(step) == 1:

        logging.info("Starting up cctbx")

        if facility == "S3DF":
            preproc = None
            proc = [
                f"ssh -YAC psana "
                f"/sdf/group/lcls/ds/tools/mfx/scripts/cctbx/cctbx.sh "
                f"{user} {exp} {facility} 2 {str(debug)}"
            ]
        elif facility == "NERSC":
            preproc = [
                f"/sdf/group/lcls/ds/tools/mfx/scripts/cctbx/sshproxy.sh -c cctbx -u {user}"
            ]
            proc = [
                f"ssh -i ~/.ssh/cctbx -YAC cctbx@perlmutter-p1.nersc.gov "
                f"/global/common/software/lcls/mfx/scripts/cctbx/cctbx.sh "
                f"{user} {exp} {facility} 2 {str(debug)}"
            ]

        if preproc is not None:
            logging.info(preproc)
            os.system(preproc[0])

        logging.info(proc)
        if debug:
            os.system(proc[0])
        else:
            subprocess.Popen(
                proc, shell=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    else:

        if facility == "NERSC":
            cctbx_dir = f"/global/homes/c/cctbx/.cctbx.xfel"
        elif facility == "S3DF":
            cctbx_dir = f"/sdf/home/{user[0]}/{user}/.cctbx.xfel"
        else:
            cctbx_dir = None
            logging.warning(f"Facility not found: {facility}")

        if cctbx_dir is not None:
            if not os.path.exists(cctbx_dir):
                os.makedirs(cctbx_dir)
            #
            check_settings(exp, facility, cctbx_dir)




def run():
    """Entry point for console_scripts"""
    main(sys.argv[1:])


if __name__ == "__main__":
    run()