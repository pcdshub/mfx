"""
Type checking utilities for use in other submodules.

Keep this separate to avoid circular imports.
"""

import functools
from typing import Literal

from pydantic import ConfigDict, validate_call

Diagnostics = Literal["xcs1", "dg1", "dg2", "ip"]
Packages = Literal["xopt", "blop"]
Methods = Literal["turbo", "calib"]
Devices = Literal["yag", "wave8"]
Movers = Literal["mirr", "und"]
Turbo = Literal["safety", "optimize"]



def validate_w_lowercase_args(func):
    """
    Decorator to make string inputs lowercase, and then validate.

    Parameters:
    -----------
    func (Callable):
        The function to decorate.

    Returns:
    --------
    Callable:
        The decorated function with string arguments converted to lowercase.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Convert all string arguments to lowercase
        new_args = tuple(arg.lower() if isinstance(arg, str) else arg for arg in args)
        new_kwargs = {
            k: v.lower() if isinstance(v, str) else v for k, v in kwargs.items()
        }

        # Call the original function with the modified arguments, validated by Pydantic
        validated_func = validate_call(func, config=ConfigDict(validate_default=True))
        return validated_func(*new_args, **new_kwargs)

    return wrapper
