"""FDC3 Desktop Agent - A Python implementation of the FDC3 Desktop Agent.

This package provides the desktop agent implementation and exports the
primary API surface used by applications embedding or extending the
agent (`fdc3.desktop_agent`).
"""

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
