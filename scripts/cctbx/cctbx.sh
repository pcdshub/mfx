#! /bin/bash

user=$1
experiment=$2
facility=$3
step=$4
debug=$5
phil=$6

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

case $step in

  1)
    python ${mfx_dir}/scripts/cctbx/cctbx_start.py -u $user -e $experiment -f $facility -d $debug
    ;;

  2)
    python ${mfx_dir}/scripts/cctbx/cctbx_start.py -u $user -e $experiment -f $facility -d $debug -p $phil
    cctbx.xfel
    ;;
esac