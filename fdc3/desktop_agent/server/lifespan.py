# Lifespan management for the FDC3 Desktop Agent server

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncContextManager, Protocol, cast

from fastapi import FastAPI

from ..bridging import BridgeClient
from ..bridging.client import (
    BridgeConnectionSettings,
    RequestHandler,
    ImplementationMetadataFactory,
    ChannelsStateFactory,
    ChannelMember,
    ChannelsState,
)
from ..bridging.router import BridgeRequestRouter
from ..core import core_services, CoreServices
from ..distributed.factory import get_adapter
from ..distributed.adapter import DistributedLogAdapter
from ..api import DisplayMetadata
from ..tools import create_task_safe
from fdc3.models.dacp.dacp import (
    BroadcastEvent,
    BroadcastEventPayload,
    AgentEventMeta,
    Fdc3Context,
)
from ..version import __version__
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


logger = logging.getLogger(__name__)


DEFAULT_USER_CHANNELS: list[tuple[str, str, str]] = [
    ("user:red", "Red", "0xFF0000"),
    ("user:orange", "Orange", "0xFFA500"),
    ("user:yellow", "Yellow", "0xFFFF00"),
    ("user:green", "Green", "0x00FF00"),
    ("user:blue", "Blue", "0x0000FF"),
    ("user:purple", "Purple", "0x800080"),
]


def create_implementation_metadata_factory(
    settings: BridgeConnectionSettings,
) -> ImplementationMetadataFactory:
    """Create the implementation metadata factory for bridge handshake."""

    def _implementation_metadata() -> dict[str, Any]:
        # Minimal ImplementationMetadata for bridging handshake.
        # Keep optional features aligned with DACP getInfo reporting.
        # See FDC3 agent-bridging overview, BCP step 3.
        optional_features = {
            # We do not expose originating app metadata on context/intent payloads.
            "OriginatingAppMetadata": False,
            "UserChannelMembershipAPIs": True,
            "DesktopAgentBridging": True,
        }

        return {
            "fdc3Version": "2.2",
            "provider": "py-fdc3-desktop-agent",
            "providerVersion": __version__,
            "optionalFeatures": optional_features,
        }

    return cast(ImplementationMetadataFactory, _implementation_metadata)


def create_channels_state_factory(
    settings: BridgeConnectionSettings,
) -> ChannelsStateFactory:
    """Create the channels state factory for bridge handshake."""

    def _channels_state() -> ChannelsState:
        # Provide a best-effort snapshot of current channel membership for
        # the bridging handshake. We include `instanceUuid` (internal) and
        # enrich with `appId`/`instanceId` when known.
        state: ChannelsState = {}

        channel_manager = core_services.channel_manager
        app_registry = core_services.app_registry

        try:
            existing_users = [
                c
                for c in channel_manager.list_channels()
                if getattr(c, "type", None) == "user"
            ]
        except Exception:
            existing_users = []

        if not existing_users:
            for channel_id, name, color in DEFAULT_USER_CHANNELS:
                if channel_manager.get_channel(channel_id) is None:
                    channel_manager.create_channel(
                        channel_id,
                        "user",
                        display_metadata=DisplayMetadata(name=name, color=color),
                    )

        for channel in channel_manager.list_channels():
            members: list[ChannelMember] = []
            for instance_uuid in channel_manager.get_channel_members(channel.id):
                instance_info = (
                    app_registry.get_instance(instance_uuid)
                    if app_registry is not None
                    else None
                )
                if instance_info is not None:
                    members.append(
                        {
                            "desktopAgent": settings.requested_name,
                            "appId": instance_info.app_id,
                            "instanceId": instance_info.instance_id,
                            "instanceUuid": instance_info.instance_uuid,
                        }
                    )
                else:
                    members.append(
                        {
                            "desktopAgent": settings.requested_name,
                            "instanceUuid": instance_uuid,
                        }
                    )
            state[channel.id] = members

        return state

    return cast(ChannelsStateFactory, _channels_state)


async def _safe_await(label: str, awaitable) -> None:
    try:
        await awaitable
    except Exception:
        logger.exception("Error %s", label)


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
        state = cast(AppState, app.state)

        async def _apply_channels_state(channels_state: dict[str, list[dict]] | None):
            if not channels_state:
                return

            channel_manager = core_services.channel_manager
            listener_store = core_services.listener_store

            for channel_id, incoming in channels_state.items():
                if not isinstance(incoming, list):
                    continue

                incoming_contexts: list[Fdc3Context] = [
                    cast(Fdc3Context, ctx)
                    for ctx in incoming
                    if isinstance(ctx, dict) and ctx.get("type")
                ]
                if not incoming_contexts:
                    continue

                with channel_manager._lock:
                    existing = dict(
                        channel_manager.channel_contexts.get(channel_id, {})
                    )
                    members = set(channel_manager.get_channel_members(channel_id))
                    channel_known = (
                        channel_id in channel_manager.channels
                        or channel_id in channel_manager.channel_contexts
                    )

                if not channel_known:
                    with channel_manager._lock:
                        stored = channel_manager.channel_contexts.setdefault(
                            channel_id, {}
                        )
                        for ctx in incoming_contexts:
                            stored[ctx["type"]] = ctx
                        stored[channel_manager.LAST_CONTEXT_KEY] = incoming_contexts[0]
                    continue

                send_queue: list[tuple[str, Fdc3Context]] = []

                for ctx in reversed(incoming_contexts):
                    ctx_type = ctx["type"]
                    existing_ctx = existing.get(ctx_type)
                    if existing_ctx is None or existing_ctx != ctx:
                        listeners = listener_store.get_context_listeners_for_type(
                            ctx_type, channel_id=channel_id, include_global=True
                        )
                        for listener in listeners:
                            if listener.context_type is None:
                                continue
                            if listener.instance_uuid not in members:
                                continue
                            send_queue.append((listener.instance_uuid, ctx))
                        existing[ctx_type] = ctx

                most_recent = incoming_contexts[0]
                existing_last = existing.get(channel_manager.LAST_CONTEXT_KEY)
                if existing_last != most_recent:
                    for listener in listener_store.context_listeners.values():
                        if listener.context_type is not None:
                            continue
                        if listener.channel_id not in (None, channel_id):
                            continue
                        if listener.instance_uuid not in members:
                            continue
                        send_queue.append((listener.instance_uuid, most_recent))
                    existing[channel_manager.LAST_CONTEXT_KEY] = most_recent

                with channel_manager._lock:
                    channel_manager.channel_contexts[channel_id] = existing

                serialized: dict[int, str] = {}
                for instance_uuid, ctx in send_queue:
                    key = id(ctx)
                    payload = serialized.get(key)
                    if payload is None:
                        payload = BroadcastEvent(
                            type="broadcastEvent",
                            payload=BroadcastEventPayload(context=ctx),
                            meta=AgentEventMeta(),
                        ).model_dump_json()
                        serialized[key] = payload
                    await instance_connection_manager.send_to_instance(
                        instance_uuid, payload
                    )

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
        # First, discover plugins from entry points if enabled
        all_plugins = list(config.plugins)  # Copy to avoid modifying config
        if config.auto_discover_plugins:
            from ..plugins import discover_plugins

            discovered = discover_plugins()
            all_plugins.extend(discovered)

        for plugin in all_plugins:
            await core_services.register_plugin(plugin)
            logger.info(f"Registered plugin: {plugin.name}")

        # Desktop Agent Bridging (experimental)
        state.bridge_client = None
        if config.bridge_enabled:
            settings = BridgeConnectionSettings(
                host=config.bridge_host,
                port_start=config.bridge_port_start,
                port_end=config.bridge_port_end,
                requested_name=config.bridge_requested_name,
                retry_seconds=config.bridge_connect_retry_seconds,
                request_timeout_seconds=config.bridge_request_timeout_seconds,
            )

            router = BridgeRequestRouter(
                storage=storage,
                launcher=launcher,
                connection_manager=instance_connection_manager,
                core_services=core_services,
                local_desktop_agent_name=None,
            )

            async def _handle_connected_agents_update(payload):
                add_agent = payload.addAgent
                if isinstance(add_agent, str) and add_agent:
                    router.set_local_desktop_agent_name(add_agent)
                channels_state = getattr(payload, "channelsState", None)
                if channels_state:
                    await _apply_channels_state(dict(channels_state))

            bridge_client = BridgeClient(
                settings,
                implementation_metadata_factory=create_implementation_metadata_factory(
                    settings
                ),
                channels_state_factory=create_channels_state_factory(settings),
                request_handler=cast(RequestHandler, router.handle),
                connected_agents_update_handler=_handle_connected_agents_update,
            )
            await bridge_client.start()
            state.bridge_client = bridge_client

            # Inject into handler so outbound calls can be bridged.
            dacp_handler.bridge_client = bridge_client

        # Initialize distributed adapter
        adapter = config.distributed_adapter
        if adapter is None:
            try:
                adapter = get_adapter()
            except Exception:
                logger.exception("Error creating distributed adapter")
                adapter = None

        if adapter:
            try:
                await adapter.start()
                state.distributed_adapter = adapter

                async def _distributed_event_handler(ev):
                    try:
                        if isinstance(ev, str):
                            payload = json.loads(ev)
                        else:
                            payload = ev
                        core_services.channel_manager._emit_event(
                            payload.get("event_type"),
                            payload.get("channel_id"),
                            payload.get("instance_uuid"),
                            (
                                json.loads(payload.get("context"))
                                if payload.get("context")
                                else None
                            ),
                            remote=True,
                        )
                    except Exception:
                        logger.exception("Error handling distributed event")

                def _sub_cb(ev: dict):
                    # Fire-and-forget: schedule handler safely so exceptions
                    # are logged instead of being dropped.
                    create_task_safe(_distributed_event_handler(ev))

                sub_id = await adapter.subscribe("channel_events", _sub_cb)
                state.distributed_subscription_id = sub_id
            except Exception:
                logger.exception("Error starting distributed adapter")
                state.distributed_adapter = None
                state.distributed_subscription_id = None
        else:
            state.distributed_adapter = None
            state.distributed_subscription_id = None

        # Store references for route handlers
        state.storage = storage
        state.launcher = launcher
        state.core_services = core_services
        # Expose the DACP handler so admin routes can programmatically raise
        # intents and deliver intent events to connected instances.
        state.dacp_handler = dacp_handler

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
