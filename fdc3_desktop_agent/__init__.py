"""Legacy package shim removed.

The legacy ``fdc3_desktop_agent`` top-level package shim has been removed
as part of the migration to the unified ``fdc3`` namespace. Import the
new module paths such as ``fdc3.desktop_agent`` instead.

This file intentionally raises ImportError to make the removal explicit.
"""

raise ImportError(
    "fdc3_desktop_agent shim removed; import from 'fdc3.desktop_agent' instead"
)
