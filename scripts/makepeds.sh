#! /bin/bash

daq=$1
det=$2
exp=$3
run=$4

case $daq in
  1)
    ssh -Y psana /sdf/group/lcls/ds/tools/engineering_tools/engineering_tools/scripts/makepeds_psana --queue milano --run $run --experiment $experiment
    ;;

  2)
    source /sdf/group/lcls/ds/ana/sw/conda2/manage/bin/psconda.sh

    case $det in

    jungfrau)
        echo making jungfrau
        ssh -Y psana jungfrau_dark_proc -k exp=$exp,run=$run -d jungfrau -o ~/work
        ssh -Y psana jungfrau_deploy_constants -k exp=$exp,run=$run -d jungfrau -o ~/work -D
        ;;

    epix)
        echo making epix
        ssh -Y psana det_dark_proc -k "{'exp':'$exp','run':$run,'dir':'/sdf/data/lcls/drpsrcf/ffb/mfx/$exp/xtc/','detectors':['epix100']}" -d epix100 -D
        ;;

    all)
        echo making jungfrau
        ssh -Y psana jungfrau_dark_proc -k exp=$exp,run=$run -d jungfrau -o ~/work
        ssh -Y psana jungfrau_deploy_constants -k exp=$exp,run=$run -d jungfrau -o ~/work -D
        ssh -Y psana det_dark_proc -k "{'exp':'$exp','run':$run,'dir':'/sdf/data/lcls/drpsrcf/ffb/mfx/$exp/xtc/','detectors':['epix100']}" -d epix100 -D
        ;;
    esac
    ;;
esac