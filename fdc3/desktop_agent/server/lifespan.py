# Lifespan management for the FDC3 Desktop Agent server

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncContextManager, Protocol, cast

from fastapi import FastAPI

from ..bridging import BridgeClient
from ..core import core_services, CoreServices
from ..distributed.adapter import DistributedLogAdapter
from ..distributed.factory import get_adapter
from . import lifespan_bridge as _lifespan_bridge
from . import lifespan_distributed as _lifespan_distributed
from .constants import SYSTEM_APP_METADATA


if TYPE_CHECKING:
    from ..config import DesktopAgentConfig
    from ..handlers import DACPHandler, WebSocketConnectionManager
    from ..launcher.interfaces import ProcessLauncher
    from ..storage.interfaces import Storage
    from .connection_manager import AgentClientConnectionManager


class AppState(Protocol):
    bridge_client: BridgeClient | None
    distributed_adapter: DistributedLogAdapter | None
    distributed_subscription_id: str | None
    storage: Storage
    launcher: ProcessLauncher
    core_services: CoreServices
    dacp_handler: DACPHandler
    agent_client_manager: AgentClientConnectionManager
    instance_connection_manager: WebSocketConnectionManager


logger = logging.getLogger(__name__)


async def _safe_await(label: str, awaitable) -> None:
    try:
        await awaitable
    except Exception:
        logger.exception("Error %s", label)


def _ensure_app_state(state: Any) -> AppState:
    defaults: dict[str, Any] = {
        "bridge_client": None,
        "distributed_adapter": None,
        "distributed_subscription_id": None,
        "storage": None,
        "launcher": None,
        "core_services": core_services,
        "dacp_handler": None,
        "agent_client_manager": None,
        "instance_connection_manager": None,
    }
    for name, value in defaults.items():
        if not hasattr(state, name):
            setattr(state, name, value)
    return cast(AppState, state)


async def _setup_bridge(
    *,
    config: DesktopAgentConfig,
    storage: Storage,
    launcher: ProcessLauncher,
    instance_connection_manager: WebSocketConnectionManager,
    dacp_handler: DACPHandler,
) -> BridgeClient | None:
    _lifespan_bridge.core_services = core_services
    _lifespan_bridge.BridgeClient = BridgeClient
    return await _lifespan_bridge._setup_bridge(
        config=config,
        storage=storage,
        launcher=launcher,
        instance_connection_manager=instance_connection_manager,
        dacp_handler=dacp_handler,
    )


async def _setup_distributed_adapter(
    config: DesktopAgentConfig,
) -> tuple[DistributedLogAdapter | None, str | None]:
    _lifespan_distributed.core_services = core_services
    _lifespan_distributed.get_adapter = get_adapter
    return await _lifespan_distributed._setup_distributed_adapter(config)


async def _register_plugins(config: DesktopAgentConfig) -> None:
    all_plugins = list(config.plugins)  # Copy to avoid modifying config
    if config.auto_discover_plugins:
        from ..plugins import discover_plugins

        discovered = discover_plugins()
        all_plugins.extend(discovered)

    for plugin in all_plugins:
        await core_services.register_plugin(plugin)
        logger.info("Registered plugin: %s", plugin.name)


def create_lifespan(
    config: DesktopAgentConfig,
    storage: Storage,
    launcher: ProcessLauncher,
    agent_client_manager: AgentClientConnectionManager,
    instance_connection_manager: WebSocketConnectionManager,
    dacp_handler: DACPHandler,
) -> Callable[[FastAPI], AsyncContextManager[None]]:
    """Create the lifespan context manager for the FastAPI app.

    Args:
        config: DesktopAgentConfig instance
        storage: Storage backend instance
        launcher: App launcher instance
        agent_client_manager: AgentClientConnectionManager instance
        instance_connection_manager: WebSocketConnectionManager instance
        dacp_handler: DACPHandler instance

    Returns:
        An async context manager function suitable for FastAPI's lifespan parameter.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Lifespan handler to initialize and teardown resources."""
        state = _ensure_app_state(app.state)

        # Startup
        logging.basicConfig(level=getattr(logging, config.log_level))

        await storage.initialize()
        logger.info(f"FDC3 Desktop Agent storage initialized at {config.db_path}")

        await storage.apps.add_app(SYSTEM_APP_METADATA)
        logger.info(f"Server configured for {config.host}:{config.port}")
        logger.info(f"Allowed origins: {', '.join(config.allowed_origins)}")

        # For display purposes, prefer localhost when the server is bound to 0.0.0.0
        display_host = "127.0.0.1" if config.host == "0.0.0.0" else config.host
        display_agent_url = config.computed_agent_url.replace(
            f"//{config.host}", f"//{display_host}", 1
        )

        logger.info(f"HTTP API available at: http://{display_host}:{config.port}")
        logger.info(f"GraphQL endpoint at: http://{display_host}:{config.port}/graphql")
        logger.info(f"WebSocket endpoint at: {display_agent_url}")
        logger.info(f"Admin interface at: http://{display_host}:{config.port}/admin")

        # Register intent handler plugins
        await _register_plugins(config)

        # Desktop Agent Bridging (experimental)
        state.bridge_client = await _setup_bridge(
            config=config,
            storage=storage,
            launcher=launcher,
            instance_connection_manager=instance_connection_manager,
            dacp_handler=dacp_handler,
        )

        # Initialize distributed adapter
        adapter, sub_id = await _setup_distributed_adapter(config)
        state.distributed_adapter = adapter
        state.distributed_subscription_id = sub_id

        # Store references for route handlers
        state.storage = storage
        state.launcher = launcher
        state.core_services = core_services
        # Expose the DACP handler so admin routes can programmatically raise
        # intents and deliver intent events to connected instances.
        state.dacp_handler = dacp_handler
        state.agent_client_manager = agent_client_manager
        state.instance_connection_manager = instance_connection_manager

        try:
            yield
        finally:
            # Shutdown
            if state.bridge_client is not None:
                await _safe_await("stopping bridge client", state.bridge_client.stop())

            adapter = state.distributed_adapter
            sub_id = state.distributed_subscription_id
            if adapter:
                if sub_id:
                    await _safe_await(
                        "unsubscribing distributed adapter",
                        adapter.unsubscribe(sub_id),
                    )
                await _safe_await("stopping distributed adapter", adapter.stop())

            await _safe_await("stopping launcher", launcher.stop())
            await _safe_await(
                "closing agent client manager", agent_client_manager.close_all()
            )
            await _safe_await(
                "closing instance connection manager",
                instance_connection_manager.close_all(),
            )

            # Unregister plugins
            for plugin in list(core_services.plugin_registry.list_plugins()):
                await _safe_await(
                    f"unregistering plugin {plugin.name}",
                    core_services.unregister_plugin(plugin),
                )

            await _safe_await("closing storage", storage.close())
            logger.info("FDC3 Desktop Agent storage closed")

    return lifespan
