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

def geom_refine(exp, facility, level, group):
    logging.info(f"Refining Geometry")
    if facility == "NERSC":
        exp = exp[3:-2]
        proc = [
                f"ssh -i ~/.ssh/cctbx -YAC cctbx@perlmutter-p1.nersc.gov "
                f"/global/common/software/lcls/mfx/scripts/cctbx/geom_refine.sh "
                f"{exp} {facility} {group} {level}"
            ]
    elif facility == "S3DF":
        proc = [
                f"ssh -YAC psana "
                f"/sdf/group/lcls/ds/tools/mfx/scripts/cctbx/geom_refine.sh "
                f"{exp} {facility} {group} {level}"
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
        "--level",
        "-l",
        dest="level",
        default=None,
        help="Enter -l for the level of geometry refinement",
    )
    parser.add_argument(
        "--group",
        "-g",
        dest="group",
        default=None,
        help="Enter -g for the trial "+
        "and rungroup number in the format 000_rg005."+
        "Default is newest folder"
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
    level = args.level
    group = args.group

    geom_refine(exp, facility, level, group)


def run():
    """Entry point for console_scripts"""
    main(sys.argv[1:])


if __name__ == "__main__":
    run()