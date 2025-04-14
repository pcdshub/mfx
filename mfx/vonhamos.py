from ophyd.device import Component as Cpt
from pcdsdevices.epics_motor import BeckhoffAxis
from pcdsdevices.interface import BaseInterface
from pcdsdevices.device import GroupDevice

class DeterministicBeckhoffAxis(BeckhoffAxis):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def go(self, target: float, epsilon: float = 0.0001, 
           n_iterations_max: int = 10, wait: bool = True) -> None:
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
        wait : bool, optional
            Whether to wait for motion to complete, by default True
        """
        iteration = 0
        while iteration < n_iterations_max:            
            self.clear_error()

            self.move(target, wait=wait)
            
            current_pos = self.user_readback.get()
            
            if abs(current_pos - target) <= epsilon:
                return
                
            iteration += 1
            
        print(
            f"Failed to reach target {target} within {n_iterations_max} iterations. "
            f"Final position: {self.user_readback.get()}, target: {target}, "
            f"deviation: {abs(self.user_readback.get() - target)}"
        )

    def go_with_overshoot(self, target: float, overshoot_factor: float = 0.1, 
                          wait: bool = True) -> None:
        """
        Move to target using a small overshoot to compensate for friction/backlash.

        Parameters
        ----------
        target : float
            Target position to move to.
        overshoot_factor : float, optional
            Extra distance to move beyond target, by default 0.001.
        wait : bool, optional
            Whether to wait for motion to complete, by default True.
        """
        current_pos = self.user_readback.get()
        direction = 1 if target > current_pos else -1
        overshoot_target = target + direction * overshoot_factor

        self.clear_error()
        self.move(overshoot_target, wait=wait)

        self.clear_error()
        self.move(target, wait=wait)

    def go_proportional(self, target: float, epsilon: float = 0.0001, 
                        factor: float = 1.2, n_iterations_max: int = 10, wait: bool = True) -> None:
        """
        Move to target using proportional correction steps.

        Parameters
        ----------
        target : float
            Target position to move to.
        epsilon : float, optional
            Maximum allowed deviation from target, by default 0.0001.
        factor : float, optional
            Multiplicative factor for correction step size (>1 to overcome friction), by default 1.2.
        n_iterations_max : int, optional
            Maximum number of iterations to attempt, by default 10.
        wait : bool, optional
            Whether to wait for motion to complete, by default True.
        """
        for _ in range(n_iterations_max):
            self.clear_error()
            current_pos = self.user_readback.get()
            error = target - current_pos

            if abs(error) <= epsilon:
                return
            # factor *= 0.9
            next_target = current_pos + factor * error
            self.move(next_target, wait=wait)

        print(
            f"Failed to reach target {target} after {n_iterations_max} iterations."
        )

    def go_smart(self, target: float, epsilon: float = 0.0001, stuck_epsilon: float = 0.01, 
                 n_iterations_max: int = 10, factor: float = 1.2, wait: bool = True) -> None:
        """
        Move to target using a smart strategy that detects stuck movement.

        If error reduction stalls, apply a forced overshoot.

        Parameters
        ----------
        target : float
            Target position to move to.
        epsilon : float, optional
            Maximum allowed deviation from target, by default 0.0001.
        n_iterations_max : int, optional
            Maximum number of iterations to attempt, by default 10.
        wait : bool, optional
            Whether to wait for motion to complete, by default True.
        """
        previous_error = None
        for _ in range(n_iterations_max):
            self.clear_error()
            current_pos = self.user_readback.get()
            error = target - current_pos

            if abs(error) <= epsilon:
                return

            overshoot = error
            # Detect stuck movement
            if previous_error is not None and abs(error - previous_error) <= stuck_epsilon :
                print("Detected stuck movement. Applying extra correction.")
                
                overshoot *= factor 

            next_target = current_pos + overshoot
            self.move(next_target, wait=wait)
            previous_error = error

        print(
            f"Failed to reach target {target} after {n_iterations_max} iterations."
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

