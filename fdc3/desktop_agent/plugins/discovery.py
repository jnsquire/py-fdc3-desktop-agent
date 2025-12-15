"""Plugin discovery via Python entry points.

This module provides functions to discover and load IntentHandlerPlugin
implementations from installed packages using Python's entry points mechanism.

External packages can register plugins by adding an entry point in their
pyproject.toml::

    [project.entry-points."fdc3_desktop_agent.plugins"]
    my-plugin = "my_package.plugins:MyIntentPlugin"

The entry point value should be a class that inherits from IntentHandlerPlugin.
The plugin will be instantiated (with no arguments) when loaded.
"""

from __future__ import annotations

import logging
import sys
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from .interfaces import IntentHandlerPlugin

logger = logging.getLogger(__name__)

# Entry point group name for FDC3 Desktop Agent plugins (legacy)
PLUGIN_ENTRY_POINT_GROUP = "fdc3_desktop_agent.plugins"
# New entry point group name for the unified `fdc3` package (recommended)
NEW_PLUGIN_ENTRY_POINT_GROUP = "fdc3.desktop_agent.plugins"


def discover_plugins() -> List["IntentHandlerPlugin"]:
    """Discover and instantiate plugins from installed packages.

    Scans all installed packages for entry points in the
    'fdc3_desktop_agent.plugins' group and instantiates each plugin class.

    Returns:
        List of instantiated IntentHandlerPlugin instances.

    Example:
        External packages register plugins in pyproject.toml::

            [project.entry-points."fdc3_desktop_agent.plugins"]
            my-handler = "my_package.plugins:MyIntentHandler"
            another-handler = "my_package.plugins:AnotherHandler"

        Then the agent discovers them at startup::

            plugins = discover_plugins()
            # Returns [MyIntentHandler(), AnotherHandler(), ...]
    """
    from .interfaces import IntentHandlerPlugin

    # Use importlib.metadata (Python 3.9+). Look for both legacy and new
    # entry point group names to support a gradual migration.
    groups = [PLUGIN_ENTRY_POINT_GROUP, NEW_PLUGIN_ENTRY_POINT_GROUP]

    eps = []
    if sys.version_info >= (3, 10):
        from importlib.metadata import entry_points

        for g in groups:
            try:
                eps.extend(entry_points(group=g))
            except Exception:
                # Some environments may raise if group is unknown; ignore
                continue
    else:
        from importlib.metadata import entry_points

        all_eps = entry_points()
        for g in groups:
            eps.extend(all_eps.get(g, []))

    plugins: List[IntentHandlerPlugin] = []

    for ep in eps:
        try:
            logger.debug(f"Loading plugin entry point: {ep.name} = {ep.value}")
            plugin_class = ep.load()

            # Validate that it's an IntentHandlerPlugin subclass
            if not isinstance(plugin_class, type):
                logger.warning(
                    f"Plugin entry point '{ep.name}' is not a class, skipping"
                )
                continue

            if not issubclass(plugin_class, IntentHandlerPlugin):
                logger.warning(
                    f"Plugin entry point '{ep.name}' ({plugin_class.__name__}) "
                    f"does not inherit from IntentHandlerPlugin, skipping"
                )
                continue

            # Instantiate the plugin
            plugin_instance = plugin_class()
            plugins.append(plugin_instance)
            logger.info(
                f"Discovered plugin '{ep.name}': {plugin_instance.name} "
                f"(handles: {plugin_instance.handled_intents})"
            )

        except Exception as e:
            logger.error(f"Failed to load plugin entry point '{ep.name}': {e}")
            continue

    if plugins:
        logger.info(
            f"Discovered {len(plugins)} plugin(s) from entry points: "
            f"{[p.name for p in plugins]}"
        )
    else:
        logger.debug("No plugins discovered from entry points")

    return plugins


def list_plugin_entry_points() -> List[dict]:
    """List all registered plugin entry points without loading them.

    Useful for debugging or displaying available plugins.

    Returns:
        List of dicts with 'name', 'value', and 'group' keys.
    """
    groups = [PLUGIN_ENTRY_POINT_GROUP, NEW_PLUGIN_ENTRY_POINT_GROUP]
    eps = []
    if sys.version_info >= (3, 10):
        from importlib.metadata import entry_points

        for g in groups:
            try:
                eps.extend(entry_points(group=g))
            except Exception:
                continue
    else:
        from importlib.metadata import entry_points

        all_eps = entry_points()
        for g in groups:
            eps.extend(all_eps.get(g, []))

    return [
        {
            "name": ep.name,
            "value": ep.value,
            "group": getattr(ep, "group", None) or PLUGIN_ENTRY_POINT_GROUP,
        }
        for ep in eps
    ]
