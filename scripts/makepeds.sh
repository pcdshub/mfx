#! /bin/bash

run=$1
experiment=$2

ssh -Y psana /sdf/group/lcls/ds/tools/engineering_tools/engineering_tools/scripts/makepeds_psana --queue milano --run $run --experiment $experiment