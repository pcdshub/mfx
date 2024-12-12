#! /bin/bash

experiment=$1
run=$2
facility=$3
type=$4
debug=$5

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

case $type in

  mask)
    cd /pscratch/sd/c/cctbx/l10477/common/results
    mkdir masks
    cd masks/
    dials.generate_mask ../geom/r24_agbe.expt border=1
    mv pixels.mask border.mask
    ;;

  geometry)
    cd /pscratch/sd/c/cctbx/l10477/common/results/averages/r0024/000/out
    dials.import max.cbf wavelength=1.105
    dials.image_viewer imported.expt
    ;;
esac