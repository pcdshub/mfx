#! /bin/bash

exp=$1
facility=$2
type=$3
group=$4
run=$5

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

runpath="${mfx_dir}/common/results/averages/${run}"

out="${runpath}/${group}/out"

if [[ ! -d ${runpath} ]]; then
    echo ERROR: Run not averaged yet. Please stop and Average from the GUI
    exit 1 # terminate and indicate error
fi

if [ -z "${group}" ] || [ "${group}" == "None" ]; then
  # No arguments provided, open the newest file
  group=$(ls -t ${runpath} | head -n 1)
  echo "no trial-rungroup provided so using the newest"
else
  # Arguments provided, use the first one as the file to open
  echo "path provided"
fi

case $type in

  mask)
    cd ${out}
    dials.import max.cbf wavelength=1.105
    cd ${mfx_dir}/common/results
    mkdir masks
    cd masks/
    dials.generate_mask ${out}/imported.expt border=1
    mv pixels.mask test.mask
    dials.image_viewer ${out}/avg.cbf mask=border.mask
    ;;

  geometry)
    cd ${out}
    dials.import max.cbf wavelength=1.105
    dials.image_viewer imported.expt
    ;;
esac
