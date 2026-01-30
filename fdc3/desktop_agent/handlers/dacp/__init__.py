"""
DACP (Desktop Agent Communication Protocol) handler.

This module handles FDC3 operations like app launching, context broadcasting,
and listener management. It is organized into submodules for maintainability:

- base: Core DACPHandler class and shared utilities
- registry: Handler registration decorator and error codes
- models: Pydantic validation models for DACP messages
"""

from .base import DACPHandler
from .registry import dacp_handler, DACPError

# Re-export commonly used types for backward compatibility
from fdc3.models.dacp.enums import PrivateChannelEventListenerTypes

__all__ = [
    "DACPHandler",
    "dacp_handler",
    "DACPError",
    "PrivateChannelEventListenerTypes",
]
