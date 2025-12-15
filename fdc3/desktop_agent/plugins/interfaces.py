"""Plugin interfaces for extending FDC3 Desktop Agent.

This module provides the base classes and registry for implementing
custom intent handlers that run in-process with the desktop agent.

Example usage::

    from fdc3.desktop_agent.plugins import IntentHandlerPlugin, IntentHandlerResult

    class MyIntentPlugin(IntentHandlerPlugin):
        @property
        def handled_intents(self) -> list[str]:
            return ["myApp.customIntent"]

        async def handle_intent(
            self,
            intent: str,
            context: dict | None,
            source: dict | None,
        ) -> IntentHandlerResult:
            # Do something with the intent
            return IntentHandlerResult(handled=True, result={"status": "ok"})

    # Register via config
    config = DesktopAgentConfig(plugins=[MyIntentPlugin()])
    app = create_app(config)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class IntentHandlerResult:
    """Result returned by an intent handler plugin.

    Attributes:
        handled: True if the plugin handled the intent, False to fall through
                 to the next handler or normal resolution.
        result: Optional result data to return to the caller.
        error: Optional error message if the intent handling failed.
    """

    handled: bool = False
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class IntentHandlerPlugin(ABC):
    """Abstract base class for intent handler plugins.

    Implement this class to create custom intent handlers that run
    in-process with the desktop agent. Plugins are checked before
    the normal intent resolution flow.
    """

    @property
    @abstractmethod
    def handled_intents(self) -> List[str]:
        """List of intent names this plugin handles.

        Return a list of intent strings (e.g., ["myApp.doSomething"]).
        The plugin's handle_intent method will be called for any intent
        in this list.
        """
        pass

    @property
    def priority(self) -> int:
        """Priority for this plugin (higher = checked first).

        Override to change priority. Default is 0.
        When multiple plugins handle the same intent, higher priority
        plugins are checked first.
        """
        return 0

    @property
    def name(self) -> str:
        """Human-readable name for this plugin.

        Override to provide a custom name. Defaults to class name.
        """
        return self.__class__.__name__

    async def on_register(self, core_services: Any) -> None:
        """Called when the plugin is registered with the agent.

        Override to perform initialization that requires access to
        core services (app registry, listener store, etc.).

        Args:
            core_services: The CoreServices instance.
        """
        pass

    async def on_unregister(self) -> None:
        """Called when the plugin is unregistered.

        Override to perform cleanup.
        """
        pass

    @abstractmethod
    async def handle_intent(
        self,
        intent: str,
        context: Optional[Dict[str, Any]],
        source: Optional[Dict[str, Any]],
    ) -> IntentHandlerResult:
        """Handle an intent raised by an application.

        This method is called when an app raises an intent that matches
        one of this plugin's handled_intents.

        Args:
            intent: The intent name (e.g., "myApp.doSomething").
            context: Optional FDC3 context data passed with the intent.
            source: Optional source app identifier.

        Returns:
            IntentHandlerResult indicating whether the intent was handled
            and any result or error to return.
        """
        pass


class PluginRegistry:
    """Registry for intent handler plugins.

    Manages plugin registration and lookup for intent dispatch.
    """

    def __init__(self):
        self._plugins: List[IntentHandlerPlugin] = []
        self._intent_map: Dict[str, List[IntentHandlerPlugin]] = {}

    def register(self, plugin: IntentHandlerPlugin) -> None:
        """Register a plugin with the registry.

        Args:
            plugin: The plugin instance to register.
        """
        if plugin in self._plugins:
            logger.warning(f"Plugin {plugin.name} is already registered")
            return

        self._plugins.append(plugin)

        # Index by handled intents
        for intent in plugin.handled_intents:
            if intent not in self._intent_map:
                self._intent_map[intent] = []
            self._intent_map[intent].append(plugin)
            # Keep sorted by priority (descending)
            self._intent_map[intent].sort(key=lambda p: p.priority, reverse=True)

        logger.info(
            f"Registered plugin {plugin.name} for intents: {plugin.handled_intents}"
        )

    def unregister(self, plugin: IntentHandlerPlugin) -> None:
        """Unregister a plugin from the registry.

        Args:
            plugin: The plugin instance to unregister.
        """
        if plugin not in self._plugins:
            logger.warning(f"Plugin {plugin.name} is not registered")
            return

        self._plugins.remove(plugin)

        # Remove from intent map
        for intent in plugin.handled_intents:
            if intent in self._intent_map:
                self._intent_map[intent] = [
                    p for p in self._intent_map[intent] if p is not plugin
                ]
                if not self._intent_map[intent]:
                    del self._intent_map[intent]

        logger.info(f"Unregistered plugin {plugin.name}")

    def get_plugins_for_intent(self, intent: str) -> List[IntentHandlerPlugin]:
        """Get all plugins that handle a given intent.

        Args:
            intent: The intent name to look up.

        Returns:
            List of plugins sorted by priority (highest first).
            Empty list if no plugins handle this intent.
        """
        return self._intent_map.get(intent, [])

    def has_handler_for_intent(self, intent: str) -> bool:
        """Check if any plugin handles a given intent.

        Args:
            intent: The intent name to check.

        Returns:
            True if at least one plugin handles this intent.
        """
        return intent in self._intent_map and len(self._intent_map[intent]) > 0

    def list_plugins(self) -> List[IntentHandlerPlugin]:
        """List all registered plugins.

        Returns:
            List of all registered plugin instances.
        """
        return list(self._plugins)

    def list_handled_intents(self) -> List[str]:
        """List all intents that have registered handlers.

        Returns:
            List of intent names.
        """
        return list(self._intent_map.keys())
