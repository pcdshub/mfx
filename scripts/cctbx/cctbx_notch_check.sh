#! /bin/bash

runlist="mfxl1027922:294 mfxl1027922:295 mfxl1027922:296 mfxl1027922:297 mfxl1027922:298"

ssh -YAC psana /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/cctbx_step2.sh notch $runlist