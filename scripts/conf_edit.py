# -*- coding: utf-8 -*-
"""
cctbx_start
"""
import argparse
import sys
import logging
import os
import subprocess
import requests
import yaml

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)


def is_valid_yaml(file_path):
    try:
        with open('/reg/g/pcds/pyps/apps/hutch-python/mfx/alt_conf_temp.yml', 'r') as file:
            yaml.safe_load(file)
        return True
    except yaml.YAMLError as e:
        logging.error(f"Error in YAML file: {e}")
        return False
    except FileNotFoundError:
        logging.error(f"Error: File not found: /reg/g/pcds/pyps/apps/hutch-python/mfx/alt_conf_temp.yml")
        return False


def update_yaml(exp):
    logging.info("Updating yaml file")
    with open("/reg/g/pcds/pyps/apps/hutch-python/mfx/alt_conf.yml") as istream:
        ymldoc = yaml.safe_load(istream)
        ymldoc['experiment'] = exp

    with open("/reg/g/pcds/pyps/apps/hutch-python/mfx/alt_conf_temp.yml", "w") as ostream:
        yaml.dump(ymldoc, ostream, default_flow_style=False, sort_keys=False)

    if is_valid_yaml('/reg/g/pcds/pyps/apps/hutch-python/mfx/alt_conf_temp.yml'):
        os.rename('/reg/g/pcds/pyps/apps/hutch-python/mfx/alt_conf_temp.yml', '/reg/g/pcds/pyps/apps/hutch-python/mfx/alt_conf.yml')


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

    if exp is None:
        ws_url = "https://pswww.slac.stanford.edu/ws/lgbk"
        resp = requests.get(
            ws_url + "/lgbk/ws/activeexperiment_for_instrument_station",
            {"instrument_name": 'mfx', "station": 0})
        exp_input = resp.json().get("value", {}).get("name")
    else:
        exp_input = exp

    if exp is not None:
        update_yaml(exp_input)

    else:
        logging.warning('No change requested to conf.yml')


def run():
    """Entry point for console_scripts"""
    main(sys.argv[1:])


if __name__ == "__main__":
    run()