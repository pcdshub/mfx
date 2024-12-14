#! /bin/bash

exp=$1
facility=$2
type=$3
run=$4
group=$5

case $facility in

  S3DF)
    mfx_dir="/sdf/data/lcls/ds/mfx/${exp}/results"
    mfx3="/sdf/group/lcls/ds/tools/mfx"
    source /sdf/group/lcls/ds/tools/cctbx/setup.sh
    ;;

  NERSC)
    mfx_dir="/pscratch/sd/c/cctbx/${exp}"
    mfx3="/global/common/software/lcls/mfx"
    source /global/common/software/cctbx/alcc-recipes/cctbx/activate.sh
    ;;
esac

runpath="${mfx_dir}/common/results/averages/${run}"

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

out="${runpath}/${group}/out"

case $type in

  mask)
    cd ${out}
    dials.import ${out}/max.cbf wavelength=1.105
    mask_path="${mfx_dir}/common/masks"
    mkdir -p ${mask_path}

    echo "Would you like to make a new mask? (y/n) "
    read yn

    case $yn in 
      y)
        echo ok, we shall proceed with mask making
        echo ${mfx3}/scripts/cctbx/mask.py -e $exp -r $run -f $facility -g $group
        libtbx.python ${mfx3}/scripts/cctbx/mask.py -e $exp -r $run -f $facility -g $group
        dials.generate_mask ${out}/imported.expt border=1
        mv pixels.mask border.mask
        dials.generate_mask border.mask ${run}_stddev.mask
        newest_mask=${mask_path}/${run}_border_stddev.mask
        mv pixels.mask ${newest_mask}
        dials.image_viewer ${out}/avg.cbf mask=${newest_mask}
        ;;

      n)
        echo we will look at an image with the newest mask...
        newest_mask=$(ls -t ${mfx_dir}/common/masks/*.mask | head -n 1)
        dials.image_viewer ${out}/avg.cbf mask=${newest_mask}
        ;;

      *) echo invalid response;
        exit 1
        ;;
    esac
    ;;

  geometry)
    cd ${out}
    dials.import max.cbf wavelength=1.105
    dials.image_viewer imported.expt
    ;;
esac
