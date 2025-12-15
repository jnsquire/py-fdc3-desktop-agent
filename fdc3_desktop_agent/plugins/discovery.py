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

# Entry point group name for FDC3 Desktop Agent plugins
PLUGIN_ENTRY_POINT_GROUP = "fdc3_desktop_agent.plugins"


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

    # Use importlib.metadata (Python 3.9+)
    if sys.version_info >= (3, 10):
        from importlib.metadata import entry_points

        eps = entry_points(group=PLUGIN_ENTRY_POINT_GROUP)
    else:
        from importlib.metadata import entry_points

        all_eps = entry_points()
        eps = all_eps.get(PLUGIN_ENTRY_POINT_GROUP, [])

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
    if sys.version_info >= (3, 10):
        from importlib.metadata import entry_points

        eps = entry_points(group=PLUGIN_ENTRY_POINT_GROUP)
    else:
        from importlib.metadata import entry_points

        all_eps = entry_points()
        eps = all_eps.get(PLUGIN_ENTRY_POINT_GROUP, [])

    return [
        {
            "name": ep.name,
            "value": ep.value,
            "group": PLUGIN_ENTRY_POINT_GROUP,
        }
        for ep in eps
    ]
