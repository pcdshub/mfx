"""
Custom exception classes.

Keep this separate to avoid circular imports.
"""

class FeasibilityError(Exception):
    """
    A custom exception class to tell users when no Xopt sample points are feasible,
    e.g. due to the constraints being too tight.
    """
    pass
