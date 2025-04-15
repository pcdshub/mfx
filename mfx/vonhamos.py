from mfx.db import mfx_von_hamos_6crystal as vh

class SimpleDeterministicVH:
    """
    Simple wrapper for von Hamos spectrometer that provides deterministic movement capabilities.
    
    Examples:
    --------
    >>> vh = SimpleDeterministicVH()
    
    # Basic movement
    >>> vh.go('c1', 'rot', 45.0)  # Move crystal 1's rotation to 45 degrees
    
    # Movement with custom tolerance
    >>> vh.go('c4', 'x', 10.0, epsilon=0.001)  # Move crystal 4's x position with tighter tolerance
    
    # Movement with more retries
    >>> vh.go('c2', 'tilt', 30.0, n_iterations_max=20)  # Allow more attempts to reach target
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

    def go(self, c, axis, target, epsilon=0.001, n_iterations_max=10, wait=True):
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
        wait : bool, optional
            Whether to wait for motion to complete, by default True
        """
        motor = self.get_motor(c, axis)

        low_limit, high_limit = motor.limits

        if target < low_limit or target > high_limit:
            raise ValueError(f"Target {target} is out of limits {low_limit} to {high_limit}")
        
        iteration = 0
        while iteration < n_iterations_max:
            motor.clear_error()
            motor.move(target, wait=wait)
            current_pos = motor.user_readback.get()
            
            if abs(current_pos - target) <= epsilon:
                return
                
            iteration += 1
            
        print(
            f"Failed to reach target {target} within {n_iterations_max} iterations. "
            f"Final position: {current_pos}, target: {target}, "
            f"deviation: {abs(current_pos - target)}"
        )