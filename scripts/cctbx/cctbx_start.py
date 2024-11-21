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

    logging.info("Starting up cctbx")

    if facility == "S3DF":
        preproc = None
        proc = [
            f"ssh -YAC psana "
            f"/sdf/group/lcls/ds/tools/mfx/scripts/cctbx/cctbx.sh "
            f"{user} {exp} {facility} 2"
        ]
    elif facility == "NERSC":
        preproc = [
            f"/sdf/group/lcls/ds/tools/mfx/scripts/cctbx/sshproxy -c cctbx -u {user}"
        ]
        proc = [
            f"ssh -i ~/.ssh/cctbx -YAC cctbx@perlmutter-p1.nersc.gov "
            f"/sdf/group/lcls/ds/tools/mfx/scripts/cctbx/cctbx.sh "
            f"{user} {exp} {facility} 2"
        ]

    if preproc is not None:
        logging.info(preproc)
        if debug:
            os.system(preproc[0])
        else:
            subprocess.Popen(
                preproc, shell=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    logging.info(proc)
    if debug:
        os.system(proc[0])
    else:
        subprocess.Popen(
            proc, shell=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def run():
    """Entry point for console_scripts"""
    main(sys.argv[1:])


if __name__ == "__main__":
    run()