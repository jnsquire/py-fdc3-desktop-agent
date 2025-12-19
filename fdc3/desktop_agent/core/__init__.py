# Orchestration and core services

from .app_registry import AppRegistry
from .listener_store import ListenerStore
from .channel_manager import ChannelManager
from .context_router import ContextRouter
from .intent_resolver import IntentResolver
from .external_registry import ExternalHandlerRegistry
from ..plugins import PluginRegistry, IntentHandlerPlugin
import asyncio
import logging
import threading
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


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
        # maps request_uuid -> (asyncio.Future, asyncio.AbstractEventLoop)
        self._pending_intents: Dict[
            str, Tuple[asyncio.Future, asyncio.AbstractEventLoop]
        ] = {}
        # Lock to protect _pending_intents for thread-safe access
        self._pending_intents_lock = threading.Lock()

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
        return self._register_pending_intent(request_uuid)

    def _register_pending_intent(self, request_uuid: str) -> asyncio.Future:
        """Create and register a pending intent future.

        If a future already exists for `request_uuid`, return it and log a warning.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as exc:
            # Creating futures without a running event loop is error-prone and
            # usually indicates the caller is not running inside an async
            # context. Require a running loop to avoid subtle bugs.
            raise RuntimeError(
                "create_pending_intent must be called from an async context with a running event loop"
            ) from exc

        with self._pending_intents_lock:
            existing = self._pending_intents.get(request_uuid)
            if existing:
                logger.warning("pending intent %s already registered", request_uuid)
                return existing[0]
            fut: asyncio.Future = loop.create_future()
            # store both future and its loop instead of relying on private attrs
            self._pending_intents[request_uuid] = (fut, loop)
            return fut

    def _clear_pending_intent(self, request_uuid: str) -> None:
        with self._pending_intents_lock:
            self._pending_intents.pop(request_uuid, None)

    def resolve_pending_intent(
        self, request_uuid: str, result: dict | None = None, error: str | None = None
    ) -> None:
        """Resolve a pending intent future with `result` or `error`.

        Logs a warning if the future is missing or already done.
        """
        with self._pending_intents_lock:
            entry = self._pending_intents.pop(request_uuid, None)

        if not entry:
            logger.warning("no pending intent %s when resolving response", request_uuid)
            return

        fut, fut_loop = entry

        if fut.done():
            logger.warning(
                "pending intent %s already done when resolving response", request_uuid
            )
            return

        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        # If the future's loop is different from the currently running loop,
        # schedule the resolution on the future's loop in a thread-safe way.
        if fut_loop is not None and fut_loop is not current_loop:
            if error is not None:
                fut_loop.call_soon_threadsafe(fut.set_exception, RuntimeError(error))
            else:
                fut_loop.call_soon_threadsafe(fut.set_result, result)
        else:
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
