"""DACP User Channel Models."""

from pydantic import BaseModel, Field
from typing import Literal, Optional, List
from .envelopes import (
    DacpMessage,
    AppRequestMeta,
    AgentResponseMeta,
    register_message_type,
    Fdc3Context,
)
from fdc3.models.identifiers import Channel


# user channel membership APIs
class GetUserChannelsRequestPayload(BaseModel):
    pass


@register_message_type("getUserChannels")
class GetUserChannelsRequest(DacpMessage):
    type: Literal["getUserChannels"]
    payload: GetUserChannelsRequestPayload = Field(
        default_factory=GetUserChannelsRequestPayload
    )
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class GetUserChannelsResponsePayload(BaseModel):
    channels: List[Channel]


# Channel list is produced by the agent and may include implementation-
# specific fields; parse via the generic `AgentResponse` envelope.
class GetUserChannelsResponse(BaseModel):
    type: Literal["getUserChannelsResponse"]
    payload: GetUserChannelsResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# deprecated user channel APIs (2.2 compatibility)
class GetSystemChannelsRequestPayload(BaseModel):
    pass


@register_message_type("getSystemChannels")
class GetSystemChannelsRequest(DacpMessage):
    type: Literal["getSystemChannels"]
    payload: GetSystemChannelsRequestPayload = Field(
        default_factory=GetSystemChannelsRequestPayload
    )
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class GetSystemChannelsResponsePayload(BaseModel):
    channels: List[Channel]


# Deprecated (2.2 compatibility) API response — retained for
# compatibility and parsed via the generic `AgentResponse` envelope.
class GetSystemChannelsResponse(BaseModel):
    type: Literal["getSystemChannelsResponse"]
    payload: GetSystemChannelsResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class GetCurrentChannelRequestPayload(BaseModel):
    pass


@register_message_type("getCurrentChannel")
class GetCurrentChannelRequest(DacpMessage):
    type: Literal["getCurrentChannel"]
    payload: GetCurrentChannelRequestPayload = Field(
        default_factory=GetCurrentChannelRequestPayload
    )
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class GetCurrentChannelResponsePayload(BaseModel):
    channel: Optional[Channel] = None


# `channel` may be null or agent-specific; parsed via the generic
# `AgentResponse` envelope to accept implementation variations.
class GetCurrentChannelResponse(BaseModel):
    type: Literal["getCurrentChannelResponse"]
    payload: GetCurrentChannelResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# channel object APIs
class GetCurrentContextRequestPayload(BaseModel):
    contextType: Optional[str] = None
    channelId: Optional[str] = None


@register_message_type("getCurrentContext")
class GetCurrentContextRequest(DacpMessage):
    type: Literal["getCurrentContext"]
    payload: GetCurrentContextRequestPayload = Field(
        default_factory=GetCurrentContextRequestPayload
    )
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class GetCurrentContextResponsePayload(BaseModel):
    context: Optional["Fdc3Context"] = None


# Context payload is arbitrary FDC3 context data; parsed via the
# generic `AgentResponse` envelope to avoid strict per-field validation.
class GetCurrentContextResponse(BaseModel):
    type: Literal["getCurrentContextResponse"]
    payload: GetCurrentContextResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class JoinUserChannelRequestPayload(BaseModel):
    channelId: str


@register_message_type("joinUserChannel")
class JoinUserChannelRequest(DacpMessage):
    type: Literal["joinUserChannel"]
    payload: JoinUserChannelRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class JoinUserChannelResponsePayload(BaseModel):
    channel: Channel


@register_message_type("joinUserChannelResponse")
class JoinUserChannelResponse(BaseModel):
    type: Literal["joinUserChannelResponse"]
    payload: JoinUserChannelResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class JoinChannelRequestPayload(BaseModel):
    channelId: str


@register_message_type("joinChannel")
class JoinChannelRequest(DacpMessage):
    type: Literal["joinChannel"]
    payload: JoinChannelRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class JoinChannelResponsePayload(BaseModel):
    channel: Channel


# Returns a `Channel` from the agent; parse via the generic
# `AgentResponse` envelope to avoid re-registering response types.
class JoinChannelResponse(BaseModel):
    type: Literal["joinChannelResponse"]
    payload: JoinChannelResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class LeaveCurrentChannelRequestPayload(BaseModel):
    pass


@register_message_type("leaveCurrentChannel")
class LeaveCurrentChannelRequest(DacpMessage):
    type: Literal["leaveCurrentChannel"]
    payload: LeaveCurrentChannelRequestPayload = Field(
        default_factory=LeaveCurrentChannelRequestPayload
    )
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class LeaveCurrentChannelResponsePayload(BaseModel):
    pass


@register_message_type("leaveCurrentChannelResponse")
class LeaveCurrentChannelResponse(BaseModel):
    type: Literal["leaveCurrentChannelResponse"]
    payload: LeaveCurrentChannelResponsePayload = Field(
        default_factory=LeaveCurrentChannelResponsePayload
    )
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# Rebuild models with forward references
GetCurrentContextRequest.model_rebuild()
GetCurrentContextResponse.model_rebuild()
