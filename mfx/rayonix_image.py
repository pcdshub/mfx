# ssh daq-mfx-mon05
# source /reg/g/psdm/sw/conda1/manage/bin/psconda.sh -py3

from psana import *
import time
from psmon import publish
from psmon.plots import Image

#setOption('psana.calib-dir', '/reg/d/psdm/mfx/mfxlv0719/calib')
setOption('psana.calib-dir', '/sdf/data/lcls/ds/mfx/mfxl1010021/calib')
ds = DataSource('shmem=psana.0:stop=no')
det = Detector('Rayonix')

publish.local = True
publish.plot_opts.aspect = 1
img_arr=None
lastupdate = 0
for nevent, evt in enumerate(ds.events()):
    image = det.image(evt)
    if nevent==0:
        img_arr=image
    if nevent % 10 == 0:
        print ('event', nevent)
       
    if image is None:
        print ('*** no detector image')
        continue
    if time.time() - lastupdate >= 0.4:
        print ('update')
        img_arr=image#img_arr+image
        lastupdate = time.time()
        imgsend = Image(nevent, "Rayonix", img_arr)
        publish.send('image', imgsend)
