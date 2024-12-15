#! /bin/bash
#SBATCH --nodes 1
#SBATCH --ntasks-per-node=128
#SBATCH --output=/pscratch/sd/c/cctbx/l10477/common/results/averages/test/log.out
#SBATCH --error=/pscratch/sd/c/cctbx/l10477/common/results/averages/test/err.out
#SBATCH --qos realtime
#SBATCH --time=00:45:00
#SBATCH --job-name=image_viewer
#SBATCH --account=lcls
#SBATCH --constraint=cpu
#SBATCH --time=120

exp=$1
facility=$2
run=$3

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

dirpath="${mfx_dir}/common/results/${run}"
runpath="${mfx_dir}/common/results/averages/${run}"

if [ -z "${group}" ] || [ "${group}" == "None" ]; then
  group=$(ls -t ${dirpath} | head -n 1)
  echo "no trial-rungroup provided so using the newest"
else
  echo "path provided"
fi

if [[ ! -d ${runpath} ]]; then
    ave_out="${runpath}/${group}/out"
    mkdir -p ${ave_out}
fi

srun dxtbx.image_average ${dirpath}/${group}/data.loc --mpi=True -v -a ${ave_out}/avg.cbf -m ${ave_out}/max.cbf -s ${ave_out}/std.cbf
