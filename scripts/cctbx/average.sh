#! /bin/bash
#SBATCH --nodes 1
#SBATCH --ntasks-per-node=120
#SBATCH --output=/sdf/data/lcls/ds/mfx/mfxl1033223/results/common/results/averages/r0758/006_rg031/stdout/log.out
#SBATCH --error=/sdf/data/lcls/ds/mfx/mfxl1033223/results/common/results/averages/r0758/006_rg031/stdout/err.out
#SBATCH --partition milano
#SBATCH --job-name=r756
#SBATCH --account=lcls:mfxl1033223 --reservation=lcls:onshift

exp=$1
facility=$2
run=$3
group=$4

case $facility in

  S3DF)
    mfx_dir="/sdf/data/lcls/ds/mfx/${exp}/results"
    source /sdf/group/lcls/ds/tools/cctbx/build/conda_setpaths.sh
    ;;

  NERSC)
    mfx_dir="/pscratch/sd/c/cctbx/${exp}"
    source /global/common/software/cctbx/alcc-recipes/cctbx/activate.sh
    ;;
esac

dirpath="${mfx_dir}/common/results/${run}"
runpath="${mfx_dir}/common/results/averages/${run}"

if [ -z "${group}" ] || [ "${group}" == "None" ]; then
  group=$(ls -t ${dirpath} | head -n 1)
  echo "no trial-rungroup provided so using the newest"
else
  echo "path provided"
fi

ave_out="${runpath}/${group}/out"

if [[ ! -d ${ave_out} ]]; then
    mkdir -p ${ave_out}
fi

mpirun dxtbx.image_average ${dirpath}/${group}/data.loc --mpi=True --skip-images=1 -v -a ${ave_out}/avg.cbf -m ${ave_out}/max.cbf -s ${ave_out}/std.cbf
