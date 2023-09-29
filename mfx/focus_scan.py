def focus_scan(camera, start=1, end=299, step=1):
    """
    Runs through transfocator Z to find the best focus

    Parameters
    ----------
    camera: str, required
        camera where you want to focus

    step: int, optional
	step size of transfocator movements

    start: int, optional
	starting transfocator position

    end: int, optional
	final transfocator position

    Examples:
    mfx dg1 yag is MFX:DG1:P6740
    mfx dg2 yag is MFX:DG2:P6740
    mfx dg3 yag is MFX:GIGE:02:IMAGE1

    Operations
    ----------

    """
    # cd /reg/g/pcds/pyps/apps/hutch-python/mfx/mfx
    # from mfx.transfocator_scan import *
    from mfx.transfocator_scan import *
    import numpy as np
    from mfx.db import tfs

    trf_align = transfocator_scan.transfocator_aligner(camera)
    trf_pos = np.arange(start, end, step)
    trf_align.scan_transfocator(tfs.translation,trf_pos,1)