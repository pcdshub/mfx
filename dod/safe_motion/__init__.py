"""
safe_motion — obstacle-avoiding motion layer for the MFX DoD robot.

Exports
-------
SafeRobot
    Subclass of DoD that intercepts all motion methods and, when
    ``safe_mode=True``, routes moves through a visibility-graph path
    planner before executing them.

Development location:
    DoD_dev/safe_motion/

Deployment location (copy here when stable):
    MFX_Hutch_Python/mfx/dod/safe_motion/
"""

from .safe_robot import SafeRobot

__all__ = ["SafeRobot"]
