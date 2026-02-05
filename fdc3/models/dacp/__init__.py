"""DACP models package (relocated).

This package contains the Pydantic models for the Desktop Agent Control Protocol (DACP)
and external handler extensions.
"""

# Re-export all models from the main dacp module for backward compatibility
from .dacp import *  # noqa: F403
from .external_models import *  # noqa: F403
