"""Lightweight client library for external FDC3 intent handlers.

This is a minimal scaffold to connect to the desktop agent WCP endpoint,
register intent handlers, receive forwarded intents, and send results.

Note: This uses the `websockets` library for async WebSocket connections.
"""

from .client import FDC3Client

__all__ = ["FDC3Client"]
