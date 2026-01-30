"""
Channel-related DACP handlers: user channels, private channels, join/leave operations.
"""

import logging
from typing import TYPE_CHECKING

from fdc3.models.dacp.dacp import (
    GetUserChannelsRequest,
    GetUserChannelsResponse,
    GetUserChannelsResponsePayload,
    GetSystemChannelsRequest,
    GetSystemChannelsResponse,
    GetSystemChannelsResponsePayload,
    GetCurrentChannelRequest,
    GetCurrentChannelResponse,
    GetCurrentChannelResponsePayload,
    GetCurrentContextRequest,
    GetCurrentContextResponse,
    GetCurrentContextResponsePayload,
    JoinUserChannelRequest,
    JoinUserChannelResponse,
    JoinUserChannelResponsePayload,
    JoinChannelRequest,
    JoinChannelResponse,
    JoinChannelResponsePayload,
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
    PrivateChannelDisconnectRequest,
    PrivateChannelDisconnectResponse,
    PrivateChannelDisconnectResponsePayload,
)
from fdc3.models.dacp.enums import PrivateChannelEventListenerTypes
from fdc3.models.identifiers import AppIdentifier
from fdc3.models.primitives import ListenerUuid
from ...api import DisplayMetadata
from ...types import WcpSessions
from ..protocols import MessageSender
from .registry import dacp_handler, DACPError

if TYPE_CHECKING:
    from .base import DACPHandler
    from ...core import CoreServices

logger = logging.getLogger(__name__)


class ChannelHandlersMixin:
    """Mixin providing channel-related DACP handlers."""

    # These attributes are provided by DACPHandler
    _core: "CoreServices"
    _default_user_channels_ready: bool

    @dacp_handler(GetUserChannelsRequest, needs_session=False)
    async def _handle_get_user_channels(
        self: "DACPHandler", request: GetUserChannelsRequest, *, sender: MessageSender
    ) -> None:
        channels = self._get_user_channels()

        response = GetUserChannelsResponse(
            type="getUserChannelsResponse",
            payload=GetUserChannelsResponsePayload(channels=channels),
            meta=self._meta_from_request(request),
        )
        await self._send_model(sender, response)

    @dacp_handler(GetSystemChannelsRequest, needs_session=False)
    async def _handle_get_system_channels(
        self: "DACPHandler", request: GetSystemChannelsRequest, *, sender: MessageSender
    ) -> None:
        channels = self._get_user_channels()

        response = GetSystemChannelsResponse(
            type="getSystemChannelsResponse",
            payload=GetSystemChannelsResponsePayload(channels=channels),
            meta=self._meta_from_request(request),
        )
        await self._send_model(sender, response)

    @dacp_handler(GetCurrentChannelRequest, needs_session=True)
    async def _handle_get_current_channel(
        self: "DACPHandler",
        request: GetCurrentChannelRequest,
        *,
        session_id: str,
        wcp_sessions: WcpSessions,
        sender: MessageSender,
    ) -> None:
        instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        current = self._core.channel_manager.get_current_channel(instance_uuid)
        response = GetCurrentChannelResponse(
            type="getCurrentChannelResponse",
            payload=GetCurrentChannelResponsePayload(
                channel=(self._wire_channel(current) if current is not None else None)
            ),
            meta=self._meta_from_request(request),
        )
        await self._send_model(sender, response)

    @dacp_handler(GetCurrentContextRequest, needs_session=True)
    async def _handle_get_current_context(
        self: "DACPHandler",
        request: GetCurrentContextRequest,
        *,
        session_id: str,
        wcp_sessions: WcpSessions,
        sender: MessageSender,
    ) -> None:
        instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        current_channel = self._core.channel_manager.get_current_channel(instance_uuid)
        requested_channel_id = request.payload.channelId
        target_channel_id: str | None = None

        if requested_channel_id:
            channel = self._core.channel_manager.get_channel(requested_channel_id)
            if channel is None:
                await self._send_error(
                    sender,
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
                    sender,
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
            context = self._core.channel_manager.get_channel_context(
                target_channel_id, request.payload.contextType
            )

        response = GetCurrentContextResponse(
            type="getCurrentContextResponse",
            payload=GetCurrentContextResponsePayload(
                context=self._normalize_context(context)
            ),
            meta=self._meta_from_request(request),
        )
        await self._send_model(sender, response)

    @dacp_handler(JoinUserChannelRequest, needs_session=True)
    async def _handle_join_user_channel(
        self: "DACPHandler",
        request: JoinUserChannelRequest,
        *,
        session_id: str,
        wcp_sessions: WcpSessions,
        sender: MessageSender,
    ) -> None:
        self._ensure_default_user_channels()

        raw_id = request.payload.channelId
        channel_id = raw_id if ":" in raw_id else f"user:{raw_id}"

        channel = self._core.channel_manager.get_channel(channel_id)
        if channel is None or getattr(channel, "type", None) != "user":
            await self._send_error(
                sender,
                "joinUserChannelResponse",
                DACPError.NO_CHANNEL_FOUND,
                request,
            )
            return

        instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        self._core.channel_manager.join_channel(instance_uuid, channel_id)
        logger.info(f"Instance {instance_uuid} joined channel {channel_id}")

        response = JoinUserChannelResponse(
            type="joinUserChannelResponse",
            payload=JoinUserChannelResponsePayload(channel=self._wire_channel(channel)),
            meta=self._meta_from_request(request),
        )
        await self._send_model(sender, response)
        await self._emit_user_channel_changed_event(
            instance_uuid=instance_uuid, current_channel_id=channel_id
        )

    @dacp_handler(JoinChannelRequest, needs_session=True)
    async def _handle_join_channel(
        self: "DACPHandler",
        request: JoinChannelRequest,
        *,
        session_id: str,
        wcp_sessions: WcpSessions,
        sender: MessageSender,
    ) -> None:
        self._ensure_default_user_channels()

        raw_id = request.payload.channelId
        channel_id = raw_id if ":" in raw_id else f"user:{raw_id}"

        channel = self._core.channel_manager.get_channel(channel_id)
        if channel is None or getattr(channel, "type", None) != "user":
            await self._send_error(
                sender,
                "joinChannelResponse",
                DACPError.NO_CHANNEL_FOUND,
                request,
            )
            return

        instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        self._core.channel_manager.join_channel(instance_uuid, channel_id)
        logger.info(f"Instance {instance_uuid} joined channel {channel_id}")

        response = JoinChannelResponse(
            type="joinChannelResponse",
            payload=JoinChannelResponsePayload(channel=self._wire_channel(channel)),
            meta=self._meta_from_request(request),
        )
        await self._send_model(sender, response)
        await self._emit_user_channel_changed_event(
            instance_uuid=instance_uuid, current_channel_id=channel_id
        )

    @dacp_handler(LeaveCurrentChannelRequest, needs_session=True)
    async def _handle_leave_current_channel(
        self: "DACPHandler",
        request: LeaveCurrentChannelRequest,
        *,
        session_id: str,
        wcp_sessions: WcpSessions,
        sender: MessageSender,
    ) -> None:
        instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        self._core.channel_manager.leave_current_channel(instance_uuid)

        response = LeaveCurrentChannelResponse(
            type="leaveCurrentChannelResponse",
            payload=LeaveCurrentChannelResponsePayload(),
            meta=self._meta_from_request(request),
        )
        await self._send_model(sender, response)
        await self._emit_user_channel_changed_event(
            instance_uuid=instance_uuid, current_channel_id=None
        )

    @dacp_handler(JoinPrivateChannelRequest, needs_session=True)
    async def _handle_join_private_channel(
        self: "DACPHandler",
        request: JoinPrivateChannelRequest,
        *,
        session_id: str,
        wcp_sessions: WcpSessions,
        sender: MessageSender,
    ) -> None:
        channel_id = request.payload.channelId
        channel = self._core.channel_manager.get_channel(channel_id)

        if channel is None or getattr(channel, "type", None) != "private":
            await self._send_error(
                sender,
                "joinPrivateChannelResponse",
                DACPError.NO_CHANNEL_FOUND,
                request,
            )
            return

        instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        owner = self._core.channel_manager.get_private_channel_owner(channel_id)
        invitation_token = request.payload.invitationToken
        if instance_uuid != owner:
            valid_invite = False
            if invitation_token:
                valid_invite = (
                    self._core.channel_manager.consume_private_channel_invite(
                        channel_id, invitation_token, instance_uuid
                    )
                )
            if not valid_invite:
                await self._send_error(
                    sender,
                    "joinPrivateChannelResponse",
                    DACPError.CHANNEL_ACCESS_DENIED,
                    request,
                )
                return

        self._core.channel_manager.join_channel(instance_uuid, channel_id)

        response = JoinPrivateChannelResponse(
            type="joinPrivateChannelResponse",
            payload=JoinPrivateChannelResponsePayload(
                channel=self._wire_channel(channel)
            ),
            meta=self._meta_from_request(request),
        )
        await self._send_model(sender, response)

    @dacp_handler(LeavePrivateChannelRequest, needs_session=True)
    async def _handle_leave_private_channel(
        self: "DACPHandler",
        request: LeavePrivateChannelRequest,
        *,
        session_id: str,
        wcp_sessions: WcpSessions,
        sender: MessageSender,
    ) -> None:
        channel_id = request.payload.channelId
        channel = self._core.channel_manager.get_channel(channel_id)

        if channel is None or getattr(channel, "type", None) != "private":
            await self._send_error(
                sender,
                "leavePrivateChannelResponse",
                DACPError.NO_CHANNEL_FOUND,
                request,
            )
            return

        instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        current = self._core.channel_manager.get_current_channel(instance_uuid)
        if current is None or getattr(current, "id", None) != channel_id:
            await self._send_error(
                sender,
                "leavePrivateChannelResponse",
                DACPError.CHANNEL_ACCESS_DENIED,
                request,
            )
            return

        self._core.channel_manager.leave_current_channel(instance_uuid)

        response = LeavePrivateChannelResponse(
            type="leavePrivateChannelResponse",
            payload=LeavePrivateChannelResponsePayload(),
            meta=self._meta_from_request(request),
        )
        await self._send_model(sender, response)

    @dacp_handler(CreatePrivateChannelRequest, needs_session=True)
    async def _handle_create_private_channel(
        self: "DACPHandler",
        request: CreatePrivateChannelRequest,
        *,
        session_id: str,
        wcp_sessions: WcpSessions,
        sender: MessageSender,
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
            channel = self._core.channel_manager.create_private_channel(
                instance_uuid,
                display_metadata=metadata,
            )
        except ValueError:
            await self._send_error(
                sender,
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
        await self._send_model(sender, response)

    @dacp_handler(CreatePrivateChannelInvitationRequest, needs_session=True)
    async def _handle_create_private_channel_invitation(
        self: "DACPHandler",
        request: CreatePrivateChannelInvitationRequest,
        *,
        session_id: str,
        wcp_sessions: WcpSessions,
        sender: MessageSender,
    ) -> None:
        channel_id = request.payload.channelId
        channel = self._core.channel_manager.get_channel(channel_id)

        if channel is None or getattr(channel, "type", None) != "private":
            await self._send_error(
                sender,
                "createPrivateChannelInvitationResponse",
                DACPError.NO_CHANNEL_FOUND,
                request,
            )
            return

        instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        owner = self._core.channel_manager.get_private_channel_owner(channel_id)
        if instance_uuid != owner:
            await self._send_error(
                sender,
                "createPrivateChannelInvitationResponse",
                DACPError.CHANNEL_ACCESS_DENIED,
                request,
            )
            return

        token = self._core.channel_manager.create_private_channel_invite(
            channel_id, request.payload.instanceId
        )

        response = CreatePrivateChannelInvitationResponse(
            type="createPrivateChannelInvitationResponse",
            payload=CreatePrivateChannelInvitationResponsePayload(
                invitationToken=token
            ),
            meta=self._meta_from_request(request),
        )
        await self._send_model(sender, response)

    @dacp_handler(PrivateChannelDisconnectRequest, needs_session=True)
    async def _handle_private_channel_disconnect(
        self: "DACPHandler",
        request: PrivateChannelDisconnectRequest,
        *,
        session_id: str,
        wcp_sessions: WcpSessions,
        sender: MessageSender,
    ) -> None:
        instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        channel_id = request.payload.channelId
        channel = self._core.channel_manager.get_channel(channel_id)

        if channel is None or getattr(channel, "type", None) != "private":
            await self._send_error(
                sender,
                "privateChannelDisconnectResponse",
                DACPError.NO_CHANNEL_FOUND,
                request,
            )
            return

        owner = self._core.channel_manager.get_private_channel_owner(channel_id)
        if instance_uuid != owner and instance_uuid not in channel.members:
            await self._send_error(
                sender,
                "privateChannelDisconnectResponse",
                DACPError.CHANNEL_ACCESS_DENIED,
                request,
            )
            return

        self._core.channel_manager.destroy_private_channel(channel_id)
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
        await self._send_model(sender, response)

    @dacp_handler(PrivateChannelAddEventListenerRequest, needs_session=True)
    async def _handle_private_channel_add_event_listener(
        self: "DACPHandler",
        request: PrivateChannelAddEventListenerRequest,
        *,
        session_id: str,
        wcp_sessions: WcpSessions,
        sender: MessageSender,
    ) -> None:
        instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
        channel_id = request.payload.channelId
        channel = self._core.channel_manager.get_channel(channel_id)

        if channel is None or getattr(channel, "type", None) != "private":
            await self._send_error(
                sender,
                "privateChannelAddEventListenerResponse",
                DACPError.NO_CHANNEL_FOUND,
                request,
            )
            return

        owner = self._core.channel_manager.get_private_channel_owner(channel_id)
        if instance_uuid != owner:
            await self._send_error(
                sender,
                "privateChannelAddEventListenerResponse",
                DACPError.CHANNEL_ACCESS_DENIED,
                request,
            )
            return

        listener = self._core.listener_store.add_event_listener(
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
        await self._send_model(sender, response)

        identity = self._get_session_identity(session_id, wcp_sessions)
        source_identity = AppIdentifier(
            appId=identity.appId or "fdc3-desktop-agent",
            instanceId=identity.instanceId,
            desktopAgent=None,
        )
        await self._bridge_private_channel_listener_update(
            channel_id=channel_id,
            event_type=request.payload.eventType,
            source_identity=source_identity,
            added=True,
        )
