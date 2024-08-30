#! /bin/bash

user=$1
experiment=$2

source /sdf/group/lcls/ds/ana/sw/conda1/manage/bin/psconda.sh
python /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/cctbx_start.py -u $user -e $experiment