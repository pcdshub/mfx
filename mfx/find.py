# Class-based usage
from mfx.find import Find
find = Find()

# Get motor
motor = find.get_motor_by_pvname('MFX:DG1:MMS:01')
motor.mv(10.0)
print(f"Position: {motor.position}")

# Get signal
temp = find.get_signal_by_pvname('MFX:TEMP:01')
value = temp.get()
temp.put(300)

# Get simple motor
piezo = find.get_signal_motor_by_pvname('MFX:PIEZO:01')
piezo.move(5.0)

# Cache management
cached = find.list_cached_devices()
print(f"Cached motors: {cached['motors']}")
find.clear_caches()

# Convenience functions (recommended)
from mfx.find import get_motor, get_signal, get_simple_motor

# Quick motor access
motor = get_motor('MFX:DG1:MMS:01')
motor.mv(15.0)

# Quick signal access
temp = get_signal('MFX:TEMP:01')
current_temp = temp.get()

# Quick simple motor
piezo = get_simple_motor('MFX:PIEZO:01')
piezo.move(7.5)

# Search for devices
from mfx.find import search_motors, search_signals

# Find all DG1 motors
dg1_motors = search_motors('DG1')
for name, pv in dg1_motors:
    print(f"{name}: {pv}")

# Find temperature signals
temp_signals = search_signals('temp')
for name, pv in temp_signals:
    print(f"{name}: {pv}")

# Global instance
from mfx.find import find

motor = find.get_motor_by_pvname('MFX:DG1:MMS:01')
signal = find.get_signal_by_pvname('MFX:PRESSURE:01')

# Interactive exploration
from mfx.find import get_motor, search_motors

# Find motor
motors = search_motors('focus')
print(motors)

# Try first match
if motors:
    name, pv = motors[0]
    motor = get_motor(pv)
    print(f"Current position: {motor.position}")

# Scan integration
from mfx.find import get_simple_motor
from bluesky import RunEngine
import bluesky.plans as bp

RE = RunEngine()
motor = get_simple_motor('MFX:PIEZO:01')
motor.setpoint.kind = 'hinted'

# Use in scan
from mfx.db import daq
RE(bp.scan([daq], motor, 0, 10, 11))