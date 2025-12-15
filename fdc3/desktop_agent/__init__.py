"""FDC3 Desktop Agent - A Python implementation of the FDC3 Desktop Agent.

This package provides a WebSocket-based FDC3 Desktop Agent that can be run
standalone or embedded in another Python application.

The package currently supports a compatibility shim: if a unified `fdc3`
package is installed that exposes `fdc3.desktop_agent`, this module will
emit a DeprecationWarning and re-export symbols from `fdc3.desktop_agent`.
Otherwise it falls back to the existing local module exports.
"""

import warnings

try:
    # Prefer new unified package layout when available.
    from fdc3.desktop_agent import (
        __version__,
        DesktopAgentConfig,
        create_app,
        app,
        Storage,
        AppMetadata,
        LaunchConfig,
        ProcessLauncher,
        LaunchResult,
        DistributedLogAdapter,
        IntentHandlerPlugin,
        IntentHandlerResult,
        PluginRegistry,
        discover_plugins,
        list_plugin_entry_points,
        PLUGIN_ENTRY_POINT_GROUP,
    )

    warnings.warn(
        "fdc3_desktop_agent is deprecated; import from fdc3.desktop_agent instead. "
        "This shim will be removed in a future release.",
        DeprecationWarning,
    )

    __all__ = [
        "__version__",
        "create_app",
        "app",
        "DesktopAgentConfig",
        "Storage",
        "AppMetadata",
        "LaunchConfig",
        "ProcessLauncher",
        "LaunchResult",
        "DistributedLogAdapter",
        "IntentHandlerPlugin",
        "IntentHandlerResult",
        "PluginRegistry",
        "discover_plugins",
        "list_plugin_entry_points",
        "PLUGIN_ENTRY_POINT_GROUP",
    ]

except Exception:
    # Fall back to the current internal implementation when the new layout is
    # not present yet.
    from .version import __version__

    from .config import DesktopAgentConfig
    from .server import create_app, app

    # Re-export key interfaces for custom implementations
    from .storage.interfaces import Storage, AppMetadata, LaunchConfig
    from .launcher.interfaces import ProcessLauncher, LaunchResult
    from .distributed.adapter import DistributedLogAdapter
    from .plugins import (
        IntentHandlerPlugin,
        IntentHandlerResult,
        PluginRegistry,
        discover_plugins,
        list_plugin_entry_points,
        PLUGIN_ENTRY_POINT_GROUP,
    )

    __all__ = [
        # Version
        "__version__",
        # Main API
        "create_app",
        "app",
        "DesktopAgentConfig",
        # Interfaces for custom implementations
        "Storage",
        "AppMetadata",
        "LaunchConfig",
        "ProcessLauncher",
        "LaunchResult",
        "DistributedLogAdapter",
        # Plugin API
        "IntentHandlerPlugin",
        "IntentHandlerResult",
        "PluginRegistry",
        "discover_plugins",
        "list_plugin_entry_points",
        "PLUGIN_ENTRY_POINT_GROUP",
    ]
