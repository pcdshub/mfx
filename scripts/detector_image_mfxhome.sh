#! /bin/bash

source /reg/g/psdm/etc/psconda.sh
experiment=`python /cds/home/d/djr/scripts/mfx/scripts/get_info.py --exp`
python /cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/detector_image.py -e $experiment
