"""
Event and listener-related DACP handlers: event listeners, context listeners,
intent listeners, broadcast operations.
"""

import logging
from typing import TYPE_CHECKING, Any

from fdc3.models.dacp.dacp import (
    AddEventListenerRequest,
    AddEventListenerResponse,
    AddEventListenerResponsePayload,
    RemoveEventListenerRequest,
    RemoveEventListenerResponse,
    RemoveEventListenerResponsePayload,
    BroadcastRequest,
    BroadcastEvent,
    BroadcastEventPayload,
    AgentEventMeta,
    AddContextListenerRequest,
    AddContextListenerResponse,
    AddContextListenerResponsePayload,
    AddIntentListenerRequest,
    AddIntentListenerResponse,
    AddIntentListenerResponsePayload,
    IntentListenerUnsubscribeRequest,
    IntentListenerUnsubscribeResponse,
    IntentListenerUnsubscribeResponsePayload,
    ContextListenerUnsubscribeRequest,
    ContextListenerUnsubscribeResponse,
    ContextListenerUnsubscribeResponsePayload,
    HeartbeatAcknowledgmentRequest,
)
from fdc3.models.dacp.enums import PrivateChannelEventListenerTypes
from fdc3.models.identifiers import AppIdentifier
from fdc3.models.primitives import ListenerUuid
from ...types import WcpSessions
from ..protocols import MessageSender
from .registry import dacp_handler, DACPError

if TYPE_CHECKING:
    from .base import DACPHandler
    from ...core import CoreServices

logger = logging.getLogger(__name__)


class EventHandlersMixin:
    """Mixin providing event and listener-related DACP handlers."""

    # These attributes are provided by DACPHandler
    _core: "CoreServices"
    connection_manager: Any
    bridge_client: Any

    @dacp_handler(AddEventListenerRequest, needs_session=True)
    async def _handle_add_event_listener(
        self: "DACPHandler",
        request: AddEventListenerRequest,
        *,
        session_id: str,
        wcp_sessions: WcpSessions,
        sender: MessageSender,
    ) -> None:
        instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        listener = self._core.listener_store.add_event_listener(
            ListenerUuid(), instance_uuid, request.payload.eventType
        )

        response = AddEventListenerResponse(
            type="addEventListenerResponse",
            payload=AddEventListenerResponsePayload(
                listenerUuid=listener.listener_uuid
            ),
            meta=self._meta_from_request(request),
        )
        await self._send_model(sender, response)

    @dacp_handler(RemoveEventListenerRequest, needs_session=False)
    async def _handle_remove_event_listener(
        self: "DACPHandler",
        request: RemoveEventListenerRequest,
        *,
        sender: MessageSender,
    ) -> None:
        listener = self._core.listener_store.remove_listener(
            request.payload.listenerUuid.root
        )

        channel_id = getattr(listener, "channel_id", None) if listener else None
        event_type = getattr(listener, "event_type", None) if listener else None
        if channel_id:
            channel = self._core.channel_manager.get_channel(channel_id)
            if channel is not None and getattr(channel, "type", None) == "private":
                source = getattr(request.meta, "source", None)
                if isinstance(source, AppIdentifier):
                    source_identity = source
                elif isinstance(source, dict):
                    source_identity = AppIdentifier(
                        appId=source.get("appId") or "fdc3-desktop-agent",
                        instanceId=source.get("instanceId"),
                        desktopAgent=None,
                    )
                else:
                    source_identity = AppIdentifier(
                        appId="fdc3-desktop-agent",
                        instanceId=None,
                        desktopAgent=None,
                    )

                resolved_event_type: PrivateChannelEventListenerTypes | None = None
                if isinstance(event_type, PrivateChannelEventListenerTypes):
                    resolved_event_type = event_type
                elif isinstance(event_type, str):
                    try:
                        resolved_event_type = PrivateChannelEventListenerTypes(
                            event_type
                        )
                    except ValueError:
                        resolved_event_type = None

                await self._bridge_private_channel_listener_update(
                    channel_id=channel_id,
                    event_type=resolved_event_type,
                    source_identity=source_identity,
                    added=False,
                )
        response = RemoveEventListenerResponse(
            type="removeEventListenerResponse",
            payload=RemoveEventListenerResponsePayload(),
            meta=self._meta_from_request(request),
        )
        await self._send_model(sender, response)

    @dacp_handler(BroadcastRequest, needs_session=True)
    async def _handle_broadcast(
        self: "DACPHandler",
        request: BroadcastRequest,
        *,
        session_id: str,
        wcp_sessions: WcpSessions,
        sender: MessageSender,
    ):
        """Handle broadcast request"""
        source_instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        normalized_context = self._normalize_context(request.payload.context)
        context_payload = normalized_context or request.payload.context

        # Use payload channelId if provided (e.g. from bridge), else current channel
        channel_id = request.payload.channelId
        if channel_id is None:
            current_channel = self._core.channel_manager.get_current_channel(
                source_instance_uuid
            )
            channel_id = current_channel.id if current_channel else None

        # Forward to Desktop Agent Bridge (best-effort). The bridge won't echo
        # back to this agent, so we still deliver locally.
        try:
            bridge = getattr(self, "bridge_client", None)
            if (
                bridge is not None
                and getattr(bridge, "is_connected", False)
                and session_id
            ):
                source_identity = self._get_session_identity(session_id, wcp_sessions)
                await bridge.send_request_no_wait(
                    request_type="broadcastRequest",
                    payload={"context": context_payload, "channelId": channel_id}
                    if channel_id
                    else {"context": context_payload},
                    source=AppIdentifier(
                        appId=source_identity.appId or "unknown",
                        instanceId=source_identity.instanceId,
                        desktopAgent=None,
                    ),
                )
        except Exception:
            # Best-effort: local broadcast must still succeed.
            pass

        targets = self._core.context_router.broadcast_context(
            context_payload,
            source_instance_uuid=source_instance_uuid,
            channel_id=channel_id,
        )

        event_payload = BroadcastEvent(
            type="broadcastEvent",
            payload=BroadcastEventPayload(context=context_payload),
            meta=AgentEventMeta(),
        ).model_dump_json()

        # Send broadcast event to targets
        for target_uuid in targets:
            try:
                await self.connection_manager.send_to_instance(
                    target_uuid, event_payload
                )
            except Exception:
                logger.exception(f"Failed to send broadcast to {target_uuid}")

    @dacp_handler(AddContextListenerRequest, needs_session=True)
    async def _handle_add_context_listener(
        self: "DACPHandler",
        request: AddContextListenerRequest,
        *,
        session_id: str,
        wcp_sessions: WcpSessions,
        sender: MessageSender,
    ):
        """Handle add context listener request"""
        source_instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)

        current_channel = self._core.channel_manager.get_current_channel(
            source_instance_uuid
        )
        requested_channel_id = request.payload.channelId
        target_channel_id: str | None = None

        if requested_channel_id:
            channel = self._core.channel_manager.get_channel(requested_channel_id)
            if channel is None:
                await self._send_error(
                    sender,
                    "addContextListenerResponse",
                    DACPError.NO_CHANNEL_FOUND,
                    request,
                )
                return
            if (
                current_channel is None
                or getattr(current_channel, "id", None) != requested_channel_id
            ):
                await self._send_error(
                    sender,
                    "addContextListenerResponse",
                    DACPError.CHANNEL_ACCESS_DENIED,
                    request,
                )
                return
            target_channel_id = requested_channel_id
        elif current_channel is not None:
            target_channel_id = current_channel.id

        listener = self._core.listener_store.add_context_listener(
            ListenerUuid(),
            source_instance_uuid,
            request.payload.contextType,
            channel_id=target_channel_id,
        )

        if current_channel and getattr(current_channel, "type", None) == "private":
            details: dict[str, Any] = {
                "listenerUuid": listener.listener_uuid.root,
                "instanceUuid": listener.instance_uuid,
            }
            if request.payload.contextType:
                details["contextType"] = request.payload.contextType

            await self._emit_private_channel_event(
                channel_id=current_channel.id,
                event_type=PrivateChannelEventListenerTypes.onAddContextListener,
                details=details,
            )

        if target_channel_id is not None:
            initial_context = self._core.channel_manager.get_channel_context(
                target_channel_id, request.payload.contextType
            )
            normalized = self._normalize_context(initial_context)
            if normalized is not None:
                event = BroadcastEvent(
                    type="broadcastEvent",
                    payload=BroadcastEventPayload(context=normalized),
                    meta=AgentEventMeta(),
                )
                await self.connection_manager.send_to_instance(
                    source_instance_uuid, event.model_dump_json()
                )

        response = AddContextListenerResponse(
            type="addContextListenerResponse",
            payload=AddContextListenerResponsePayload(
                listenerUuid=listener.listener_uuid
            ),
            meta=self._meta_from_request(request),
        )
        await self._send_model(sender, response)

    @dacp_handler(AddIntentListenerRequest, needs_session=True)
    async def _handle_add_intent_listener(
        self: "DACPHandler",
        request: AddIntentListenerRequest,
        *,
        session_id: str,
        wcp_sessions: WcpSessions,
        sender: MessageSender,
    ):
        """Handle add intent listener request"""
        source_instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)

        listener = self._core.listener_store.add_intent_listener(
            ListenerUuid(), source_instance_uuid, request.payload.intent
        )

        response = AddIntentListenerResponse(
            type="addIntentListenerResponse",
            payload=AddIntentListenerResponsePayload(
                listenerUuid=listener.listener_uuid
            ),
            meta=self._meta_from_request(request),
        )
        await self._send_model(sender, response)

    @dacp_handler(IntentListenerUnsubscribeRequest, needs_session=False)
    async def _handle_intent_listener_unsubscribe(
        self: "DACPHandler",
        request: IntentListenerUnsubscribeRequest,
        *,
        sender: MessageSender,
    ):
        """Handle intent listener unsubscribe"""
        self._core.listener_store.remove_listener(request.payload.listenerUuid.root)

        response = IntentListenerUnsubscribeResponse(
            type="intentListenerUnsubscribeResponse",
            payload=IntentListenerUnsubscribeResponsePayload(),
            meta=self._meta_from_request(request),
        )
        await self._send_model(sender, response)

    @dacp_handler(ContextListenerUnsubscribeRequest, needs_session=False)
    async def _handle_context_listener_unsubscribe(
        self: "DACPHandler",
        request: ContextListenerUnsubscribeRequest,
        *,
        sender: MessageSender,
    ):
        """Handle context listener unsubscribe"""
        listener = self._core.listener_store.remove_listener(
            request.payload.listenerUuid.root
        )

        if listener:
            instance_uuid = listener.instance_uuid
            channel = self._core.channel_manager.get_current_channel(instance_uuid)
            if channel and getattr(channel, "type", None) == "private":
                details: dict[str, Any] = {
                    "listenerUuid": request.payload.listenerUuid.root
                }
                context_type = getattr(listener, "context_type", None)
                if context_type:
                    details["contextType"] = context_type

                await self._emit_private_channel_event(
                    channel_id=channel.id,
                    event_type=PrivateChannelEventListenerTypes.onUnsubscribe,
                    details=details,
                )

        response = ContextListenerUnsubscribeResponse(
            type="contextListenerUnsubscribeResponse",
            payload=ContextListenerUnsubscribeResponsePayload(),
            meta=self._meta_from_request(request),
        )
        await self._send_model(sender, response)

    @dacp_handler(HeartbeatAcknowledgmentRequest, needs_session=False)
    async def _handle_heartbeat_acknowledgment(
        self: "DACPHandler",
        request: HeartbeatAcknowledgmentRequest,
        *,
        sender: MessageSender,
    ):
        """Handle heartbeat acknowledgment"""
        logger.debug(
            f"Received heartbeat acknowledgment for event {request.payload.heartbeatEventUuid}"
        )
