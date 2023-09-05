from mfx.db import mfx_dg1_slits as s1
from mfx.db import mfx_dg2_upstream_slits as s2
from mfx.db import mfx_dg2_midstream_slits as s3
from mfx.db import mfx_dg2_downstream_slits as s4

class User():
    def __init__(self):
        pass
    def mfxslits(self, width=1):
        s1.hg(width)
#        s1.vg(width)
#        s2.hg(width)
#        s2.vg(width)
#        s3.hg(width)
#        s3.vg(width)
#        s4.hg(width)
#        s4.vg(width)
