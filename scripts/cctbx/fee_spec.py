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
        exp: str = None,
        runs: list = [],
        facility: str = "S3DF"):
    """Don't use this in hutch python.

    Parameters:

        exp (str): 
            experiment number. Current experiment by default

        run_list (list): 
            List of run numbers. Last run number by default

        facility (str): Default: "S3DF". Options: "S3DF, NERSC".
    """
    if facility == "NERSC":
        exp = exp[3:-2]
        proc = [
                f"ssh -i ~/.ssh/cctbx -YAC cctbx@perlmutter-p1.nersc.gov "
                f"/global/common/software/lcls/mfx/scripts/cctbx/fee_spec.sh "
                f"{runs} {facility}"
            ]
    elif facility == "S3DF":
        proc = [
                f"ssh -YAC psana "
                f"/sdf/group/lcls/ds/tools/mfx/scripts/cctbx/fee_spec.sh "
                f"{runs} {facility}"
            ]
    else:
        logging.warning(f"Facility not found: {facility}")

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
        "--runs",
        "-r",
        dest="runs",
        default=None,
        help="Enter -r for List of run numbers. Last run number by default"
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
    runs = args.runs

    output(exp, runs, facility)


def run():
    """Entry point for console_scripts"""
    main(sys.argv[1:])


if __name__ == "__main__":
    run()