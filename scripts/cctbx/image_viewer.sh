#! /bin/bash

experiment=$1
run=$2
facility=$3
type=$4
debug=$5

case $facility in

  S3DF)
    mfx_dir="/sdf/data/lcls/ds/mfx/${exp}/results"
    source /sdf/group/lcls/ds/tools/cctbx/setup.sh
    ;;

  NERSC)
    mfx_dir="/pscratch/sd/c/cctbx/${exp}"
    source /global/common/software/cctbx/alcc-recipes/cctbx/activate.sh
    ;;
esac

case $type in

  mask)
    cd ${mfx_dir}/common/results
    mkdir masks
    cd masks/
    dials.generate_mask ../geom/r24_agbe.expt border=1
    mv pixels.mask border.mask
    ;;

  geometry)
    cd ${mfx_dir}/common/results/averages/r0024/000/out
    dials.import max.cbf wavelength=1.105
    dials.image_viewer imported.expt
    ;;
esac