#!/usr/bin/bash
# Enter a minimal MFX optimize ipython session
# Set up your python environment before running this script
# At MFX, enter via "mfx3 optimize" to load the standard environment.

set -e
cd "$(dirname "$(realpath "${BASH_SOURCE[0]}")")"/../..
ipython -i mfx/optimize/interactive.py -- "$@"
