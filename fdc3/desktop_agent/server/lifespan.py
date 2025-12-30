# Lifespan management for the FDC3 Desktop Agent server

import json
import logging
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI

from ..bridging import BridgeClient
from ..bridging.client import BridgeConnectionSettings, RequestHandlerProtocol
from ..bridging.router import BridgeRequestRouter
from ..core import core_services
from ..distributed.factory import get_adapter
from ..tools import create_task_safe
from ..version import __version__
from .constants import SYSTEM_APP_METADATA

logger = logging.getLogger(__name__)


def create_implementation_metadata_factory(settings: BridgeConnectionSettings):
    """Create the implementation metadata factory for bridge handshake."""

    def _implementation_metadata() -> dict:
        # Minimal ImplementationMetadata for bridging handshake.
        # Compute optional features based on available core services.
        # See FDC3 agent-bridging overview, BCP step 3.
        optional_features = {
            "OriginatingAppMetadata": hasattr(core_services, "app_registry")
            and getattr(core_services, "app_registry") is not None,
            "UserChannelMembershipAPIs": hasattr(core_services, "channel_manager")
            and getattr(core_services, "channel_manager") is not None,
            "DesktopAgentBridging": True,
        }

        return {
            "fdc3Version": "2.2",
            "provider": "py-fdc3-desktop-agent",
            "providerVersion": __version__,
            "optionalFeatures": optional_features,
        }

    return _implementation_metadata


def create_channels_state_factory(settings: BridgeConnectionSettings):
    """Create the channels state factory for bridge handshake."""

    def _channels_state() -> dict:
        # Provide a best-effort snapshot of current channel membership for
        # the bridging handshake. We include `instanceUuid` (internal) and
        # enrich with `appId`/`instanceId` when known.
        state: dict[str, list[dict]] = {}

        channel_manager = core_services.channel_manager
        app_registry = getattr(core_services, "app_registry", None)

        for channel in channel_manager.list_channels():
            members: list[dict] = []
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

    return _channels_state


def create_lifespan(
    config,
    storage,
    launcher,
    agent_client_manager,
    instance_connection_manager,
    dacp_handler,
):
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
    async def lifespan(app: FastAPI):
        """Lifespan handler to initialize and teardown resources."""
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
        app.state.bridge_client = None
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

            bridge_client = BridgeClient(
                settings,
                implementation_metadata_factory=create_implementation_metadata_factory(
                    settings
                ),
                channels_state_factory=create_channels_state_factory(settings),
                request_handler=cast(RequestHandlerProtocol, router.handle),
            )
            await bridge_client.start()
            app.state.bridge_client = bridge_client

            # Inject into handler so outbound calls can be bridged.
            dacp_handler.bridge_client = bridge_client

        # Initialize distributed adapter
        adapter = config.distributed_adapter
        sub_id = None
        if adapter is None:
            try:
                adapter = get_adapter()
            except Exception:
                adapter = None

        if adapter:
            try:
                await adapter.start()
                app.state.distributed_adapter = adapter

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
                app.state.distributed_subscription_id = sub_id
            except Exception:
                app.state.distributed_adapter = None
                app.state.distributed_subscription_id = None
        else:
            app.state.distributed_adapter = None
            app.state.distributed_subscription_id = None

        # Store references for route handlers
        app.state.storage = storage
        app.state.launcher = launcher
        app.state.core_services = core_services

        try:
            yield
        finally:
            # Shutdown
            try:
                bridge_client = getattr(app.state, "bridge_client", None)
                if bridge_client is not None:
                    await bridge_client.stop()
            except Exception:
                logger.exception("Error stopping bridge client")

            adapter = getattr(app.state, "distributed_adapter", None)
            sub_id = getattr(app.state, "distributed_subscription_id", None)
            if adapter:
                if sub_id:
                    try:
                        await adapter.unsubscribe(sub_id)
                    except Exception:
                        pass
                try:
                    await adapter.stop()
                except Exception:
                    pass

            try:
                await launcher.stop()
            except Exception:
                pass

            try:
                await agent_client_manager.close_all()
            except Exception:
                pass

            try:
                await instance_connection_manager.close_all()
            except Exception:
                pass

            # Unregister plugins
            for plugin in list(core_services.plugin_registry.list_plugins()):
                try:
                    await core_services.unregister_plugin(plugin)
                except Exception:
                    pass

            await storage.close()
            logger.info("FDC3 Desktop Agent storage closed")

    return lifespan
