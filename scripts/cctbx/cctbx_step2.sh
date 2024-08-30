#! /bin/bash

option=$1

source /sdf/group/lcls/ds/tools/cctbx/setup.sh

if [[ "$option" == "notch" ]]
then
  echo Selected $option
  runlist=$2
  libtbx.python /sdf/group/lcls/ds/tools/cctbx/energy/fee_spec.py $runlist
fi

if [[ "$option" == "gui" ]]
then
  echo Selected $option
  cctbx.xfel
fi
