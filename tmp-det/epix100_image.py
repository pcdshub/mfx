# ssh daq-mfx-mon05
# source /reg/g/psdm/sw/conda1/manage/bin/psconda.sh -py3

from psana import *
import time
from psmon import publish
from psmon.plots import Image

#setOption('psana.calib-dir', '/reg/d/psdm/mfx/mfxlv0719/calib')
#setOption('psana.calib-dir', '/sdf/data/lcls/ds/mfx/mfxl1001521/calib')
setOption('psana.calib-dir', '/cds/home/opr/mfxopr/s3df-calib')
ds = DataSource('shmem=psana.0:stop=no')
det = Detector('ePix100_1')

publish.local = True
publish.plot_opts.aspect = 1
img_arr=None
lastupdate = 0

n_ave=30
i_ave=0

for nevent, evt in enumerate(ds.events()):
    img = det.image(evt)
    if img is None:
        print ('*** no detector image')
        continue
 
    if i_ave == 0:
        image = img
    else:
        image += img
    i_ave += 1
    if i_ave < n_ave:
        continue
    #if nevent==0:
    #    img_arr=image
    if nevent % 10 == 0:
        print ('event', nevent)
       
    if time.time() - lastupdate >= 0.4:
        print ('update')
        img_arr=image#img_arr+image
        lastupdate = time.time()
        imgsend = Image(nevent, "ePix100_1", img_arr)
        publish.send('image', imgsend)
        i_ave=0
