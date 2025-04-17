from mfx.db import mfx_von_hamos_6crystal as vh

class SimpleDeterministicVH:
    """
    Simple wrapper for von Hamos spectrometer that provides deterministic movement capabilities.
    
    Examples:
    --------
    >>> vh = SimpleDeterministicVH()
    
    # Basic deterministic movement
    >>> vh.go('c1', 'rot', 45.0)  # Move crystal 1's rotation to 45 degrees
    
    # Smart movement with overshooting
    >>> vh.go('c1', 'rot', 45.0, smart=True)  # Will detect and handle stuck movement
    
    # Custom parameters
    >>> vh.go('c2', 'x', 10.0, epsilon=0.001, n_iterations_max=20)  # Tighter tolerance, more attempts
    >>> vh.go('c2', 'x', 10.0, smart=True, stuck_threshold=0.0005, overshoot_factor=1.5)  # Custom smart parameters
    """

    def __init__(self):
        self.vh = vh

    def get_motor(self, c, axis):
        """
        Get a specific motor.
        
        Parameters
        ----------
        c : str
            Crystal number (e.g. 'c1', 'c2', etc.)
        axis : str
            Axis name (e.g. 'x', 'rot', 'tilt')
            
        Returns
        -------
        motor : BeckhoffAxis
            The requested motor
        """
        return getattr(getattr(self.vh, c), axis)

    def go(self, c, axis, target, epsilon=0.001, n_iterations_max=10, 
           smart=False, stuck_threshold=0.001, overshoot_factor=1.2, wait=True):
        """
        Move a motor to target position with guaranteed accuracy.
        
        Parameters
        ----------
        c : str
            Crystal number (e.g. 'c1', 'c2', etc.)
        axis : str
            Axis name (e.g. 'x', 'rot', 'tilt')
        target : float
            Target position to move to
        epsilon : float, optional
            Maximum allowed deviation from target, by default 0.001
        n_iterations_max : int, optional
            Maximum number of iterations to attempt, by default 10
        smart : bool, optional
            Whether to use smart movement with overshooting, by default False
        stuck_threshold : float, optional
            Minimum position change to consider movement not stuck, by default 0.001
        overshoot_factor : float, optional
            Factor to multiply error by for overshoot (should be >1 to overshoot), by default 1.2
        wait : bool, optional
            Whether to wait for motion to complete, by default True
        """
        motor = self.get_motor(c, axis)
        low_limit, high_limit = motor.limits

        if target < low_limit or target > high_limit:
            raise ValueError(f"Target {target} is out of limits {low_limit} to {high_limit}")

        previous_pos = motor.user_readback.get()
        iteration = 0
        
        while iteration < n_iterations_max:
            motor.clear_error()
            current_pos = motor.user_readback.get()
            
            if abs(current_pos - target) <= epsilon:
                return
                
            if smart:
                position_change = abs(current_pos - previous_pos)
                
                if position_change < stuck_threshold:
                    print(f"Detected stuck movement at position {current_pos}. Applying overshoot.")
                    
                    error = target - current_pos
                    direction = 1 if error > 0 else -1
                    
                    overshoot_target = current_pos + direction * abs(error) * overshoot_factor
                    overshoot_target = max(min(overshoot_target, high_limit), low_limit)
                    
                    motor.clear_error()
                    motor.move(overshoot_target, wait=wait)
                    
                    motor.clear_error()
                    motor.move(target, wait=wait)
                else:
                    motor.move(target, wait=wait)
            else:
                motor.move(target, wait=wait)
            
            previous_pos = current_pos
            iteration += 1
            
        print(
            f"Failed to reach target {target} within {n_iterations_max} iterations. "
            f"Final position: {current_pos}, target: {target}, "
            f"deviation: {abs(current_pos - target)}"
        )