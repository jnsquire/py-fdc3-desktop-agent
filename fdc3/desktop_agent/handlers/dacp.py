"""
DACP (Desktop Agent Communication Protocol) message handler.
Handles FDC3 operations like app launching, context broadcasting, and listener management.
"""

import logging
import uuid
import asyncio
from typing import Dict, Any

from fastapi import WebSocket

from fdc3.models.dacp.dacp import (
    AgentEventMeta,
    OpenRequest,
    AgentResponse,
    ErrorResponsePayload,
    AgentResponseMeta,
    OpenResponse,
    OpenResponsePayload,
    BroadcastRequest,
    BroadcastEvent,
    BroadcastEventPayload,
    AddContextListenerRequest,
    AddContextListenerResponse,
    AddContextListenerResponsePayload,
    AddIntentListenerRequest,
    AddIntentListenerResponse,
    AddIntentListenerResponsePayload,
    AddEventListenerRequest,
    AddEventListenerResponse,
    AddEventListenerResponsePayload,
    RemoveEventListenerRequest,
    RemoveEventListenerResponse,
    RemoveEventListenerResponsePayload,
    FDC3EventMessage,
    FDC3EventMessagePayload,
    GetInfoRequest,
    GetInfoResponse,
    GetInfoResponsePayload,
    GetAppMetadataRequest,
    GetAppMetadataResponse,
    GetAppMetadataResponsePayload,
    GetUserChannelsRequest,
    GetUserChannelsResponse,
    GetUserChannelsResponsePayload,
    GetCurrentChannelRequest,
    GetCurrentChannelResponse,
    GetCurrentChannelResponsePayload,
    GetCurrentContextRequest,
    GetCurrentContextResponse,
    GetCurrentContextResponsePayload,
    JoinUserChannelRequest,
    JoinUserChannelResponse,
    JoinUserChannelResponsePayload,
    LeaveCurrentChannelRequest,
    LeaveCurrentChannelResponse,
    LeaveCurrentChannelResponsePayload,
    CreatePrivateChannelRequest,
    CreatePrivateChannelResponse,
    CreatePrivateChannelResponsePayload,
    JoinPrivateChannelRequest,
    JoinPrivateChannelResponse,
    JoinPrivateChannelResponsePayload,
    LeavePrivateChannelRequest,
    LeavePrivateChannelResponse,
    LeavePrivateChannelResponsePayload,
    CreatePrivateChannelInvitationRequest,
    CreatePrivateChannelInvitationResponse,
    CreatePrivateChannelInvitationResponsePayload,
    PrivateChannelAddEventListenerRequest,
    PrivateChannelAddEventListenerResponse,
    PrivateChannelAddEventListenerResponsePayload,
    PrivateChannelEvent,
    PrivateChannelEventPayload,
    FindIntentRequest,
    FindIntentResponse,
    FindIntentResponsePayload,
    FindIntentsByContextRequest,
    FindIntentsByContextResponse,
    FindIntentsByContextResponsePayload,
    FindInstancesRequest,
    FindInstancesResponse,
    FindInstancesResponsePayload,
    RaiseIntentRequest,
    RaiseIntentResponse,
    RaiseIntentResponsePayload,
    RaiseIntentForContextRequest,
    RaiseIntentForContextResponse,
    RaiseIntentForContextResponsePayload,
    IntentEvent,
    IntentEventPayload,
    ContextListenerUnsubscribeRequest,
    ContextListenerUnsubscribeResponse,
    ContextListenerUnsubscribeResponsePayload,
    IntentListenerUnsubscribeRequest,
    IntentListenerUnsubscribeResponse,
    IntentListenerUnsubscribeResponsePayload,
    PrivateChannelDisconnectRequest,
    PrivateChannelDisconnectResponse,
    PrivateChannelDisconnectResponsePayload,
    HeartbeatAcknowledgmentRequest,
    IntentResultRequest,
    IntentResultResponse,
    IntentResultResponsePayload,
    RaiseIntentResultResponse,
)
from ..core import core_services
from fdc3.models.dacp.message_parser import parse_message, MessageParseError
from fdc3.models.dacp.external_models import (
    RegisterExternalHandlerRequest,
    RegisterExternalHandlerResponse,
    RegisterExternalHandlerResponsePayload,
    UnregisterExternalHandlerRequest,
    UnregisterExternalHandlerResponse,
    ExternalIntentResultRequest,
    ForwardedIntentMessage,
    ForwardedIntentPayload,
)
from ..storage import Storage
from ..launcher.interfaces import ProcessLauncher
from ..api import IntentResolution, DisplayMetadata
from fdc3.models.dacp.enums import PrivateChannelEventListenerTypes
from fdc3.models.identifiers import AppIdentifier
from fdc3.models.identifiers import IntentResolution as WireIntentResolution
from fdc3.models.identifiers import AppIntent, IntentMetadata, AppMetadata
from fdc3.models.identifiers import ImplementationMetadata
from fdc3.models.identifiers import (
    Channel as WireChannel,
    DisplayMetadata as WireDisplayMetadata,
)
from fdc3.models.identifiers import FDC3Event, FDC3EventType
from fdc3.models.primitives import RequestUuid, ListenerUuid
from .connection_manager import WebSocketConnectionManager
from .system_intent import SystemIntentHandler
from ..version import __version__

logger = logging.getLogger(__name__)


class DACPError:
    """Standardized DACP error codes."""

    APP_NOT_FOUND = "AppNotFound"
    APP_TIMEOUT = "AppTimeout"
    ERROR_ON_LAUNCH = "ErrorOnLaunch"
    INTERNAL_ERROR = "InternalError"
    NO_APPS_FOUND = "NoAppsFound"
    NO_CHANNEL_FOUND = "NoChannelFound"
    CHANNEL_CREATION_FAILED = "CreationFailed"
    CHANNEL_ACCESS_DENIED = "AccessDenied"
    RESOLVER_UNAVAILABLE = "ResolverUnavailable"
    TARGET_APP_UNAVAILABLE = "TargetAppUnavailable"
    TARGET_INSTANCE_UNAVAILABLE = "TargetInstanceUnavailable"


class DACPHandler:
    """Handles DACP (Desktop Agent Communication Protocol) messages"""

    DEFAULT_USER_CHANNELS: list[tuple[str, str, str]] = [
        ("user:red", "Red", "0xFF0000"),
        ("user:orange", "Orange", "0xFFA500"),
        ("user:yellow", "Yellow", "0xFFFF00"),
        ("user:green", "Green", "0x00FF00"),
        ("user:blue", "Blue", "0x0000FF"),
        ("user:purple", "Purple", "0x800080"),
    ]

    def __init__(
        self,
        storage: Storage,
        launcher: ProcessLauncher,
        connection_manager: WebSocketConnectionManager,
    ):
        self.storage = storage
        self.launcher = launcher
        self.connection_manager = connection_manager
        self.system_intent_handler = SystemIntentHandler()
        # Optional Desktop Agent Bridging client (set by server lifespan).
        self.bridge_client = None

    # Handler registry: maps request types to (handler_method_name, needs_session_context)
    # needs_session_context indicates if the handler requires session_id and wcp_sessions
    _HANDLERS: dict[type, tuple[str, bool]] = {}

    @classmethod
    def _init_handlers(cls) -> dict[type, tuple[str, bool]]:
        """Initialize handler registry. Called once at class definition time."""
        return {
            OpenRequest: ("_handle_open", True),
            BroadcastRequest: ("_handle_broadcast", True),
            AddContextListenerRequest: ("_handle_add_context_listener", True),
            AddIntentListenerRequest: ("_handle_add_intent_listener", True),
            IntentListenerUnsubscribeRequest: (
                "_handle_intent_listener_unsubscribe",
                False,
            ),
            GetInfoRequest: ("_handle_get_info", True),
            GetAppMetadataRequest: ("_handle_get_app_metadata", False),
            GetUserChannelsRequest: ("_handle_get_user_channels", False),
            GetCurrentChannelRequest: ("_handle_get_current_channel", True),
            GetCurrentContextRequest: ("_handle_get_current_context", True),
            JoinUserChannelRequest: ("_handle_join_user_channel", True),
            LeaveCurrentChannelRequest: ("_handle_leave_current_channel", True),
            JoinPrivateChannelRequest: ("_handle_join_private_channel", True),
            LeavePrivateChannelRequest: ("_handle_leave_private_channel", True),
            CreatePrivateChannelRequest: (
                "_handle_create_private_channel",
                True,
            ),
            CreatePrivateChannelInvitationRequest: (
                "_handle_create_private_channel_invitation",
                True,
            ),
            PrivateChannelAddEventListenerRequest: (
                "_handle_private_channel_add_event_listener",
                True,
            ),
            PrivateChannelDisconnectRequest: (
                "_handle_private_channel_disconnect",
                True,
            ),
            FindIntentRequest: ("_handle_find_intent", False),
            FindIntentsByContextRequest: ("_handle_find_intents_by_context", False),
            FindInstancesRequest: ("_handle_find_instances", False),
            RegisterExternalHandlerRequest: ("_handle_register_external_handler", True),
            UnregisterExternalHandlerRequest: (
                "_handle_unregister_external_handler",
                True,
            ),
            ExternalIntentResultRequest: ("_handle_external_intent_result", False),
            RaiseIntentRequest: ("_handle_raise_intent", True),
            RaiseIntentForContextRequest: ("_handle_raise_intent_for_context", False),
            IntentResultRequest: ("_handle_intent_result_request", False),
            RaiseIntentResultResponse: ("_handle_raise_intent_result_response", False),
            ContextListenerUnsubscribeRequest: (
                "_handle_context_listener_unsubscribe",
                False,
            ),
            AddEventListenerRequest: ("_handle_add_event_listener", True),
            RemoveEventListenerRequest: ("_handle_remove_event_listener", False),
            HeartbeatAcknowledgmentRequest: ("_handle_heartbeat_acknowledgment", False),
        }

    @staticmethod
    def _meta_from_request(request: Any) -> AgentResponseMeta:
        return AgentResponseMeta(requestUuid=request.meta.requestUuid)

    def _get_instance_uuid(self, session_id: str, wcp_sessions: Dict[str, Any]) -> str:
        """Extract instance UUID from session context."""
        return wcp_sessions[session_id]["identity"]["instanceUuid"]

    def _get_session_identity(
        self, session_id: str | None, wcp_sessions: Dict[str, Any] | None
    ) -> Dict[str, Any]:
        """Extract identity dict from session context."""
        if session_id is None or wcp_sessions is None:
            return {}
        return (wcp_sessions.get(session_id) or {}).get("identity") or {}

    def _get_source_app_identifier(
        self, session_id: str | None, wcp_sessions: Dict[str, Any] | None
    ) -> AppIdentifier:
        """Build AppIdentifier from session context."""
        identity = self._get_session_identity(session_id, wcp_sessions)
        return AppIdentifier(
            appId=identity.get("appId") or "unknown",
            instanceId=identity.get("instanceId"),
            desktopAgent=None,
        )

    async def _send_error(
        self,
        websocket: WebSocket,
        response_type: str,
        error: str,
        request: Any,
    ) -> None:
        """Send a standardized error response."""
        response = AgentResponse(
            type=response_type,
            payload=ErrorResponsePayload(error=error),
            meta=self._meta_from_request(request),
        )
        await self._send_model(websocket, response)

    async def _send_model(self, websocket: WebSocket, model) -> None:
        """Helper method to send a Pydantic model as JSON over WebSocket"""
        try:
            await websocket.send_text(model.model_dump_json())
        except Exception as e:
            logger.error(f"Failed to send model {model.__class__.__name__}: {e}")

    async def handle_message(
        self,
        message: Dict[str, Any],
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ):
        """Handle DACP message with centralized Pydantic validation."""
        msg_type = message.get("type")

        # Parse and validate message using Pydantic
        try:
            parsed = parse_message(message)
        except MessageParseError as e:
            logger.warning(f"Failed to parse DACP message: {e}")
            # Send error response if we can determine the response type
            response_type = f"{msg_type}Response" if msg_type else "errorResponse"
            err = AgentResponse(
                type=response_type,
                payload=ErrorResponsePayload(error=str(e)),
                meta=AgentResponseMeta(
                    requestUuid=(
                        RequestUuid(root=e.request_uuid)
                        if e.request_uuid
                        else RequestUuid()
                    )
                ),
            )
            await self._send_model(websocket, err)
            return

        # Dispatch to typed handlers using registry
        handler_info = self._HANDLERS.get(type(parsed))
        if handler_info is None:
            logger.warning(f"Unknown DACP message type: {msg_type}")
            return

        handler_name, needs_session = handler_info
        handler = getattr(self, handler_name)

        if needs_session:
            await handler(
                parsed,
                session_id=session_id,
                wcp_sessions=wcp_sessions,
                websocket=websocket,
            )
        else:
            await handler(parsed, websocket=websocket)

    async def _emit_user_channel_changed_event(
        self, *, instance_uuid: str, current_channel_id: str | None
    ) -> None:
        listeners = core_services.listener_store.get_event_listeners(
            FDC3EventType.USER_CHANNEL_CHANGED.value, instance_uuid=instance_uuid
        )
        if not listeners:
            return

        event = FDC3EventMessage(
            type="fdc3Event",
            payload=FDC3EventMessagePayload(
                event=FDC3Event(
                    type=FDC3EventType.USER_CHANNEL_CHANGED,
                    details={"currentChannelId": current_channel_id},
                )
            ),
            meta=AgentEventMeta(),
        )

        try:
            await self.connection_manager.send_to_instance(
                instance_uuid, event.model_dump_json()
            )
        except Exception:
            logger.debug(
                "Failed to send USER_CHANNEL_CHANGED event to instance %s",
                instance_uuid,
                exc_info=True,
            )

    async def _emit_private_channel_event(
        self,
        *,
        channel_id: str,
        event_type: PrivateChannelEventListenerTypes,
        details: dict[str, Any] | None = None,
    ) -> None:
        listeners = core_services.listener_store.get_event_listeners(
            event_type.value,
            channel_id=channel_id,
        )
        if not listeners:
            return

        event = PrivateChannelEvent(
            type="privateChannelEvent",
            payload=PrivateChannelEventPayload(
                channelId=channel_id,
                eventType=event_type,
                details=details,
            ),
            meta=AgentEventMeta(),
        )
        payload = event.model_dump_json()

        for listener in listeners:
            try:
                await self.connection_manager.send_to_instance(
                    listener.instance_uuid, payload
                )
            except Exception:
                logger.debug(
                    "Failed to send private channel event %s to %s",
                    event_type.value,
                    listener.instance_uuid,
                    exc_info=True,
                )

    async def _handle_private_channel_add_event_listener(
        self,
        request: PrivateChannelAddEventListenerRequest,
        *,
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ) -> None:
        instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        channel_id = request.payload.channelId
        channel = core_services.channel_manager.get_channel(channel_id)

        if channel is None or getattr(channel, "type", None) != "private":
            await self._send_error(
                websocket,
                "privateChannelAddEventListenerResponse",
                DACPError.NO_CHANNEL_FOUND,
                request,
            )
            return

        owner = core_services.channel_manager.get_private_channel_owner(channel_id)
        if instance_uuid != owner:
            await self._send_error(
                websocket,
                "privateChannelAddEventListenerResponse",
                DACPError.CHANNEL_ACCESS_DENIED,
                request,
            )
            return

        listener = core_services.listener_store.add_event_listener(
            ListenerUuid(),
            instance_uuid,
            request.payload.eventType.value if request.payload.eventType else None,
            channel_id=channel_id,
        )

        response = PrivateChannelAddEventListenerResponse(
            type="privateChannelAddEventListenerResponse",
            payload=PrivateChannelAddEventListenerResponsePayload(
                listenerUuid=listener.listener_uuid
            ),
            meta=self._meta_from_request(request),
        )
        await self._send_model(websocket, response)

    async def _handle_get_info(
        self,
        request: GetInfoRequest,
        *,
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ) -> None:
        identity = self._get_session_identity(session_id, wcp_sessions)
        app_id = identity.get("appId") or "unknown"
        instance_id = identity.get("instanceId")

        # Best-effort: enrich app metadata from storage if available.
        name = None
        version = None
        description = None
        icons = None
        if app_id and app_id != "unknown":
            try:
                meta = await self.storage.apps.get_app_metadata(app_id)
            except Exception:
                logger.debug(
                    "getInfo: failed to load app metadata from storage", exc_info=True
                )
                meta = None

            if meta is not None:
                name = getattr(meta, "name", None)
                version = getattr(meta, "version", None)
                description = getattr(meta, "description", None)
                icons = getattr(meta, "icons", None)

        impl = ImplementationMetadata(
            fdc3Version="2.2",
            provider="py-fdc3-desktop-agent",
            providerVersion=__version__,
            optionalFeatures={
                # We do not currently expose originating app metadata on
                # context/intent delivery payloads.
                "OriginatingAppMetadata": False,
                "UserChannelMembershipAPIs": True,
                # Bridging is optional and only available when configured.
                "DesktopAgentBridging": self.bridge_client is not None,
            },
            appMetadata=AppMetadata(
                appId=app_id,
                instanceId=instance_id,
                name=name,
                version=version,
                description=description,
                icons=icons,
            ),
        )

        response = GetInfoResponse(
            type="getInfoResponse",
            payload=GetInfoResponsePayload(implementationMetadata=impl),
            meta=self._meta_from_request(request),
        )
        await self._send_model(websocket, response)

    async def _handle_get_app_metadata(
        self, request: GetAppMetadataRequest, *, websocket: WebSocket
    ) -> None:
        app_id = request.payload.app.appId
        if not app_id:
            await self._send_error(
                websocket, "getAppMetadataResponse", DACPError.APP_NOT_FOUND, request
            )
            return

        try:
            meta = await self.storage.apps.get_app_metadata(app_id)
        except Exception:
            logger.debug(
                "getAppMetadata: failed to load app metadata from storage",
                exc_info=True,
            )
            meta = None

        if not meta:
            await self._send_error(
                websocket, "getAppMetadataResponse", DACPError.APP_NOT_FOUND, request
            )
            return

        app_meta = AppMetadata(
            appId=getattr(meta, "app_id", None)
            or getattr(meta, "appId", None)
            or app_id,
            name=getattr(meta, "name", None),
            version=getattr(meta, "version", None),
            description=getattr(meta, "description", None),
            icons=getattr(meta, "icons", None),
        )

        response = GetAppMetadataResponse(
            type="getAppMetadataResponse",
            payload=GetAppMetadataResponsePayload(appMetadata=app_meta),
            meta=self._meta_from_request(request),
        )
        await self._send_model(websocket, response)

    def _ensure_default_user_channels(self) -> None:
        """Ensure a baseline set of user channels exists.

        This is a best-effort convenience for clients that expect user channels
        to be available without prior configuration.
        """
        try:
            existing = [
                c
                for c in core_services.channel_manager.list_channels()
                if getattr(c, "type", None) == "user"
            ]
        except Exception:
            existing = []

        if existing:
            return

        for channel_id, name, color in self.DEFAULT_USER_CHANNELS:
            if core_services.channel_manager.get_channel(channel_id) is None:
                core_services.channel_manager.create_channel(
                    channel_id,
                    "user",
                    display_metadata=DisplayMetadata(name=name, color=color),
                )

    @staticmethod
    def _extract_storage_app_id(meta: object) -> str | None:
        return getattr(meta, "app_id", None) or getattr(meta, "appId", None)

    @staticmethod
    def _wire_app_metadata(app_id: str, meta: object | None) -> AppMetadata:
        return AppMetadata(
            appId=app_id,
            name=getattr(meta, "name", None) if meta is not None else None,
            version=getattr(meta, "version", None) if meta is not None else None,
            description=getattr(meta, "description", None)
            if meta is not None
            else None,
            icons=getattr(meta, "icons", None) if meta is not None else None,
        )

    @staticmethod
    def _wire_channel(channel) -> WireChannel:
        display = getattr(channel, "display_metadata", None)
        if display is not None:
            dm = WireDisplayMetadata(
                name=getattr(display, "name", None),
                color=getattr(display, "color", None),
                glyph=getattr(display, "glyph", None),
            )
        else:
            dm = None
        return WireChannel(
            id=getattr(channel, "id"), type=getattr(channel, "type"), displayMetadata=dm
        )

    async def _handle_get_user_channels(
        self, request: GetUserChannelsRequest, *, websocket: WebSocket
    ) -> None:
        self._ensure_default_user_channels()
        channels = [
            self._wire_channel(c)
            for c in core_services.channel_manager.list_channels()
            if getattr(c, "type", None) == "user"
        ]

        response = GetUserChannelsResponse(
            type="getUserChannelsResponse",
            payload=GetUserChannelsResponsePayload(channels=channels),
            meta=self._meta_from_request(request),
        )
        await self._send_model(websocket, response)

    async def _handle_get_current_channel(
        self,
        request: GetCurrentChannelRequest,
        *,
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ) -> None:
        instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        current = core_services.channel_manager.get_current_channel(instance_uuid)
        response = GetCurrentChannelResponse(
            type="getCurrentChannelResponse",
            payload=GetCurrentChannelResponsePayload(
                channel=(self._wire_channel(current) if current is not None else None)
            ),
            meta=self._meta_from_request(request),
        )
        await self._send_model(websocket, response)

    async def _handle_get_current_context(
        self,
        request: GetCurrentContextRequest,
        *,
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ) -> None:
        instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        current_channel = core_services.channel_manager.get_current_channel(
            instance_uuid
        )
        requested_channel_id = request.payload.channelId
        target_channel_id: str | None = None

        if requested_channel_id:
            channel = core_services.channel_manager.get_channel(requested_channel_id)
            if channel is None:
                await self._send_error(
                    websocket,
                    "getCurrentContextResponse",
                    DACPError.NO_CHANNEL_FOUND,
                    request,
                )
                return
            if (
                current_channel is None
                or getattr(current_channel, "id", None) != requested_channel_id
            ):
                await self._send_error(
                    websocket,
                    "getCurrentContextResponse",
                    DACPError.CHANNEL_ACCESS_DENIED,
                    request,
                )
                return
            target_channel_id = requested_channel_id
        elif current_channel is not None:
            target_channel_id = current_channel.id

        context = None
        if target_channel_id is not None:
            context = core_services.channel_manager.get_channel_context(
                target_channel_id, request.payload.contextType
            )

        response = GetCurrentContextResponse(
            type="getCurrentContextResponse",
            payload=GetCurrentContextResponsePayload(context=context),
            meta=self._meta_from_request(request),
        )
        await self._send_model(websocket, response)

    async def _handle_join_user_channel(
        self,
        request: JoinUserChannelRequest,
        *,
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ) -> None:
        self._ensure_default_user_channels()

        raw_id = request.payload.channelId
        channel_id = raw_id if ":" in raw_id else f"user:{raw_id}"

        channel = core_services.channel_manager.get_channel(channel_id)
        if channel is None or getattr(channel, "type", None) != "user":
            await self._send_error(
                websocket,
                "joinUserChannelResponse",
                DACPError.NO_CHANNEL_FOUND,
                request,
            )
            return

        instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        core_services.channel_manager.join_channel(instance_uuid, channel_id)
        logger.info(f"Instance {instance_uuid} joined channel {channel_id}")

        response = JoinUserChannelResponse(
            type="joinUserChannelResponse",
            payload=JoinUserChannelResponsePayload(channel=self._wire_channel(channel)),
            meta=self._meta_from_request(request),
        )
        await self._send_model(websocket, response)
        await self._emit_user_channel_changed_event(
            instance_uuid=instance_uuid, current_channel_id=channel_id
        )

    async def _handle_leave_current_channel(
        self,
        request: LeaveCurrentChannelRequest,
        *,
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ) -> None:
        instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        core_services.channel_manager.leave_current_channel(instance_uuid)

        response = LeaveCurrentChannelResponse(
            type="leaveCurrentChannelResponse",
            payload=LeaveCurrentChannelResponsePayload(),
            meta=self._meta_from_request(request),
        )
        await self._send_model(websocket, response)
        await self._emit_user_channel_changed_event(
            instance_uuid=instance_uuid, current_channel_id=None
        )

    async def _handle_join_private_channel(
        self,
        request: JoinPrivateChannelRequest,
        *,
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ) -> None:
        channel_id = request.payload.channelId
        channel = core_services.channel_manager.get_channel(channel_id)

        if channel is None or getattr(channel, "type", None) != "private":
            await self._send_error(
                websocket,
                "joinPrivateChannelResponse",
                DACPError.NO_CHANNEL_FOUND,
                request,
            )
            return

        instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        owner = core_services.channel_manager.get_private_channel_owner(channel_id)
        invitation_token = request.payload.invitationToken
        if instance_uuid != owner:
            valid_invite = False
            if invitation_token:
                valid_invite = (
                    core_services.channel_manager.consume_private_channel_invite(
                        channel_id, invitation_token, instance_uuid
                    )
                )
            if not valid_invite:
                await self._send_error(
                    websocket,
                    "joinPrivateChannelResponse",
                    DACPError.CHANNEL_ACCESS_DENIED,
                    request,
                )
                return

        core_services.channel_manager.join_channel(instance_uuid, channel_id)

        response = JoinPrivateChannelResponse(
            type="joinPrivateChannelResponse",
            payload=JoinPrivateChannelResponsePayload(
                channel=self._wire_channel(channel)
            ),
            meta=self._meta_from_request(request),
        )
        await self._send_model(websocket, response)

    async def _handle_leave_private_channel(
        self,
        request: LeavePrivateChannelRequest,
        *,
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ) -> None:
        channel_id = request.payload.channelId
        channel = core_services.channel_manager.get_channel(channel_id)

        if channel is None or getattr(channel, "type", None) != "private":
            await self._send_error(
                websocket,
                "leavePrivateChannelResponse",
                DACPError.NO_CHANNEL_FOUND,
                request,
            )
            return

        instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        current = core_services.channel_manager.get_current_channel(instance_uuid)
        if current is None or getattr(current, "id", None) != channel_id:
            await self._send_error(
                websocket,
                "leavePrivateChannelResponse",
                DACPError.CHANNEL_ACCESS_DENIED,
                request,
            )
            return

        core_services.channel_manager.leave_current_channel(instance_uuid)

        response = LeavePrivateChannelResponse(
            type="leavePrivateChannelResponse",
            payload=LeavePrivateChannelResponsePayload(),
            meta=self._meta_from_request(request),
        )
        await self._send_model(websocket, response)

    async def _handle_create_private_channel(
        self,
        request: CreatePrivateChannelRequest,
        *,
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ) -> None:
        instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        # Convert wire DisplayMetadata (from fdc3.models.identifiers) to the agent's
        # DisplayMetadata type expected by the channel manager.
        wire_dm = request.payload.displayMetadata
        metadata: DisplayMetadata | None = None
        if wire_dm is not None:
            metadata = DisplayMetadata(
                name=getattr(wire_dm, "name", None),
                color=getattr(wire_dm, "color", None),
                glyph=getattr(wire_dm, "glyph", None),
            )
        try:
            channel = core_services.channel_manager.create_private_channel(
                instance_uuid,
                display_metadata=metadata,
            )
        except ValueError:
            await self._send_error(
                websocket,
                "createPrivateChannelResponse",
                DACPError.CHANNEL_CREATION_FAILED,
                request,
            )
            return

        response = CreatePrivateChannelResponse(
            type="createPrivateChannelResponse",
            payload=CreatePrivateChannelResponsePayload(
                channel=self._wire_channel(channel)
            ),
            meta=self._meta_from_request(request),
        )
        await self._send_model(websocket, response)

    async def _handle_create_private_channel_invitation(
        self,
        request: CreatePrivateChannelInvitationRequest,
        *,
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ) -> None:
        channel_id = request.payload.channelId
        channel = core_services.channel_manager.get_channel(channel_id)

        if channel is None or getattr(channel, "type", None) != "private":
            await self._send_error(
                websocket,
                "createPrivateChannelInvitationResponse",
                DACPError.NO_CHANNEL_FOUND,
                request,
            )
            return

        instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        owner = core_services.channel_manager.get_private_channel_owner(channel_id)
        if instance_uuid != owner:
            await self._send_error(
                websocket,
                "createPrivateChannelInvitationResponse",
                DACPError.CHANNEL_ACCESS_DENIED,
                request,
            )
            return

        token = core_services.channel_manager.create_private_channel_invite(
            channel_id, request.payload.instanceId
        )

        response = CreatePrivateChannelInvitationResponse(
            type="createPrivateChannelInvitationResponse",
            payload=CreatePrivateChannelInvitationResponsePayload(
                invitationToken=token
            ),
            meta=self._meta_from_request(request),
        )
        await self._send_model(websocket, response)

    async def _handle_private_channel_disconnect(
        self,
        request: PrivateChannelDisconnectRequest,
        *,
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ) -> None:
        instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        channel_id = request.payload.channelId
        channel = core_services.channel_manager.get_channel(channel_id)

        if channel is None or getattr(channel, "type", None) != "private":
            await self._send_error(
                websocket,
                "privateChannelDisconnectResponse",
                DACPError.NO_CHANNEL_FOUND,
                request,
            )
            return

        owner = core_services.channel_manager.get_private_channel_owner(channel_id)
        if instance_uuid != owner and instance_uuid not in channel.members:
            await self._send_error(
                websocket,
                "privateChannelDisconnectResponse",
                DACPError.CHANNEL_ACCESS_DENIED,
                request,
            )
            return

        core_services.channel_manager.destroy_private_channel(channel_id)
        await self._emit_private_channel_event(
            channel_id=channel_id,
            event_type=PrivateChannelEventListenerTypes.onDisconnect,
            details={"initiatorInstanceUuid": instance_uuid},
        )
        response = PrivateChannelDisconnectResponse(
            type="privateChannelDisconnectResponse",
            payload=PrivateChannelDisconnectResponsePayload(),
            meta=self._meta_from_request(request),
        )
        await self._send_model(websocket, response)

    async def _handle_add_event_listener(
        self,
        request: AddEventListenerRequest,
        *,
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ) -> None:
        instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        listener = core_services.listener_store.add_event_listener(
            ListenerUuid(), instance_uuid, request.payload.eventType
        )

        response = AddEventListenerResponse(
            type="addEventListenerResponse",
            payload=AddEventListenerResponsePayload(
                listenerUuid=listener.listener_uuid
            ),
            meta=self._meta_from_request(request),
        )
        await self._send_model(websocket, response)

    async def _handle_remove_event_listener(
        self, request: RemoveEventListenerRequest, *, websocket: WebSocket
    ) -> None:
        core_services.listener_store.remove_listener(request.payload.listenerUuid.root)
        response = RemoveEventListenerResponse(
            type="removeEventListenerResponse",
            payload=RemoveEventListenerResponsePayload(),
            meta=self._meta_from_request(request),
        )
        await self._send_model(websocket, response)

    async def _handle_find_intent(
        self, request: FindIntentRequest, *, websocket: WebSocket
    ):
        """Handle findIntent request.

        This is a best-effort implementation based on the app directory (static
        metadata) and currently registered intent listeners (runtime).
        """
        try:
            intent = request.payload.intent
            app_ids: set[str] = set()
            app_meta_by_id: dict[str, object] = {}

            # From app directory
            try:
                listed = await self.storage.apps.list_apps()
            except Exception:
                listed = []

            for meta in listed or []:
                app_id = self._extract_storage_app_id(meta)
                intents = getattr(meta, "intents", None) or []
                if app_id and intent in intents:
                    app_ids.add(app_id)
                    app_meta_by_id[app_id] = meta

            # From runtime listeners
            try:
                listeners = (
                    core_services.listener_store.get_intent_listeners_for_intent(intent)
                )
            except Exception:
                listeners = []

            for listener in listeners:
                instance_uuid = getattr(listener, "instance_uuid", None)
                if not instance_uuid:
                    continue
                inst = core_services.app_registry.get_instance(instance_uuid)
                if inst is not None and getattr(inst, "app_id", None):
                    app_ids.add(inst.app_id)

            target = request.payload.target
            if target is not None:
                target_app_id = target.appId
                target_instance_id = target.instanceId
                if target_instance_id:
                    instances = core_services.app_registry.get_instances_for_app(
                        target_app_id
                    )
                    if not any(
                        getattr(i, "instance_id", None) == target_instance_id
                        for i in instances
                    ):
                        await self._send_error(
                            websocket,
                            "findIntentResponse",
                            DACPError.TARGET_INSTANCE_UNAVAILABLE,
                            request,
                        )
                        return

                if target_app_id not in app_ids:
                    # If app is known in directory, allow it; otherwise treat as unavailable.
                    try:
                        known = await self.storage.apps.get_app_metadata(target_app_id)
                    except Exception:
                        known = None
                    if not known:
                        await self._send_error(
                            websocket,
                            "findIntentResponse",
                            DACPError.TARGET_APP_UNAVAILABLE,
                            request,
                        )
                        return
                    app_ids = {target_app_id}

            if not app_ids:
                await self._send_error(
                    websocket, "findIntentResponse", DACPError.NO_APPS_FOUND, request
                )
                return

            apps: list[AppMetadata] = []
            for app_id in sorted(app_ids):
                meta = app_meta_by_id.get(app_id)
                apps.append(self._wire_app_metadata(app_id, meta))

            app_intent = AppIntent(intent=IntentMetadata(name=intent), apps=apps)
            response = FindIntentResponse(
                type="findIntentResponse",
                payload=FindIntentResponsePayload(appIntent=app_intent),
                meta=self._meta_from_request(request),
            )
            await self._send_model(websocket, response)
        except Exception:
            logger.exception("Error handling findIntent")
            await self._send_error(
                websocket, "findIntentResponse", DACPError.RESOLVER_UNAVAILABLE, request
            )

    async def _handle_find_intents_by_context(
        self, request: FindIntentsByContextRequest, *, websocket: WebSocket
    ):
        """Handle findIntentsByContext request.

        This agent does not yet maintain intent<->context type mappings.
        As a best-effort, return intents declared by the app directory and
        by currently registered intent listeners (ignoring compatibility).
        """
        try:
            intent_to_apps: dict[str, set[str]] = {}
            app_meta_by_id: dict[str, object] = {}

            # Directory intents
            try:
                listed = await self.storage.apps.list_apps()
            except Exception:
                listed = []
            for meta in listed or []:
                app_id = self._extract_storage_app_id(meta)
                if not app_id:
                    continue
                intents = getattr(meta, "intents", None) or []
                app_meta_by_id[app_id] = meta
                for intent in intents:
                    intent_to_apps.setdefault(intent, set()).add(app_id)

            # Runtime listeners
            try:
                listeners = getattr(
                    core_services.listener_store, "intent_listeners", {}
                )
            except Exception:
                listeners = {}
            for listener in (listeners or {}).values():
                intent = getattr(listener, "intent", None)
                instance_uuid = getattr(listener, "instance_uuid", None)
                if not intent or not instance_uuid:
                    continue
                inst = core_services.app_registry.get_instance(instance_uuid)
                if inst is not None and getattr(inst, "app_id", None):
                    intent_to_apps.setdefault(intent, set()).add(inst.app_id)

            app_intents: list[AppIntent] = []
            for intent in sorted(intent_to_apps.keys()):
                apps: list[AppMetadata] = []
                for app_id in sorted(intent_to_apps[intent]):
                    meta = app_meta_by_id.get(app_id)
                    apps.append(self._wire_app_metadata(app_id, meta))
                if apps:
                    app_intents.append(
                        AppIntent(intent=IntentMetadata(name=intent), apps=apps)
                    )

            if not app_intents:
                await self._send_error(
                    websocket,
                    "findIntentsByContextResponse",
                    DACPError.NO_APPS_FOUND,
                    request,
                )
                return

            response = FindIntentsByContextResponse(
                type="findIntentsByContextResponse",
                payload=FindIntentsByContextResponsePayload(appIntents=app_intents),
                meta=self._meta_from_request(request),
            )
            await self._send_model(websocket, response)
        except Exception:
            logger.exception("Error handling findIntentsByContext")
            await self._send_error(
                websocket,
                "findIntentsByContextResponse",
                DACPError.RESOLVER_UNAVAILABLE,
                request,
            )

    async def _handle_find_instances(
        self, request: FindInstancesRequest, *, websocket: WebSocket
    ):
        """Handle findInstances request.

        Returns the list of currently known runtime instances for the given appId.
        """
        try:
            app_id = request.payload.app.appId
            requested_instance_id = request.payload.app.instanceId
            instances = core_services.app_registry.get_instances_for_app(app_id)

            result: list[AppIdentifier] = []
            for inst in instances:
                inst_id = getattr(inst, "instance_id", None)
                if requested_instance_id and inst_id != requested_instance_id:
                    continue
                if inst_id is None:
                    continue
                result.append(
                    AppIdentifier(appId=app_id, instanceId=inst_id, desktopAgent=None)
                )

            response = FindInstancesResponse(
                type="findInstancesResponse",
                payload=FindInstancesResponsePayload(instances=result),
                meta=self._meta_from_request(request),
            )
            await self._send_model(websocket, response)
        except Exception:
            logger.exception("Error handling findInstances")
            await self._send_error(
                websocket,
                "findInstancesResponse",
                DACPError.RESOLVER_UNAVAILABLE,
                request,
            )

    async def _handle_open(
        self,
        request: OpenRequest,
        websocket: WebSocket,
        *,
        session_id: str | None = None,
        wcp_sessions: Dict[str, Any] | None = None,
    ):
        """Handle open request - launch the specified app"""
        try:
            # If the request targets a remote Desktop Agent (Agent Bridging), forward it.
            target_da = getattr(request.payload.app, "desktopAgent", None)
            if target_da and getattr(self, "bridge_client", None) is not None:
                bridge = self.bridge_client
                if bridge is not None and getattr(bridge, "is_connected", False):
                    identity = {}
                    if session_id is not None and wcp_sessions is not None:
                        identity = (wcp_sessions.get(session_id) or {}).get(
                            "identity"
                        ) or {}
                    source_identity = AppIdentifier(
                        appId=identity.get("appId") or "unknown",
                        instanceId=identity.get("instanceId"),
                        desktopAgent=None,
                    )

                    bridge_payload = {
                        "app": request.payload.app.model_dump(),
                        "context": request.payload.context,
                    }
                    bridge_resp = await bridge.send_agent_request(
                        request_type="openRequest",
                        payload=bridge_payload,
                        source=source_identity,
                        destination=request.payload.app,
                    )
                    payload = bridge_resp.get("payload") or {}
                    if payload.get("error"):
                        response = AgentResponse(
                            type="openResponse",
                            payload=ErrorResponsePayload(
                                error=str(payload.get("error"))
                            ),
                            meta=self._meta_from_request(request),
                        )
                    else:
                        response = OpenResponse(
                            type="openResponse",
                            payload=OpenResponsePayload(),
                            meta=self._meta_from_request(request),
                        )
                    await self._send_model(websocket, response)
                    return

            app_id = request.payload.app.appId

            # Check if app exists in directory
            app_metadata = await self.storage.apps.get_app_metadata(app_id)
            if not app_metadata:
                await self._send_error(
                    websocket, "openResponse", DACPError.APP_NOT_FOUND, request
                )
                return

            # Check existing instances
            existing_instances = core_services.app_registry.get_instances_for_app(
                app_id
            )
            requested_instance_id = getattr(request.payload.app, "instanceId", None)

            if requested_instance_id:
                existing_instance = next(
                    (
                        inst
                        for inst in existing_instances
                        if inst.instance_id == requested_instance_id
                    ),
                    None,
                )
                if existing_instance:
                    response = OpenResponse(
                        type="openResponse",
                        payload=OpenResponsePayload(),
                        meta=self._meta_from_request(request),
                    )
                    await self._send_model(websocket, response)
                    return
            elif existing_instances:
                # Reuse existing instance
                response = OpenResponse(
                    type="openResponse",
                    payload=OpenResponsePayload(),
                    meta=self._meta_from_request(request),
                )
                await self._send_model(websocket, response)
                return

            # Get launch config
            launch_config = await self.storage.launch_configs.get_launch_config(app_id)
            if not launch_config:
                await self._send_error(
                    websocket, "openResponse", DACPError.APP_NOT_FOUND, request
                )
                return

            # Launch the app
            launch_result = await self.launcher.launch_app(
                app_id, launch_config, request.payload.context, request.payload.app
            )

            if launch_result.success:
                if not launch_result.instance_id or not launch_result.instance_uuid:
                    await self._send_error(
                        websocket, "openResponse", DACPError.ERROR_ON_LAUNCH, request
                    )
                    return

                # Register as pending
                core_services.app_registry.register_pending_instance(
                    app_id, launch_result.instance_id, launch_result.instance_uuid
                )

                # Wait for connection
                connected = (
                    await core_services.app_registry.wait_for_instance_connection(
                        launch_result.instance_uuid, timeout=15.0
                    )
                )

                if connected:
                    response = OpenResponse(
                        type="openResponse",
                        payload=OpenResponsePayload(),
                        meta=self._meta_from_request(request),
                    )
                    await self._send_model(websocket, response)
                else:
                    core_services.app_registry.unregister_instance(
                        launch_result.instance_uuid
                    )
                    await self._send_error(
                        websocket, "openResponse", DACPError.APP_TIMEOUT, request
                    )
            else:
                await self._send_error(
                    websocket, "openResponse", DACPError.ERROR_ON_LAUNCH, request
                )

        except Exception as e:
            logger.error(f"Failed to open app: {e}")
            # Try to send error response if possible
            try:
                await self._send_error(
                    websocket, "openResponse", DACPError.ERROR_ON_LAUNCH, request
                )
            except Exception:
                pass

    async def _handle_broadcast(
        self,
        request: BroadcastRequest,
        *,
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ):
        """Handle broadcast request"""
        source_instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)

        # Forward to Desktop Agent Bridge (best-effort). The bridge won't echo
        # back to this agent, so we still deliver locally.
        try:
            bridge = getattr(self, "bridge_client", None)
            if bridge is not None and getattr(bridge, "is_connected", False):
                source_identity = wcp_sessions[session_id]["identity"]
                await bridge.send_request_no_wait(
                    request_type="broadcastRequest",
                    payload={"context": request.payload.context},
                    source=AppIdentifier(
                        appId=source_identity["appId"],
                        instanceId=source_identity.get("instanceId"),
                        desktopAgent=None,
                    ),
                )
        except Exception:
            # Best-effort: local broadcast must still succeed.
            pass

        targets = core_services.context_router.broadcast_context(
            request.payload.context, source_instance_uuid
        )

        # Send broadcast event to targets
        for target_uuid in targets:
            event = BroadcastEvent(
                type="broadcastEvent",
                payload=BroadcastEventPayload(context=request.payload.context),
                meta=AgentEventMeta(),
            )
            try:
                await self.connection_manager.send_to_instance(
                    target_uuid, event.model_dump_json()
                )
            except Exception:
                logger.exception(f"Failed to send broadcast to {target_uuid}")

    async def _handle_add_context_listener(
        self,
        request: AddContextListenerRequest,
        *,
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ):
        """Handle add context listener request"""
        source_instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)

        current_channel = core_services.channel_manager.get_current_channel(
            source_instance_uuid
        )
        requested_channel_id = request.payload.channelId
        target_channel_id: str | None = None

        if requested_channel_id:
            channel = core_services.channel_manager.get_channel(requested_channel_id)
            if channel is None:
                await self._send_error(
                    websocket,
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
                    websocket,
                    "addContextListenerResponse",
                    DACPError.CHANNEL_ACCESS_DENIED,
                    request,
                )
                return
            target_channel_id = requested_channel_id
        elif current_channel is not None:
            target_channel_id = current_channel.id

        listener = core_services.listener_store.add_context_listener(
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
            initial_context = core_services.channel_manager.get_channel_context(
                target_channel_id, request.payload.contextType
            )
            if initial_context is not None and isinstance(initial_context, dict):
                event = BroadcastEvent(
                    type="broadcastEvent",
                    payload=BroadcastEventPayload(context=initial_context),
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
        await self._send_model(websocket, response)

    async def _handle_add_intent_listener(
        self,
        request: AddIntentListenerRequest,
        *,
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ):
        """Handle add intent listener request"""
        source_instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)

        listener = core_services.listener_store.add_intent_listener(
            ListenerUuid(), source_instance_uuid, request.payload.intent
        )

        response = AddIntentListenerResponse(
            type="addIntentListenerResponse",
            payload=AddIntentListenerResponsePayload(
                listenerUuid=listener.listener_uuid
            ),
            meta=self._meta_from_request(request),
        )
        await self._send_model(websocket, response)

    async def _handle_intent_listener_unsubscribe(
        self, request: IntentListenerUnsubscribeRequest, *, websocket: WebSocket
    ):
        """Handle intent listener unsubscribe"""
        core_services.listener_store.remove_listener(request.payload.listenerUuid.root)

        response = IntentListenerUnsubscribeResponse(
            type="intentListenerUnsubscribeResponse",
            payload=IntentListenerUnsubscribeResponsePayload(),
            meta=self._meta_from_request(request),
        )
        await self._send_model(websocket, response)

    async def _handle_raise_intent(
        self,
        request: RaiseIntentRequest,
        websocket: WebSocket,
        *,
        session_id: str | None = None,
        wcp_sessions: Dict[str, Any] | None = None,
    ):
        """Handle raise intent request"""
        # Agent bridging: if a target is provided with a remote desktopAgent, forward.
        try:
            target = request.payload.target
            target_da = getattr(target, "desktopAgent", None) if target else None
            bridge = getattr(self, "bridge_client", None)
            if (
                target_da
                and bridge is not None
                and getattr(bridge, "is_connected", False)
            ):
                source_identity: AppIdentifier
                if getattr(request.meta, "source", None) is not None:
                    src = request.meta.source
                    source_identity = (
                        src
                        if isinstance(src, AppIdentifier)
                        else AppIdentifier.model_validate(src)
                    )
                else:
                    identity = {}
                    if session_id is not None and wcp_sessions is not None:
                        identity = (wcp_sessions.get(session_id) or {}).get(
                            "identity"
                        ) or {}
                    source_identity = AppIdentifier(
                        appId=identity.get("appId") or "unknown",
                        instanceId=identity.get("instanceId"),
                        desktopAgent=None,
                    )

                bridge_resp = await bridge.send_agent_request(
                    request_type="raiseIntentRequest",
                    payload={
                        "intent": request.payload.intent,
                        "context": request.payload.context,
                        "app": target.model_dump() if target else None,
                    },
                    source=source_identity,
                    destination=target,
                )

                payload = bridge_resp.get("payload") or {}
                if payload.get("error"):
                    response = AgentResponse(
                        type="raiseIntentResponse",
                        payload=ErrorResponsePayload(error=str(payload.get("error"))),
                        meta=self._meta_from_request(request),
                    )
                else:
                    intent_resolution_raw = payload.get("intentResolution")
                    intent_resolution = WireIntentResolution.model_validate(
                        intent_resolution_raw
                    )
                    response = RaiseIntentResponse(
                        type="raiseIntentResponse",
                        payload=RaiseIntentResponsePayload(
                            intentResolution=intent_resolution
                        ),
                        meta=self._meta_from_request(request),
                    )
                await self._send_model(websocket, response)
                return
        except Exception:
            # Fall back to local resolution.
            pass

        # Check if this is a system intent first
        if self.system_intent_handler.is_system_intent(request.payload.intent):
            response = await self.system_intent_handler.handle_system_intent(
                request.payload.intent,
                request.payload.context,
                request.payload.target,
                websocket,
                request.meta.requestUuid,
            )
            if response:
                await self._send_model(websocket, response)
                return

        # Check if a plugin handles this intent
        plugin_result = await self._try_plugin_handler(request)
        if plugin_result is not None:
            await self._send_model(websocket, plugin_result)
            return

        # Check if an external handler can handle this intent
        external_result = await self._try_external_handler(request, websocket)
        if external_result is not None:
            # external_result is either an AgentResponse or RaiseIntentResponse
            await self._send_model(websocket, external_result)
            return

        # Not a system intent or plugin, try normal resolution
        resolution: IntentResolution | None = (
            core_services.intent_resolver.resolve_intent(
                request.payload.intent, request.payload.context, request.payload.target
            )
        )

        if resolution:
            response = RaiseIntentResponse(
                type="raiseIntentResponse",
                payload=RaiseIntentResponsePayload(
                    intentResolution=resolution.model_dump()
                ),
                meta=self._meta_from_request(request),
            )
            await self._send_model(websocket, response)

            # Send intent event to listeners
            targets = core_services.intent_resolver.deliver_intent_event(
                request.payload.intent, request.payload.context, request.meta.source
            )

            for target_uuid in targets:
                event = IntentEvent(
                    type="intentEvent",
                    payload=IntentEventPayload(
                        intent=request.payload.intent,
                        context=request.payload.context,
                        originatingApp=request.meta.source,
                    ),
                    meta=AgentEventMeta(),
                )
                await self.connection_manager.send_to_instance(
                    target_uuid, event.model_dump_json()
                )
        else:
            await self._send_error(
                websocket, "raiseIntentResponse", DACPError.NO_APPS_FOUND, request
            )

    async def _handle_raise_intent_for_context(
        self, request: RaiseIntentForContextRequest, *, websocket: WebSocket
    ):
        """Handle raise intent for context request"""
        try:
            # This agent does not yet track intent<->contextType compatibility.
            # Implement a minimal resolver:
            # - If there are no intent listeners, return NoAppsFound.
            # - If there are multiple distinct intents available, return ResolverUnavailable
            #   (we have no user intent resolver UI).
            intent_listeners = getattr(
                core_services.listener_store, "intent_listeners", {}
            )
            # Build a sorted list of intent names (coerce to str for type-safety)
            available_intents = sorted(
                {
                    str(getattr(listener, "intent", ""))
                    for listener in intent_listeners.values()
                    if getattr(listener, "intent", None)
                }
            )

            if not available_intents:
                await self._send_error(
                    websocket,
                    "raiseIntentForContextResponse",
                    DACPError.NO_APPS_FOUND,
                    request,
                )
                return

            if len(available_intents) != 1:
                await self._send_error(
                    websocket,
                    "raiseIntentForContextResponse",
                    DACPError.RESOLVER_UNAVAILABLE,
                    request,
                )
                return

            intent = available_intents[0]
            resolution: IntentResolution | None = (
                core_services.intent_resolver.resolve_intent(
                    intent, request.payload.context, request.payload.target
                )
            )

            if not resolution:
                await self._send_error(
                    websocket,
                    "raiseIntentForContextResponse",
                    DACPError.NO_APPS_FOUND,
                    request,
                )
                return

            intent_resolution = WireIntentResolution.model_validate(
                resolution.model_dump()
            )
            response = RaiseIntentForContextResponse(
                type="raiseIntentForContextResponse",
                payload=RaiseIntentForContextResponsePayload(
                    intentResolution=intent_resolution
                ),
                meta=self._meta_from_request(request),
            )
            await self._send_model(websocket, response)

            # Send intent event to listeners (mirrors raiseIntent behavior)
            targets = core_services.intent_resolver.deliver_intent_event(
                intent, request.payload.context, request.meta.source
            )
            for target_uuid in targets:
                event = IntentEvent(
                    type="intentEvent",
                    payload=IntentEventPayload(
                        intent=intent,
                        context=request.payload.context,
                        originatingApp=request.meta.source,
                    ),
                    meta=AgentEventMeta(),
                )
                await self.connection_manager.send_to_instance(
                    target_uuid, event.model_dump_json()
                )
        except Exception:
            logger.exception("Error handling raiseIntentForContext")
            await self._send_error(
                websocket,
                "raiseIntentForContextResponse",
                DACPError.RESOLVER_UNAVAILABLE,
                request,
            )

    async def _handle_intent_result_request(
        self, request: IntentResultRequest, *, websocket: WebSocket
    ):
        """Handle intent result request"""
        logger.debug(f"Received intent result: {request.payload.intentResult}")

        response = IntentResultResponse(
            type="intentResultResponse",
            payload=IntentResultResponsePayload(),
            meta=self._meta_from_request(request),
        )
        await self._send_model(websocket, response)

    async def _handle_raise_intent_result_response(
        self, request: RaiseIntentResultResponse, *, websocket: WebSocket
    ):
        """Handle raise intent result response"""
        logger.debug(f"Intent result acknowledged: {request.meta.requestUuid}")

    async def _handle_context_listener_unsubscribe(
        self, request: ContextListenerUnsubscribeRequest, *, websocket: WebSocket
    ):
        """Handle context listener unsubscribe"""
        listener = core_services.listener_store.remove_listener(
            request.payload.listenerUuid.root
        )

        if listener:
            instance_uuid = listener.instance_uuid
            channel = core_services.channel_manager.get_current_channel(instance_uuid)
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
        await self._send_model(websocket, response)

    async def _handle_heartbeat_acknowledgment(
        self, request: HeartbeatAcknowledgmentRequest, *, websocket: WebSocket
    ):
        """Handle heartbeat acknowledgment"""
        logger.debug(
            f"Received heartbeat acknowledgment for event {request.payload.heartbeatEventUuid}"
        )

    async def _try_plugin_handler(
        self, request: RaiseIntentRequest
    ) -> AgentResponse | RaiseIntentResponse | None:
        """Try to handle intent via registered plugins.

        Args:
            request: The RaiseIntentRequest from the client.

        Returns:
            Response model if a plugin handled the intent, None otherwise.
        """
        plugins = core_services.plugin_registry.get_plugins_for_intent(
            request.payload.intent
        )

        for plugin in plugins:
            try:
                result = await plugin.handle_intent(
                    request.payload.intent,
                    request.payload.context,
                    request.meta.source.model_dump() if request.meta.source else None,
                )

                if result.handled:
                    if result.error:
                        # Plugin handled but returned an error
                        return AgentResponse(
                            type="raiseIntentResponse",
                            payload=ErrorResponsePayload(error=result.error),
                            meta=self._meta_from_request(request),
                        )

                    # Plugin handled successfully
                    resolution = IntentResolution(
                        source=AppIdentifier(
                            appId=f"plugin:{plugin.name}",
                            instanceId=None,
                            desktopAgent=None,
                        ),
                        intent=request.payload.intent,
                    )
                    return RaiseIntentResponse(
                        type="raiseIntentResponse",
                        payload=RaiseIntentResponsePayload(
                            intentResolution=resolution.model_dump()
                        ),
                        meta=self._meta_from_request(request),
                    )

            except Exception as e:
                logger.error(
                    f"Plugin {plugin.name} raised exception handling "
                    f"{request.payload.intent}: {e}"
                )
                # Continue to next plugin

        return None

    async def _handle_register_external_handler(
        self,
        request: RegisterExternalHandlerRequest,
        *,
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ) -> None:
        """Handle external handler registration - message already validated by parser."""
        logger.debug(
            "_handle_register_external_handler called: session_id=%s wcp_sessions_keys=%s meta=%s",
            session_id,
            list(wcp_sessions.keys()),
            getattr(request, "meta", None),
        )

        try:
            instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
            handler_uuid = await core_services.register_external_handler(
                instance_uuid,
                request.payload.handler_id,
                request.payload.intents,
                request.payload.priority,
                request.payload.metadata,
            )

            # send success response
            response = RegisterExternalHandlerResponse(
                payload=RegisterExternalHandlerResponsePayload(
                    handler_uuid=handler_uuid
                ),
                meta=self._meta_from_request(request),
            )
            logger.debug(
                "Sending registerExternalHandlerResponse: handler_uuid=%s requestUuid=%s",
                handler_uuid,
                request.meta.requestUuid.root,
            )
            await websocket.send_text(response.model_dump_json())
        except Exception:
            logger.exception("Failed to register external handler")
            await self._send_error(
                websocket,
                "registerExternalHandlerResponse",
                DACPError.INTERNAL_ERROR,
                request,
            )

    async def _handle_unregister_external_handler(
        self,
        request: UnregisterExternalHandlerRequest,
        *,
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ):
        """Handle external handler unregistration - message already validated by parser."""
        try:
            await core_services.unregister_external_handler(
                request.payload.handler_uuid
            )

            # Send success response using Pydantic model
            response = UnregisterExternalHandlerResponse(
                meta=self._meta_from_request(request),
            )
            await websocket.send_text(response.model_dump_json())
        except Exception:
            logger.exception("Failed to unregister external handler")
            await self._send_error(
                websocket,
                "unregisterExternalHandlerResponse",
                DACPError.INTERNAL_ERROR,
                request,
            )

    async def _handle_external_intent_result(
        self, request: ExternalIntentResultRequest, *, websocket: WebSocket
    ) -> None:
        """Handle intent result from external handler - message already validated by parser."""
        try:
            core_services.resolve_pending_intent(
                request.payload.request_uuid,
                result=request.payload.result,
                error=request.payload.error,
            )
        except Exception:
            logger.exception("Failed to handle external intent result")

    async def _try_external_handler(
        self, request: RaiseIntentRequest, websocket: WebSocket
    ) -> RaiseIntentResponse | AgentResponse | None:
        """Try to handle intent via registered external handlers.

        Args:
            request: The validated RaiseIntentRequest from the client.
            websocket: The WebSocket connection to respond on.

        Returns:
            Response model if an external handler processed the intent, None otherwise.
        """
        # Find registered external handlers for this intent
        handlers = core_services.external_registry.get_handlers_for_intent(
            request.payload.intent
        )
        if not handlers:
            return None

        # Choose first handler (highest priority)
        handler = handlers[0]

        # Build forwarded intent message using Pydantic model
        request_uuid = str(uuid.uuid4())
        forwarded = ForwardedIntentMessage(
            payload=ForwardedIntentPayload(
                request_uuid=request_uuid,
                intent=request.payload.intent,
                context=request.payload.context or {},
                source=request.meta.source.model_dump() if request.meta.source else {},
            )
        )

        # Create pending future for response correlation
        fut = core_services.create_pending_intent(request_uuid)

        try:
            # Send forwarded intent message using Pydantic serialization
            await self.connection_manager.send_to_instance(
                handler.instance_uuid, forwarded.model_dump_json()
            )
        except Exception as e:
            logger.exception(
                f"Failed to forward intent to external handler {handler.handler_id}: {e}"
            )
            core_services.resolve_pending_intent(request_uuid, error=str(e))
            return None

        try:
            # Wait for result with a reasonable timeout
            result = await asyncio.wait_for(fut, timeout=30.0)
        except asyncio.TimeoutError:
            logger.debug(f"External handler {handler.handler_id} timed out")
            return None
        except Exception as e:
            logger.debug(f"External handler failed: {e}")
            return None

        if result is None:
            return None

        # Build response using the result
        resolution = IntentResolution(
            source=AppIdentifier(
                appId=f"external:{handler.handler_id}",
                instanceId=None,
                desktopAgent=None,
            ),
            intent=request.payload.intent,
        )
        return RaiseIntentResponse(
            type="raiseIntentResponse",
            payload=RaiseIntentResponsePayload(
                intentResolution=resolution.model_dump()
            ),
            meta=self._meta_from_request(request),
        )


# Initialize the handler registry after class definition
DACPHandler._HANDLERS = DACPHandler._init_handlers()
