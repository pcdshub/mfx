#! /bin/bash

user=$1
experiment=$2
facility=$3

case $facility in

  S3DF)
    mfx_dir="/sdf/group/lcls/ds/tools/mfx"
    source /sdf/group/lcls/ds/tools/cctbx/setup.sh
    ;;

  NERSC)
    mfx_dir="/global/common/software/lcls/mfx"
    source /global/common/software/cctbx/alcc-recipes/cctbx/activate.sh
    ;;
esac

python ${mfx_dir}/scripts/cctbx/phil_setup.py -u $user -e $experiment -f $facility
cctbx.xfel
