# -*- coding: utf-8 -*-
"""
fee_spec
"""
import logging
import os
import sys
import argparse

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)


def output(
        facility: str = "S3DF",
        run_type: str = None,
        exp: str = None,
        run: str = None,
        energy: float = None,
        step: float = None,
        num: int = None):
    """ Generates the output of the energy scan or series.

    Parameters:
        facility (str):
            Default: "S3DF". Options: "S3DF, NERSC
        type (str):
            specify whether it is a vernier 'scan' or 'series'
        exp (str): 
            experiment number. Current experiment by default
        run (str): 
            The run you'd like to process
        energy (float):
            specify the starting energy in eV (only for 'series')
        step (float):
            specify the energy step size in eV (only for 'series')
        num (int):
            specify the total number of runs (only for 'series')
    """

    if run_type != 'scan' or != 'series'
        logging.error("Enter -t to specify whether it is a vernier 'scan' or 'series'. Program Exit.")
        sys.exit()

    if facility == "NERSC":
        exp = exp[3:-2]
        proc = [
                f"ssh -i ~/.ssh/cctbx -YAC cctbx@perlmutter-p1.nersc.gov "
                f"/global/common/software/lcls/mfx/scripts/cctbx/energy_calib_output.sh "
                f"{facility} {run_type} {exp} {run} {energy} {step} {num}"
            ]
    elif facility == "S3DF":
        proc = [
                f"ssh -YAC psana "
                f"/sdf/group/lcls/ds/tools/mfx/scripts/cctbx/energy_calib_output.sh "
                f"{facility} {run_type} {exp} {run} {energy} {step} {num}"
            ]
    else:
        logging.error(f"Facility not found: {facility}. Program Exit.")
        sys.exit()

    logging.info(proc)
    os.system(proc[0])


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
        "--facility",
        "-f",
        dest="facility",
        default=None,
        help="Enter -f to specify facility",
    )
    parser.add_argument(
        "--type",
        "-t",
        dest="run_type",
        default=None,
        help="Enter -t to specify whether it is a vernier 'scan' or 'series'",
    )
    parser.add_argument(
        "--experiment",
        "-e",
        dest="experiment",
        default=None,
        help="Enter -e to specify experiment number",
    )
    parser.add_argument(
        "--run",
        "-r",
        dest="run",
        default=None,
        help="Enter -r for the run you'd like to process."
    )
    parser.add_argument(
        "--energy",
        "-z",
        dest="energy",
        default=None,
        help="Enter -z to specify the starting energy in eV (only for 'series')",
    )
    parser.add_argument(
        "--step",
        "-s",
        dest="step",
        default=None,
        help="Enter -s to specify the energy step size in eV (only for 'series')",
    )
    parser.add_argument(
        "--num",
        "-n",
        dest="num",
        default=None,
        help="Enter -n to specify the total number of runs (only for 'series')",
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
    facility = args.facility
    run_type = args.run_type
    exp = args.experiment
    run = args.run
    energy = args.energy
    step = args.step
    num = args.num

    output(facility, run_type, exp, run, energy, step, num)


def run():
    """Entry point for console_scripts"""
    main(sys.argv[1:])


if __name__ == "__main__":
    run()