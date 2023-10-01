# ssh daq-mfx-mon05
# source /reg/g/psdm/sw/conda1/manage/bin/psconda.sh -py3
import argparse
import logging
import time

from psana import *
from psmon import publish
from psmon.plots import Image

logging.basicConfig(filename='detector_image.log', level=logging.INFO)


parser = argparse.ArgumentParser()
parser.add_argument('-e', '--experiment', default='mfxl1001521', required=False,
                    help='Experiment name.')
parser.add_argument('-d', '--detname', default='Rayonix', required=False,
                    help='Detector name.')
parser.add_argument('-c', '--calibdir', default=None, required=False,
                    help='(optional) path to calib directory.')
parser.add_argument('-a', '--averaging', default=1, required=False,
                    help='Average over this number of events.')
args = parser.parse_args()


if args.calibdir is None:
    calibdir=f'/sdf/data/lcls/ds/mfx/{args.experiment}/calib'
else:
    calibdir=args.calibdir
setOption('psana.calib-dir', calibdir)
logging.info(f'calibration directory used: {calibdir}')

ds = DataSource('shmem=psana.0:stop=no')
det = Detector(args.detname)

publish.local = True
publish.plot_opts.aspect = 1
img_arr = None
lastupdate = 0

i_ave = 0

for nevent, evt in enumerate(ds.events()):
    img = det.image(evt)
    if img is None:
        logging.warning('*** no detector image')
        continue

    if i_ave == 0:
        image = img
    else:
        image += img
    i_ave += 1
    if i_ave < args.averaging:
        continue

    if nevent % 10 == 0:
        logging.info('event', nevent)

    if time.time() - lastupdate >= 0.4:
        logging.info('update')
        img_arr = image
        lastupdate = time.time()
        imgsend = Image(nevent, args.detname, img_arr)
        publish.send('image', imgsend)
        i_ave = 0