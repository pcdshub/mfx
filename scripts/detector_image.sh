#! /bin/bash

experiment=$1
det=$2
calibdir=$3
ave=$4

source /reg/g/psdm/etc/psconda.sh
conda activate ana-4.0.51-py3
python /cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/detector_image.py -e $experiment -d $det -c $calibdir -a $ave &
