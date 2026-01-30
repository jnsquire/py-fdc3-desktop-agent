"""
DACP (Desktop Agent Communication Protocol) message handler.
Handles FDC3 operations like app launching, context broadcasting, and listener management.
"""

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional, Protocol, TypedDict

from fdc3.models.dacp.dacp import (
    AgentEventMeta,
    AgentResponse,
    ErrorResponsePayload,
    AgentResponseMeta,
    FDC3EventMessage,
    FDC3EventMessagePayload,
    PrivateChannelEvent,
    PrivateChannelEventPayload,
)
from fdc3.models.dacp.message_parser import parse_message, MessageParseError
from ...storage import Storage
from ...launcher.interfaces import ProcessLauncher
from ...api import DisplayMetadata
from fdc3.models.dacp.enums import PrivateChannelEventListenerTypes
from fdc3.models.identifiers import AppIdentifier
from fdc3.models.identifiers import (
    Channel as WireChannel,
    DisplayMetadata as WireDisplayMetadata,
)
from fdc3.models.identifiers import FDC3Event, FDC3EventType
from fdc3.models.primitives import RequestUuid
from ...types import (
    WcpIdentity,
    WcpSession,
    WcpSessions,
)
from ..connection_manager import WebSocketConnectionManager
from ..protocols import MessageSender
from ..system_intent import SystemIntentHandler
from ...launcher.web_launcher import WebEndpointLauncher
from ...core import core_services

# Import from sibling modules (re-exported for backwards compatibility)
from .registry import dacp_handler, DACPError  # noqa: F401
from .app import AppHandlersMixin
from .channel import ChannelHandlersMixin
from .event import EventHandlersMixin
from .intent import IntentHandlersMixin

if TYPE_CHECKING:
    from ...core.channel_manager import ChannelInstance
    from ...core.app_registry import AppInstance
    from ...storage.interfaces import AppMetadata as StoredAppMetadata

logger = logging.getLogger(__name__)


class BridgeResponseMeta(TypedDict, total=False):
    """Metadata from a bridge response."""

    requestUuid: str
    responseUuid: str
    errorSources: list[str]
    errorDetails: list[dict[str, Any]]


class BridgeResponse(TypedDict, total=False):
    """Response structure from bridge agent requests."""

    type: str
    meta: BridgeResponseMeta
    payload: dict[str, Any]


class BridgeClientProtocol(Protocol):
    """Protocol for bridge client to avoid circular imports."""

    is_connected: bool

    def has_connected_agent(self, name: str) -> bool: ...
    async def send_request_no_wait(
        self,
        request_type: str,
        payload: dict[str, Any],
        source: AppIdentifier,
        destination: AppIdentifier | None = None,
    ) -> None: ...
    async def send_agent_request(
        self,
        *,
        request_type: str,
        payload: dict[str, Any],
        source: AppIdentifier,
        destination: AppIdentifier | None = None,
        timeout: float | None = None,
    ) -> BridgeResponse: ...


class DACPHandler(
    AppHandlersMixin, ChannelHandlersMixin, EventHandlersMixin, IntentHandlersMixin
):
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
        web_launcher: Optional[WebEndpointLauncher] = None,
        core=None,
    ):
        self.storage = storage
        self.launcher = launcher
        self.connection_manager = connection_manager
        self.system_intent_handler = SystemIntentHandler(web_launcher=web_launcher)
        self._core = core or core_services
        # Optional Desktop Agent Bridging client (set by server lifespan).
        self.bridge_client = None
        self._default_user_channels_ready = False

    # Handler registry: maps request types to (handler_method_name, needs_session_context)
    # needs_session_context indicates if the handler requires session_id and wcp_sessions
    _HANDLERS: dict[type, tuple[str, bool]] = {}

    @classmethod
    def _init_handlers(cls) -> dict[type, tuple[str, bool]]:
        """Initialize handler registry. Called once at class definition time.

        Searches the entire MRO to find handlers in mixin classes.
        """
        handlers: dict[type, tuple[str, bool]] = {}
        # Traverse MRO to pick up handlers from all mixin classes
        for klass in cls.__mro__:
            for name in vars(klass):
                value = getattr(klass, name, None)
                info = getattr(value, "_dacp_handler_info", None)
                if info is None:
                    continue
                request_type, needs_session = info
                # Don't override if already registered (first in MRO wins)
                if request_type not in handlers:
                    handlers[request_type] = (name, needs_session)
        return handlers

    @staticmethod
    def _meta_from_request(
        request: Any, bridge_meta: dict[str, Any] | None = None
    ) -> AgentResponseMeta:
        meta = AgentResponseMeta(requestUuid=request.meta.requestUuid)
        if bridge_meta:
            error_sources = bridge_meta.get("errorSources")
            error_details = bridge_meta.get("errorDetails")
            if error_sources is not None:
                meta.errorSources = error_sources
            if error_details is not None:
                meta.errorDetails = error_details
        return meta

    @staticmethod
    def _normalize_app_id(app_id: str | None) -> str | None:
        if not app_id:
            return None
        if "@" in app_id:
            base, _ = app_id.split("@", 1)
            return base or app_id
        return app_id

    async def _resolve_app_id_by_name(self, app_name: str) -> str | None:
        """Resolve an app_id from a human-friendly app name.

        Searches the app directory for an app whose ``name`` matches the given
        string (case-insensitive). Returns the ``app_id`` on match or ``None``.
        """
        if not app_name:
            return None
        try:
            listed: list[StoredAppMetadata] = await self.storage.apps.list_apps()
        except Exception:
            return None
        for meta in listed:
            if meta.name == app_name or meta.name.casefold() == app_name.casefold():
                return meta.app_id
        return None

    def _get_instance_uuid(self, session_id: str, wcp_sessions: WcpSessions) -> str:
        """Extract instance UUID from session context."""
        identity = self._get_session_identity(session_id, wcp_sessions)
        return identity.instanceUuid or ""

    def _get_session_identity(
        self, session_id: str | None, wcp_sessions: WcpSessions | None
    ) -> WcpIdentity:
        """Extract identity dict from session context."""
        if session_id is None or wcp_sessions is None:
            return WcpIdentity()
        session = wcp_sessions.get(session_id) or {}
        if isinstance(session, WcpSession):
            raw_identity = session.identity or {}
        else:
            raw_identity = (session or {}).get("identity") or {}
        if isinstance(raw_identity, WcpIdentity):
            return raw_identity
        try:
            return WcpIdentity.model_validate(raw_identity)
        except Exception:
            return WcpIdentity()

    def _get_source_app_identifier(
        self, session_id: str | None, wcp_sessions: WcpSessions | None
    ) -> AppIdentifier:
        """Build AppIdentifier from session context."""
        identity = self._get_session_identity(session_id, wcp_sessions)
        return AppIdentifier(
            appId=identity.appId or "unknown",
            instanceId=identity.instanceId,
            desktopAgent=None,
        )

    async def _send_error(
        self,
        sender: MessageSender,
        response_type: str,
        error: str,
        request: Any,
        bridge_meta: dict[str, Any] | None = None,
    ) -> None:
        """Send a standardized error response."""
        response = AgentResponse(
            type=response_type,
            payload=ErrorResponsePayload(error=error),
            meta=self._meta_from_request(request, bridge_meta),
        )
        await self._send_model(sender, response)

    @staticmethod
    def _log_bridge_error_details(bridge_resp: dict[str, Any]) -> None:
        meta = bridge_resp.get("meta") or {}
        error_sources = meta.get("errorSources")
        error_details = meta.get("errorDetails")
        if error_sources or error_details:
            logger.warning(
                "Bridge errors: errorSources=%s errorDetails=%s",
                error_sources,
                error_details,
            )

    async def _send_model(self, sender: MessageSender, model) -> None:
        """Helper method to send a Pydantic model as JSON."""
        await sender.send_model(model)

    async def handle_message(
        self,
        message: Dict[str, Any],
        session_id: str,
        wcp_sessions: WcpSessions,
        sender: MessageSender,
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
            await self._send_model(sender, err)
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
                sender=sender,
            )
        else:
            await handler(parsed, sender=sender)

    async def _emit_user_channel_changed_event(
        self, *, instance_uuid: str, current_channel_id: str | None
    ) -> None:
        listeners = self._core.listener_store.get_event_listeners(
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
        listeners = self._core.listener_store.get_event_listeners(
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

        await self._bridge_private_channel_event(
            channel_id=channel_id,
            event_type=event_type,
            details=details,
        )

    def _bridge_source_from_instance_uuid(
        self, instance_uuid: str | None
    ) -> AppIdentifier:
        if instance_uuid:
            try:
                inst: AppInstance | None = self._core.app_registry.get_instance(
                    instance_uuid
                )
            except Exception:
                inst = None
            if inst is not None and inst.app_id:
                return AppIdentifier(
                    appId=inst.app_id,
                    instanceId=inst.instance_id,
                    desktopAgent=None,
                )
        return AppIdentifier(
            appId="fdc3-desktop-agent", instanceId=None, desktopAgent=None
        )

    async def _bridge_private_channel_event(
        self,
        *,
        channel_id: str,
        event_type: PrivateChannelEventListenerTypes,
        details: dict[str, Any] | None = None,
    ) -> None:
        bridge: BridgeClientProtocol | None = self.bridge_client
        if bridge is None or not bridge.is_connected:
            return

        targets = self._core.channel_manager.get_remote_private_channel_listeners(
            channel_id
        )
        if not targets:
            return

        instance_uuid = None
        if isinstance(details, dict):
            instance_uuid = details.get("instanceUuid") or details.get(
                "initiatorInstanceUuid"
            )

        source_identity = self._bridge_source_from_instance_uuid(instance_uuid)
        payload = {
            "channelId": channel_id,
            "eventType": event_type.value,
            "details": details,
        }

        for desktop_agent in targets:
            try:
                await bridge.send_request_no_wait(
                    request_type="privateChannelEvent",
                    payload=payload,
                    source=source_identity,
                    destination=AppIdentifier(
                        appId="fdc3-desktop-agent",
                        instanceId=None,
                        desktopAgent=desktop_agent,
                    ),
                )
            except Exception:
                logger.debug(
                    "Failed to bridge private channel event for %s to %s",
                    channel_id,
                    desktop_agent,
                    exc_info=True,
                )

    async def _bridge_private_channel_listener_update(
        self,
        *,
        channel_id: str,
        event_type: PrivateChannelEventListenerTypes | None,
        source_identity: AppIdentifier,
        added: bool,
    ) -> None:
        bridge: BridgeClientProtocol | None = self.bridge_client
        if bridge is None or not bridge.is_connected:
            return

        payload: dict[str, Any] = {"channelId": channel_id}
        if event_type is not None:
            payload["eventType"] = event_type.value

        try:
            await bridge.send_request_no_wait(
                request_type=(
                    "privateChannelEventListenerAdded"
                    if added
                    else "privateChannelEventListenerRemoved"
                ),
                payload=payload,
                source=source_identity,
            )
        except Exception:
            logger.debug(
                "Failed to bridge private channel listener update for %s",
                channel_id,
                exc_info=True,
            )

    def _ensure_default_user_channels(self) -> None:
        """Ensure a baseline set of user channels exists.

        This is a best-effort convenience for clients that expect user channels
        to be available without prior configuration.
        """
        if self._default_user_channels_ready:
            return
        try:
            existing = [
                c
                for c in self._core.channel_manager.list_channels()
                if c.type == "user"
            ]
        except Exception:
            existing = []

        if existing:
            self._default_user_channels_ready = True
            return

        for channel_id, name, color in self.DEFAULT_USER_CHANNELS:
            if self._core.channel_manager.get_channel(channel_id) is None:
                self._core.channel_manager.create_channel(
                    channel_id,
                    "user",
                    display_metadata=DisplayMetadata(name=name, color=color),
                )

        self._default_user_channels_ready = True

    def _get_user_channels(self) -> list[WireChannel]:
        self._ensure_default_user_channels()
        return [
            self._wire_channel(c)
            for c in self._core.channel_manager.list_channels()
            if c.type == "user"
        ]

    @staticmethod
    def _wire_channel(channel: "ChannelInstance") -> WireChannel:
        display = channel.display_metadata
        if display is not None:
            dm = WireDisplayMetadata(
                name=display.name,
                color=display.color,
                glyph=getattr(display, "glyph", None),
            )
        else:
            dm = None
        return WireChannel(id=channel.id, type=channel.type, displayMetadata=dm)


# Initialize the handler registry after class definition
DACPHandler._HANDLERS = DACPHandler._init_handlers()
