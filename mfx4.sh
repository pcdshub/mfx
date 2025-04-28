#!/bin/bash
exp=$1
daq=$2

HERE="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"

# shellcheck disable=SC1091
source "${HERE}/mfxenv"

if [ -n "$exp" ] || [ $daq == 1 ]; then
    # Launch alt hutch-python with all devices and functions
    python /reg/g/pcds/pyps/apps/hutch-python/mfx/scripts/conf_edit.py -e $exp -d $daq
    hutch-python --cfg "${HERE}/alt_conf.yml" "$@"
else
    # Launch hutch-python with all devices and functions
    hutch-python --cfg "${HERE}/conf.yml" "$@"
fi