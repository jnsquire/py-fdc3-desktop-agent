# Lifespan helpers for bridging and channel state

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Mapping, cast

from pydantic import ValidationError

from fdc3.models.dacp.dacp import (
    AgentEventMeta,
    BroadcastEvent,
    BroadcastEventPayload,
    Fdc3Context,
)

from ..api import DisplayMetadata
from ..bridging import BridgeClient
from ..bridging.settings import BridgeConnectionSettings
from ..bridging.types import (
    ChannelMember,
    ChannelsState,
    ChannelsStateFactory,
    ImplementationMetadata,
    ImplementationMetadataFactory,
)
from ..bridging.router import BridgeRequestRouter
from ..core import core_services
from ..version import __version__
from .models import ChannelContextItem, ChannelsStateModel

if TYPE_CHECKING:
    from ..config import DesktopAgentConfig
    from ..handlers import DACPHandler, WebSocketConnectionManager
    from ..launcher.interfaces import ProcessLauncher
    from ..storage.interfaces import Storage
    from ..handlers.dacp.base import BridgeClientProtocol

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

    def _implementation_metadata() -> ImplementationMetadata:
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

    return _implementation_metadata


def create_channels_state_factory(
    settings: BridgeConnectionSettings,
) -> ChannelsStateFactory:
    """Create the channels state factory for bridge handshake."""

    def _ensure_user_channels() -> list[Any]:
        channel_manager = core_services.channel_manager
        try:
            channels = list(channel_manager.list_channels())
        except Exception:
            channels = []

        existing_users = [
            channel for channel in channels if getattr(channel, "type", None) == "user"
        ]
        if not existing_users:
            for channel_id, name, color in DEFAULT_USER_CHANNELS:
                if channel_manager.get_channel(channel_id) is None:
                    channel_manager.create_channel(
                        channel_id,
                        "user",
                        display_metadata=DisplayMetadata(name=name, color=color),
                    )
            try:
                channels = list(channel_manager.list_channels())
            except Exception:
                channels = []

        return channels

    def _channels_state() -> ChannelsState:
        # Provide a best-effort snapshot of current channel membership for
        # the bridging handshake. We include `instanceUuid` (internal) and
        # enrich with `appId`/`instanceId` when known.
        state: ChannelsState = {}

        channel_manager = core_services.channel_manager
        app_registry = core_services.app_registry

        channels = _ensure_user_channels()
        for channel in channels:
            members: list[ChannelMember] = []
            for instance_uuid in channel_manager.get_channel_members(channel.id):
                instance_info = (
                    app_registry.get_instance(instance_uuid)
                    if app_registry is not None
                    else None
                )
                member: ChannelMember = {
                    "desktopAgent": settings.requested_name,
                    "instanceUuid": instance_uuid,
                }
                if instance_info is not None:
                    member.update(
                        {
                            "appId": instance_info.app_id,
                            "instanceId": instance_info.instance_id,
                            "instanceUuid": instance_info.instance_uuid,
                        }
                    )
                members.append(member)
            state[channel.id] = members

        return state

    return _channels_state


async def _apply_channels_state(
    channels_state: Mapping[str, list[ChannelContextItem]] | None,
    instance_connection_manager: WebSocketConnectionManager,
) -> None:
    if not channels_state:
        return

    channel_manager = core_services.channel_manager
    listener_store = core_services.listener_store

    for channel_id, incoming in channels_state.items():
        if not isinstance(incoming, list):
            continue

        # Expect incoming to be ChannelContextItem instances
        incoming_contexts: list[ChannelContextItem] = []
        for ctx in incoming:
            if isinstance(ctx, ChannelContextItem):
                incoming_contexts.append(ctx)
        if not incoming_contexts:
            continue

        # Extract processing into helper for clarity and smaller lock windows
        def _process_channel(
            channel_id: str, incoming_contexts: list[ChannelContextItem]
        ) -> list[tuple[str, Fdc3Context]]:
            # Initialize existing snapshot and membership
            with channel_manager._lock:
                existing = dict(channel_manager.channel_contexts.get(channel_id, {}))
                members = set(channel_manager.get_channel_members(channel_id))
                channel_known = (
                    channel_id in channel_manager.channels
                    or channel_id in channel_manager.channel_contexts
                )

                if not channel_known:
                    stored = channel_manager.channel_contexts.setdefault(channel_id, {})
                    for ctx in incoming_contexts:
                        ctx_dict = ctx.model_dump()
                        stored[ctx_dict["type"]] = ctx_dict
                    stored[channel_manager.LAST_CONTEXT_KEY] = incoming_contexts[
                        0
                    ].model_dump()
                    return []

            send_queue: list[tuple[str, Fdc3Context]] = []

            # Determine listeners to notify and update 'existing'
            for ctx in reversed(incoming_contexts):
                ctx_dict = ctx.model_dump()
                ctx_type = ctx.type
                existing_ctx = existing.get(ctx_type)
                if existing_ctx is None or existing_ctx != ctx_dict:
                    listeners = listener_store.get_context_listeners_for_type(
                        ctx_type, channel_id=channel_id, include_global=True
                    )
                    for listener in listeners:
                        if listener.context_type is None:
                            continue
                        if listener.instance_uuid not in members:
                            continue
                        send_queue.append(
                            (
                                listener.instance_uuid,
                                cast(Fdc3Context, ctx_dict),
                            )
                        )
                    existing[ctx_type] = ctx_dict

            most_recent = incoming_contexts[0].model_dump()
            existing_last = existing.get(channel_manager.LAST_CONTEXT_KEY)
            if existing_last != most_recent:
                for listener in listener_store.context_listeners.values():
                    if listener.context_type is not None:
                        continue
                    if listener.channel_id not in (None, channel_id):
                        continue
                    if listener.instance_uuid not in members:
                        continue
                    send_queue.append(
                        (listener.instance_uuid, cast(Fdc3Context, most_recent))
                    )
                existing[channel_manager.LAST_CONTEXT_KEY] = most_recent

            with channel_manager._lock:
                channel_manager.channel_contexts[channel_id] = existing

            return send_queue

        send_queue = _process_channel(channel_id, incoming_contexts)

        # Send deduplicated per-payload messages
        serialized_values: dict[str, str] = {}
        for instance_uuid, ctx in send_queue:
            payload = serialized_values.get(json.dumps(ctx, sort_keys=True))
            if payload is None:
                payload = BroadcastEvent(
                    type="broadcastEvent",
                    payload=BroadcastEventPayload(context=ctx),
                    meta=AgentEventMeta(),
                ).model_dump_json()
                serialized_values[json.dumps(ctx, sort_keys=True)] = payload
            await instance_connection_manager.send_to_instance(instance_uuid, payload)


async def _setup_bridge(
    *,
    config: DesktopAgentConfig,
    storage: Storage,
    launcher: ProcessLauncher,
    instance_connection_manager: WebSocketConnectionManager,
    dacp_handler: DACPHandler,
) -> BridgeClient | None:
    if not config.bridge_enabled:
        return None

    settings = BridgeConnectionSettings(config)

    router = BridgeRequestRouter(
        storage=storage,
        launcher=launcher,
        connection_manager=instance_connection_manager,
        core_services=core_services,
        dacp_handler=dacp_handler,
        local_desktop_agent_name=None,
    )

    async def _handle_connected_agents_update(payload: Any) -> None:
        add_agent = payload.addAgent
        if isinstance(add_agent, str) and add_agent:
            router.set_local_desktop_agent_name(add_agent)
        channels_state = getattr(payload, "channelsState", None)
        if channels_state:
            # Use Pydantic to validate the expected shape: dict[str, list[dict(type:str, ... )]]
            try:
                validated = ChannelsStateModel.model_validate(channels_state)
            except ValidationError:
                logger.warning(
                    "Ignoring malformed channelsState in connectedAgentsUpdate: %r",
                    channels_state,
                )
            else:
                await _apply_channels_state(validated.root, instance_connection_manager)

    bridge_client = BridgeClient(
        settings,
        implementation_metadata_factory=create_implementation_metadata_factory(
            settings
        ),
        channels_state_factory=create_channels_state_factory(settings),
        request_handler=router.handle,
        connected_agents_update_handler=_handle_connected_agents_update,
    )
    await bridge_client.start()
    dacp_handler.bridge_client = cast("BridgeClientProtocol", bridge_client)
    return bridge_client
