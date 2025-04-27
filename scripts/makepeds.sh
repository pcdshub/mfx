#! /bin/bash

if [ $# -ne 4 ]; then
  echo "Usage error: $0 <daq number> <det nickname> <experiment> <run>"
  exit
fi

daq=$1
det=$2
exp=$3
run=$4

#============================#
function makepeds_jungfrau ()
{
echo making jungfrau
ssh -Y psana << EOF1
source /sdf/group/lcls/ds/ana/sw/conda2/manage/bin/psconda.sh
jungfrau_dark_proc -k exp=$exp,run=$run -d jungfrau -o ~/work
jungfrau_deploy_constants -k exp=$exp,run=$run -d jungfrau -o ~/work -D
EOF1
}

function makepeds_epix ()
{
echo making epix
ssh -Y psana << EOF2
source /sdf/group/lcls/ds/ana/sw/conda2/manage/bin/psconda.sh 
det_dark_proc -k "{'exp':'$exp','run':$run,'detectors':['epix100']}" -d epix100 -D
EOF2
}
#=============================#


case $daq in
  1)
    ssh -Y psana /sdf/group/lcls/ds/tools/engineering_tools/engineering_tools/scripts/makepeds_psana --queue milano --run $run --experiment $experiment
    ;;

  2)
    case $det in

    jungfrau)
        makepeds_jungfrau
        ;;

    epix)
        makepeds_epix
        ;;

    all)
        makepeds_jungfrau
	makepeds_epix
        ;;
    esac
    ;;
esac
