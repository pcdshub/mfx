#! /bin/bash

script_dir=$(dirname "$(realpath "$0")")
cd $script_dir

user=$1
experiment=$2
facility=$3

case $facility in

  S3DF)
    ssh -YAC psana /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/cctbx_step2.sh $user $experiment S3DF
    ;;

  NERSC)
    # /global/homes/c/cctbx/mfx.sh
    ./sshproxy -c cctbx -u $user
    ssh -i ~/.ssh/cctbx -YAC cctbx@perlmutter-p1.nersc.gov /global/homes/c/cctbx/mfx/scripts/cctbx/cctbx_step2.sh $user $experiment NERSC
    ;;
esac
