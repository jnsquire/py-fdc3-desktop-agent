"""
DACP (Desktop Agent Communication Protocol) message handler.

This module is maintained for backward compatibility.
All implementation has been moved to the fdc3.desktop_agent.handlers.dacp package.

Please update imports to use:
    from fdc3.desktop_agent.handlers.dacp import DACPHandler, dacp_handler, DACPError
"""

# Re-export all public symbols from the new package for backward compatibility
from .dacp import DACPHandler, dacp_handler, DACPError

__all__ = [
    "DACPHandler",
    "dacp_handler",
    "DACPError",
]
