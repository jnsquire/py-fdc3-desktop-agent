"""DACP Private Channel Models."""

from pydantic import BaseModel, Field
from typing import Literal, Optional
from .envelopes import (
    DacpMessage,
    AppRequestMeta,
    AgentResponseMeta,
    register_message_type,
)
from fdc3.models.identifiers import Channel, DisplayMetadata
from fdc3.models.primitives import ListenerUuid
from .enums import PrivateChannelEventListenerTypes


# private channel management
class CreatePrivateChannelRequestPayload(BaseModel):
    """Payload for creating a private channel.

    The caller becomes the channel owner and is joined automatically.
    """

    displayMetadata: Optional[DisplayMetadata] = None


@register_message_type("createPrivateChannel")
class CreatePrivateChannelRequest(DacpMessage):
    """Create a private channel owned by the caller.

    The response contains the created channel metadata, including the assigned
    ``channelId``.
    """

    type: Literal["createPrivateChannel"]
    payload: CreatePrivateChannelRequestPayload = Field(
        default_factory=CreatePrivateChannelRequestPayload
    )
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class CreatePrivateChannelResponsePayload(BaseModel):
    channel: Channel


@register_message_type("createPrivateChannelResponse")
class CreatePrivateChannelResponse(BaseModel):
    type: Literal["createPrivateChannelResponse"]
    payload: CreatePrivateChannelResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class CreatePrivateChannelInvitationRequestPayload(BaseModel):
    """Payload for issuing a private channel invitation.

    ``instanceId`` can be supplied to scope the invitation to a specific app
    instance.
    """

    channelId: str
    instanceId: Optional[str] = None


@register_message_type("createPrivateChannelInvitation")
class CreatePrivateChannelInvitationRequest(DacpMessage):
    """Create a one-time invitation token for a private channel.

    Owners must invite participants before they can join. The returned
    ``invitationToken`` is consumed on the first successful join.
    """

    type: Literal["createPrivateChannelInvitation"]
    payload: CreatePrivateChannelInvitationRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class CreatePrivateChannelInvitationResponsePayload(BaseModel):
    """Response payload containing the invitation token."""

    invitationToken: str


@register_message_type("createPrivateChannelInvitationResponse")
class CreatePrivateChannelInvitationResponse(BaseModel):
    type: Literal["createPrivateChannelInvitationResponse"]
    payload: CreatePrivateChannelInvitationResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class JoinPrivateChannelRequestPayload(BaseModel):
    """Payload for joining a private channel.

    Non-owners must provide ``invitationToken``. Tokens are single-use.
    """

    channelId: str
    invitationToken: Optional[str] = None


@register_message_type("joinPrivateChannel")
class JoinPrivateChannelRequest(DacpMessage):
    """Join a private channel using a valid invitation token."""

    type: Literal["joinPrivateChannel"]
    payload: JoinPrivateChannelRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class JoinPrivateChannelResponsePayload(BaseModel):
    channel: Channel


@register_message_type("joinPrivateChannelResponse")
class JoinPrivateChannelResponse(BaseModel):
    type: Literal["joinPrivateChannelResponse"]
    payload: JoinPrivateChannelResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class LeavePrivateChannelRequestPayload(BaseModel):
    """Payload for leaving a private channel."""

    channelId: str


@register_message_type("leavePrivateChannel")
class LeavePrivateChannelRequest(DacpMessage):
    """Leave a private channel."""

    type: Literal["leavePrivateChannel"]
    payload: LeavePrivateChannelRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class LeavePrivateChannelResponsePayload(BaseModel):
    pass


@register_message_type("leavePrivateChannelResponse")
class LeavePrivateChannelResponse(BaseModel):
    type: Literal["leavePrivateChannelResponse"]
    payload: LeavePrivateChannelResponsePayload = Field(
        default_factory=LeavePrivateChannelResponsePayload
    )
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class PrivateChannelAddEventListenerRequestPayload(BaseModel):
    """Payload for subscribing to private channel events.

    ``eventType`` can be provided to filter events (e.g. add/remove listeners,
    disconnects).
    """

    channelId: str
    eventType: Optional[PrivateChannelEventListenerTypes] = None


@register_message_type("privateChannelAddEventListener")
class PrivateChannelAddEventListenerRequest(DacpMessage):
    """Subscribe to private channel lifecycle events."""

    type: Literal["privateChannelAddEventListener"]
    payload: PrivateChannelAddEventListenerRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class PrivateChannelAddEventListenerResponsePayload(BaseModel):
    listenerUuid: ListenerUuid


@register_message_type("privateChannelAddEventListenerResponse")
class PrivateChannelAddEventListenerResponse(BaseModel):
    type: Literal["privateChannelAddEventListenerResponse"]
    payload: PrivateChannelAddEventListenerResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class PrivateChannelDisconnectRequestPayload(BaseModel):
    """Payload to disconnect a private channel session."""

    channelId: str


@register_message_type("privateChannelDisconnect")
class PrivateChannelDisconnectRequest(DacpMessage):
    """Disconnect from a private channel and fire lifecycle events."""

    type: Literal["privateChannelDisconnect"]
    payload: PrivateChannelDisconnectRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class PrivateChannelDisconnectResponsePayload(BaseModel):
    pass


# Internal lifecycle acknowledgement from the agent; parsed via the
# generic `AgentResponse` envelope rather than being separately registered.
class PrivateChannelDisconnectResponse(BaseModel):
    type: Literal["privateChannelDisconnectResponse"]
    payload: PrivateChannelDisconnectResponsePayload = Field(
        default_factory=PrivateChannelDisconnectResponsePayload
    )
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)
