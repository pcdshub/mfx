#! /bin/bash

exp=$1
run=$2
facility=$3
type=$4
group=$5

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
cd ${out}
dials.import max.cbf wavelength=1.105

case $type in

  mask)
    if [[ ! -d ${runpath} ]]; then
        echo ERROR: Run not averaged yet. Please stop and Average from the GUI
        exit 1 # terminate and indicate error
    fi

    if [ -z "${group}" ]; then
      # No arguments provided, open the newest file
      group=$(ls -t ${runpath} | head -n 1)
      echo "no trial-rungroup provided so using the newest"
    else
      # Arguments provided, use the first one as the file to open
      echo "path provided"
    fi
    cd ${mfx_dir}/common/results
    mkdir masks
    cd masks/
    dials.generate_mask ${out}/imported.expt border=1
    mv pixels.mask test.mask
    dials.image_viewer ${out}/avg.cbf mask=border.mask
    ;;

  geometry)
    if [[ ! -d ${runpath} ]]; then
        echo ERROR: Run not averaged yet. Please stop and Average from the GUI
        exit 1 # terminate and indicate error
    fi

    if [ -z "${group}" ]; then
      # No arguments provided, open the newest file
      group=$(ls -t ${runpath} | head -n 1)
      echo "no trial-rungroup provided so using the newest"
    else
      # Arguments provided, use the first one as the file to open
      echo "path provided"
    fi
    dials.image_viewer imported.expt
    ;;

  refinement0)
    mkdir -p ${mfx_dir}/common/geom/refine_${group:3}
    cd ${mfx_dir}/common/geom/refine_${group:3}
    dials.combine_experiments ${mfx_dir}/common/results/r0*/${group}/out/*refined*.expt ${mfx_dir}/common/results/r0*/${group}/out/*indexed*.refl reference_from_experiment.detector=0
    cctbx.xfel.detector_residuals combined.* hierarchy=1 tag=combined &
    ;;

  refinement1)
    dials.image_viewer imported.expt
    ;;

  refinement)
    dials.image_viewer imported.expt
    ;;
esac
