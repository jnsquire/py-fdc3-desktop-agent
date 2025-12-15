"""Lightweight client library for external FDC3 intent handlers.

This is a minimal scaffold to connect to the desktop agent WCP endpoint,
register intent handlers, receive forwarded intents, and send results.

Note: This uses the `websockets` library for async WebSocket connections.
"""

import warnings

try:
    # Prefer new location if the unified `fdc3` package exists.
    from fdc3.client import FDC3Client  # type: ignore

    warnings.warn(
        "fdc3_client is deprecated; import from fdc3.client instead. "
        "This shim will be removed in a future release.",
        DeprecationWarning,
    )

    __all__ = ["FDC3Client"]

except Exception:
    # Fall back to the existing local implementation if the new package
    # layout isn't present yet.
    from .client import FDC3Client

__all__ = ["FDC3Client"]
