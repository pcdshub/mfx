#! /bin/bash

runs=$1
facility=$2

case $facility in

  S3DF)
    mfx_dir="/sdf/group/lcls/ds/tools/mfx"
    source /sdf/group/lcls/ds/tools/cctbx/setup.sh
    python /sdf/group/lcls/ds/tools/cctbx/energy/fee_spec.py ${runs}
    ;;

  NERSC)
    mfx_dir="/global/common/software/lcls/mfx"
    source /global/common/software/cctbx/alcc-recipes/cctbx/activate.sh
    python /global/homes/c/cctbx/energy/fee_spec.py ${runs}
    ;;
esac
