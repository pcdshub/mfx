from ophyd.device import Component as Cpt
from pcdsdevices.epics_motor import BeckhoffAxis
from pcdsdevices.interface import BaseInterface
from pcdsdevices.device import GroupDevice

class DeterministicBeckhoffAxis(BeckhoffAxis):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def go(self, target: float, epsilon: float = 0.001, n_iterations_max: int = 10,
           smart: bool = False, stuck_threshold: float = 0.001, overshoot_factor: float = 1.2,
           wait: bool = True) -> None:
        """
        Move to target position with guaranteed accuracy.
        
        Parameters
        ----------
        target : float
            Target position to move to
        epsilon : float, optional
            Maximum allowed deviation from target, by default 0.0001
        n_iterations_max : int, optional
            Maximum number of iterations to attempt, by default 10
        smart : bool, optional
            Whether to use smart movement with overshooting, by default False
        stuck_threshold : float, optional
            Minimum position change to consider movement not stuck, by default 0.01
        overshoot_factor : float, optional
            Factor to multiply error by for overshoot (should be >1 to overshoot), by default 1.2
        wait : bool, optional
            Whether to wait for motion to complete, by default True
        """
        iteration = 0
        previous_pos = self.user_readback.get()
        
        while iteration < n_iterations_max:
            self.clear_error()
            current_pos = self.user_readback.get()
            
            if abs(current_pos - target) <= epsilon:
                return
                
            if smart:
                position_change = abs(current_pos - previous_pos)
                
                if position_change < stuck_threshold:
                    print(f"Detected stuck movement at position {current_pos}. Applying overshoot.")
                    
                    error = target - current_pos
                    direction = 1 if error > 0 else -1
                    
                    overshoot_target = current_pos + direction * abs(error) * overshoot_factor
                    self.clear_error()
                    self.move(overshoot_target, wait=wait)
                    
                    self.clear_error()
                    self.move(target, wait=wait)
                else:
                    self.move(target, wait=wait)
            else:
                self.move(target, wait=wait)
            
            previous_pos = current_pos
            iteration += 1
            
        print(
            f"Failed to reach target {target} within {n_iterations_max} iterations. "
            f"Final position: {self.user_readback.get()}, target: {target}, "
            f"deviation: {abs(self.user_readback.get() - target)}"
        )

class DeterministicCrystal(BaseInterface, GroupDevice):
    """
    Wrapper for von Hamos crystal that adds deterministic movement capabilities.
    """

    tab_component_names = True

    x = Cpt(DeterministicBeckhoffAxis, ":X", kind="normal")
    rot = Cpt(DeterministicBeckhoffAxis, ":ROT", kind="normal")
    tilt = Cpt(DeterministicBeckhoffAxis, ":TILT", kind="normal")

class DeterministicVonHamos6Crystal(BaseInterface, GroupDevice):
    """
    Wrapper for von Hamos 6-crystal spectrometer that adds deterministic movement capabilities.
    """

    tab_component_names = True

    c1 = Cpt(DeterministicCrystal, ":C1", kind="normal")
    c2 = Cpt(DeterministicCrystal, ":C2", kind="normal")
    c3 = Cpt(DeterministicCrystal, ":C3", kind="normal")
    c4 = Cpt(DeterministicCrystal, ":C4", kind="normal")
    c5 = Cpt(DeterministicCrystal, ":C5", kind="normal")
    c6 = Cpt(DeterministicCrystal, ":C6", kind="normal") 

    rot = Cpt(BeckhoffAxis, ":ROT", kind="normal")
    y = Cpt(BeckhoffAxis, ":T1", kind="normal")
    x_bottom = Cpt(BeckhoffAxis, ":T2", kind="normal")
    x_top = Cpt(BeckhoffAxis, ":T3", kind="normal")
