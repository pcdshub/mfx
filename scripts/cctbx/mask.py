# -*- coding: utf-8 -*-
"""
cctbx_start
"""
import argparse
import sys
import logging

import dxtbx
from libtbx import easy_pickle

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)

def mask(exp, run, facility, group):
    logging.info("Making New Mask")

    if facility == "NERSC":
        mfx_dir=f"/pscratch/sd/c/cctbx/{exp}"
    elif facility == "S3DF":
        exp=f'mfx{exp}23'  #fix this
        mfx_dir=f"/sdf/data/lcls/ds/mfx/{exp}/results"
    else:
        logging.warning(f"Facility not found: {facility}")

    out_path=f"{mfx_dir}/common/results/averages/{run}/{group}/out"
    mask_path=f"{mfx_dir}/common/results/masks"

    img = dxtbx.load(f'{out_path}/std.cbf')
    mask = [m > 0 for m in img.get_raw_data()]
    easy_pickle.dump(f'{mask_path}/{run}stddev.mask', tuple(mask))


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
        "--run",
        "-r",
        dest="run",
        default=None,
        help="Enter -r for the run number",
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
    run = args.run
    group = args.group

    mask(exp, run, facility, group)


def run():
    """Entry point for console_scripts"""
    main(sys.argv[1:])


if __name__ == "__main__":
    run()
