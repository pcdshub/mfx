#! /bin/bash

exp=$1
facility=$2
group=$3
level=$4

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

if [ -z "${level}" ] || [ "${group}" == "None" ]; then
    level="all"
fi

case $level in

  0)
    mkdir -p ${mfx_dir}/common/geom/refine_${group:3}
    cd ${mfx_dir}/common/geom/refine_${group:3}
    dials.combine_experiments ${mfx_dir}/common/results/r0*/${group}/out/*refined*.expt ${mfx_dir}/common/results/r0*/${group}/out/*indexed*.refl reference_from_experiment.detector=0
    cctbx.xfel.detector_residuals combined.* hierarchy=1 tag=combined

    cctbx.xfel.filter_experiments_by_rmsd combined.*
    dials.refine filtered.* ${mfx_dir}/common/geom/refine_level0.phil
    cctbx.xfel.detector_residuals refined_level0.* hierarchy=1 tag=refined
    echo
    echo "Your level 0 refinement file found Here:"
    echo ${mfx_dir}/common/geom/refine_${group:3}/refined_level0.expt
    ;;

  1)
    cd ${mfx_dir}/common/geom/refine_${group:3}
    dials.refine refined_level0.* ${mfx_dir}/common/geom/refine_level1.phil
    cctbx.xfel.detector_residuals refined_level1.* hierarchy=1 tag=refined
    dxtbx.plot_detector_models refined_level0.expt refined_level1.expt
    echo
    echo "Final refinement file found Here:"
    echo ${mfx_dir}/common/geom/refine_${group:3}/refined_level1.expt
    ;;

  all)
    mkdir -p ${mfx_dir}/common/geom/refine_${group:3}
    cd ${mfx_dir}/common/geom/refine_${group:3}
    dials.combine_experiments ${mfx_dir}/common/results/r0*/${group}/out/*refined*.expt ${mfx_dir}/common/results/r0*/${group}/out/*indexed*.refl reference_from_experiment.detector=0
    cctbx.xfel.detector_residuals combined.* hierarchy=1 tag=combined

    cctbx.xfel.filter_experiments_by_rmsd combined.*
    dials.refine filtered.* ${mfx_dir}/common/geom/refine_level0.phil
    cctbx.xfel.detector_residuals refined_level0.* hierarchy=1 tag=refined
    echo
    echo "Your level 0 refinement file found Here:"
    echo ${mfx_dir}/common/geom/refine_${group:3}/refined_level0.expt

    dials.refine refined_level0.* ${mfx_dir}/common/geom/refine_level1.phil
    cctbx.xfel.detector_residuals refined_level1.* hierarchy=1 tag=refined
    dxtbx.plot_detector_models refined_level0.expt refined_level1.expt
    echo
    echo "Final refinement file found Here:"
    echo ${mfx_dir}/common/geom/refine_${group:3}/refined_level1.expt
    ;;
esac

echo "Refinement done. Would you like to Deploy? (y/n) "
read yn

case $yn in 
    y) echo ok, we shall proceed;;
    n) echo exiting...;
    exit;;
    *) echo invalid response;
    exit 1;;
esac

mkdir ${mfx_dir}/common/geom/refine_${group:3}/split
cd ${mfx_dir}/common/geom/refine_${group:3}/split/
dials.split_experiments ${mfx_dir}/common/geom/refine_${group:3}/refined_level1.expt
newest_split=$(ls -t split*.expt | head -n 1)
mv ${newest_split} ${mfx_dir}/common/geom/refined_${group}.expt
rm -rf ${mfx_dir}/common/geom/refine_${group:3}/split/

echo
echo "Final refinement deployed Here:"
echo ${mfx_dir}/common/geom/refined_${group}.expt