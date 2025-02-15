import psana
from matplotlib import pyplot as plt
import numpy as np
import sys

runs = []
for arg in sys.argv[1:]:
  try:
    runs.append(int(arg))
  except ValueError:
    exp = arg

good = 0
bad = 0
events = []
total = 0
data = None

maxes = []
for r in runs:
  ds = psana.DataSource('exp=%s:run=%d:smd'%(exp,r))
  d = psana.Detector('FEE-SPEC0')
  for run in ds.runs():
    for nevt, evt in enumerate(run.events()):
      f = d.get(evt)
      if f:
        good += 1
        events.append(1)
      else:
        bad += 1
        events.append(0)
        continue
      dta = f.hproj().astype(float)
      maxes.append(np.max(dta))
      #if np.max(dta) > 5e5: continue
      # ^If there are noisy spectometer shots (sawtooth pattern on spectrum) then
      # uncomment this line and set the threshold value based on the I(max) histogram.
      if data is None:
        data = dta
      else:
        data += dta
      total += 1
    print('run', r, 'max x pos', np.argmax(data), 'max value', np.max(data))
print(total)
data /= total
#data = data[:-2]
data /= np.max(data)
x = data 
# Uncomment the next line and add calibration numbers if you want to label the x-axis as energy.
# x = np.array(range(len(data))) * 0.07512 + 9625.1

from scipy.signal import savgol_filter
smoothed = savgol_filter(data, 51, 3) # window size 51, polynomial order 3

grad = np.gradient(smoothed)
grad = (grad-np.min(grad)) / (np.max(grad)-np.min(grad))

print(good, bad, good+bad)
plt.plot(x, data, '-')
plt.plot(x, smoothed, '-')
plt.plot(x, grad, '-')
plt.legend(["%d-%d"%(min(runs),max(runs)), "Smoothed", "Gradient"])
plt.title("FEE spec for %s runs"%exp)
plt.xlabel("Pixel")
#plt.xlabel("Energy (eV)")
plt.ylabel("Mean counts")
plt.show()

plt.plot(range(len(events)), events, '-')
plt.title("FEE presence over time")
plt.xlabel("Event number")
plt.ylabel("FEE present (1 yes, 0 no")
plt.show()

plt.hist(maxes, bins=100)
plt.show()
