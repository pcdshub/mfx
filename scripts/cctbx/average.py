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

def average(exp, run, facility, debug):
    logging.info(f"Making an average for run: {run}")
    run = str(run).zfill(4)
    run = f'r{run}'

    if facility == "NERSC":
        exp = exp[3:-2]
        proc = [
                f"ssh -i ~/.ssh/cctbx -YAC cctbx@perlmutter-p1.nersc.gov "
                f"sbatch /global/common/software/lcls/mfx/scripts/cctbx/average.sh "
                f"{exp} {facility} {run}"
            ]
    elif facility == "S3DF":
        proc = [
                f"ssh -YAC psana "
                f"sbatch /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/average.sh "
                f"{exp} {facility} {run}"
            ]
    else:
        logging.warning(f"Facility not found: {facility}")

    logging.info(proc)
    if debug:
        os.system(proc[0])
    else:
        subprocess.Popen(
            proc, shell=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

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
        "--run",
        "-r",
        dest="run",
        default=None,
        help="Enter -r for the run number",
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
    exp = args.experiment
    facility = args.facility
    debug = bool(args.debug)
    run = args.run

    average(exp, run, facility, debug)


def run():
    """Entry point for console_scripts"""
    main(sys.argv[1:])


if __name__ == "__main__":
    run()
