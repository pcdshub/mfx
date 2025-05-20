import sys
import os
import matplotlib.pyplot as plt 
plt.ion()

sys.path.append(os.getcwd())
from mfx.optimize.beam import Beam
b = Beam()
b.focus(0.0)
