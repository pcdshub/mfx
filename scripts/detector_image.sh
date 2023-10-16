#! /bin/bash

experiment=$1
det=$2
calibdir=$3
ave=$4

source /reg/g/psdm/etc/psconda.sh
python /cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/detector_image.py -e $experiment -d $det -c $calibdir -a $ave &

#python /cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/detector_image.py -e mfxl1013621
