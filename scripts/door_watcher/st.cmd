#!/usr/bin/env bash
unset LD_LIBRARY_PATH
unset PYTHONPATH

export PCDS_CONDA_VER='1.2.6'
source /reg/g/pcds/pyps/conda/pcds_conda

cd "$(dirname "$0")"
python --version
python door_watcher.py
