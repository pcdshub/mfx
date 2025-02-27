#! /bin/bash

facility=$1
type=$2
exp=$3
run=$4
energy=$5
step=$6
num=$7

case $facility in

  S3DF)
    mfx_dir="/sdf/group/lcls/ds/tools/mfx"
    mfx3="/sdf/group/lcls/ds/tools/mfx"
    source /sdf/group/lcls/ds/tools/cctbx/setup.sh
    ;;

  NERSC)
    mfx_dir="/global/common/software/lcls/mfx"
    mfx3="/global/common/software/lcls/mfx"
    source /global/common/software/cctbx/alcc-recipes/cctbx/activate.sh
    ;;
esac

case $type in

  scan)
    libtbx.python ${mfx3}/scripts/cctbx/fee_summed.py ${exp} ${run}
    ;;

  series)
    libtbx.python ${mfx3}/scripts/cctbx/fee_calib.py exp=${exp} run_start=${run} energy_start=${energy} energy_step=${step} n_runs=${num}
    ;;
esac