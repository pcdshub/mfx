#! /bin/bash

kill -9 `ps ux | grep detector_image.py | grep -v grep | awk '{ print $2 }'`
