#!/usr/bin/bash
# Enter a minimal MFX optimize ipython session with simulated devices.
# Set up your python environment before running this script.

set -e
cd "$(dirname "$(realpath "${BASH_SOURCE[0]}")")"/../..
ipython -i mfx/optimize/interactive.py -- --sim "$@"
