# Plugin system for extending FDC3 Desktop Agent with custom intent handlers

from .interfaces import IntentHandlerPlugin, PluginRegistry, IntentHandlerResult
from .discovery import (
    discover_plugins,
    list_plugin_entry_points,
    PLUGIN_ENTRY_POINT_GROUP,
)

__all__ = [
    "IntentHandlerPlugin",
    "PluginRegistry",
    "IntentHandlerResult",
    "discover_plugins",
    "list_plugin_entry_points",
    "PLUGIN_ENTRY_POINT_GROUP",
]
