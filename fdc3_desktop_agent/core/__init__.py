# Orchestration and core services

from .app_registry import AppRegistry
from .listener_store import ListenerStore
from .channel_manager import ChannelManager
from .context_router import ContextRouter
from .intent_resolver import IntentResolver
from .external_registry import ExternalHandlerRegistry
from ..plugins import PluginRegistry, IntentHandlerPlugin
import asyncio
from typing import Dict


class CoreServices:
    """Central manager for all core services."""

    def __init__(self):
        self.app_registry = AppRegistry()
        self.listener_store = ListenerStore()
        self.channel_manager = ChannelManager()
        self.context_router = ContextRouter(
            self.listener_store, self.channel_manager, self.app_registry
        )
        self.intent_resolver = IntentResolver(self.listener_store, self.app_registry)
        self.plugin_registry = PluginRegistry()
        self.external_registry = ExternalHandlerRegistry()
        # pending intent requests forwarded to external handlers
        # maps request_uuid -> asyncio.Future
        self._pending_intents: Dict[str, asyncio.Future] = {}

    async def register_plugin(self, plugin: IntentHandlerPlugin) -> None:
        """Register an intent handler plugin.

        Args:
            plugin: The plugin instance to register.
        """
        self.plugin_registry.register(plugin)
        await plugin.on_register(self)

    async def register_external_handler(
        self,
        instance_uuid: str,
        handler_id: str,
        intents: list[str],
        priority: int = 0,
        metadata: dict | None = None,
    ) -> str:
        handler_uuid = self.external_registry.register(
            instance_uuid, handler_id, intents, priority, metadata
        )
        return handler_uuid

    async def unregister_external_handler(self, handler_uuid: str) -> None:
        self.external_registry.unregister(handler_uuid)

    def create_pending_intent(self, request_uuid: str) -> asyncio.Future:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending_intents[request_uuid] = fut
        return fut

    def resolve_pending_intent(
        self, request_uuid: str, result: dict | None = None, error: str | None = None
    ) -> None:
        fut = self._pending_intents.pop(request_uuid, None)
        if not fut:
            return
        if error is not None:
            fut.set_exception(RuntimeError(error))
        else:
            fut.set_result(result)

    async def unregister_plugin(self, plugin: IntentHandlerPlugin) -> None:
        """Unregister an intent handler plugin.

        Args:
            plugin: The plugin instance to unregister.
        """
        await plugin.on_unregister()
        self.plugin_registry.unregister(plugin)


# Global instance
core_services = CoreServices()
