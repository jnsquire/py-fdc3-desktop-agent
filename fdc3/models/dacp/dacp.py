"""DACP Pydantic models (migrated from fdc3.desktop_agent.protocol.dacp.dacp).

This file is a straight relocation of the original DACP models and should
remain functionally equivalent.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal, Union, List, Any, TypeAlias
from fdc3.models.identifiers import AppIdentifier
from fdc3.models.identifiers import AppMetadata
from fdc3.models.identifiers import AppIntent
from fdc3.models.identifiers import DisplayMetadata
from fdc3.models.identifiers import IntentResolution
from fdc3.models.identifiers import Channel
from fdc3.models.identifiers import ImplementationMetadata
from fdc3.models.identifiers import FDC3Event
from fdc3.models.context_types import ContextBase
from fdc3.models.primitives import (
    RequestUuid,
    ResponseUuid,
    EventUuid,
    Timestamp,
    ListenerUuid,
)
from .enums import PrivateChannelEventListenerTypes

# DACP Envelopes

Fdc3Context: TypeAlias = ContextBase

MESSAGE_TYPE_MAP: dict[str, type[BaseModel]] = {}


def register_message_type(message_type: str):
    def decorator(cls: type[BaseModel]) -> type[BaseModel]:
        MESSAGE_TYPE_MAP[message_type] = cls
        return cls

    return decorator


class AppRequestMeta(BaseModel):
    requestUuid: RequestUuid = Field(default_factory=RequestUuid)
    timestamp: Timestamp = Field(default_factory=Timestamp)
    source: Optional["AppIdentifier"] = None


class AppRequest(BaseModel):
    type: str
    payload: dict  # The specific payload depends on the type
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class AgentResponseMeta(BaseModel):
    requestUuid: RequestUuid = Field(default_factory=RequestUuid)
    responseUuid: ResponseUuid = Field(default_factory=ResponseUuid)
    timestamp: Timestamp = Field(default_factory=Timestamp)
    errorSources: Optional[Any] = None
    errorDetails: Optional[Any] = None

    @field_validator("requestUuid", mode="before")
    @classmethod
    def _coerce_request_uuid(cls, v):
        # Accept either a string or an object with `root` (RootModel)
        if isinstance(v, str):
            return RequestUuid(root=v)
        if hasattr(v, "root"):
            return RequestUuid(root=getattr(v, "root"))
        return v


class AgentResponse(BaseModel):
    type: str
    payload: Union[dict, "ErrorResponsePayload"]  # Or specific error payload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class ErrorResponsePayload(BaseModel):
    error: str  # Error enum value as string


class AgentEventMeta(BaseModel):
    eventUuid: EventUuid = Field(default_factory=EventUuid)
    timestamp: Timestamp = Field(default_factory=Timestamp)


class AgentEventPayload(BaseModel):
    eventType: str
    instanceUuid: str


class AgentEvent(BaseModel):
    type: str
    payload: AgentEventPayload
    meta: AgentEventMeta = Field(default_factory=AgentEventMeta)


# Heartbeat
class HeartbeatEventPayload(BaseModel):
    pass  # Empty payload?


class HeartbeatEvent(BaseModel):
    type: Literal["heartbeatEvent"] = "heartbeatEvent"
    payload: HeartbeatEventPayload = Field(default_factory=HeartbeatEventPayload)
    meta: AgentEventMeta = Field(default_factory=AgentEventMeta)


class HeartbeatAcknowledgmentRequestPayload(BaseModel):
    heartbeatEventUuid: EventUuid = Field(default_factory=EventUuid)


@register_message_type("heartbeatAcknowledgmentRequest")
class HeartbeatAcknowledgmentRequest(BaseModel):
    type: Literal["heartbeatAcknowledgmentRequest"]
    payload: HeartbeatAcknowledgmentRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


# Now, specific request/response types for the key messages


# open
class OpenRequestPayload(BaseModel):
    app: Union["AppIdentifier", str]
    context: Optional[Fdc3Context] = None  # Context data


@register_message_type("open")
class OpenRequest(BaseModel):
    type: Literal["open"]
    payload: OpenRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class OpenResponsePayload(BaseModel):
    appIdentifier: Optional[AppIdentifier] = None


class OpenResponse(BaseModel):
    type: Literal["openResponse"]
    payload: OpenResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# broadcast
class BroadcastRequestPayload(BaseModel):
    context: Fdc3Context  # Context data
    channelId: Optional[str] = None  # Optional channel override (used by bridge)


@register_message_type("broadcast")
class BroadcastRequest(BaseModel):
    type: Literal["broadcast"]
    payload: BroadcastRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class BroadcastEventPayload(BaseModel):
    context: Fdc3Context


class BroadcastEvent(BaseModel):
    type: Literal["broadcastEvent"]
    payload: BroadcastEventPayload
    meta: AgentEventMeta = Field(default_factory=AgentEventMeta)


# context listeners
class AddContextListenerRequestPayload(BaseModel):
    contextType: Optional[str] = None
    channelId: Optional[str] = None


@register_message_type("addContextListener")
class AddContextListenerRequest(BaseModel):
    type: Literal["addContextListener"]
    payload: AddContextListenerRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class AddContextListenerResponsePayload(BaseModel):
    listenerUuid: ListenerUuid


class AddContextListenerResponse(BaseModel):
    type: Literal["addContextListenerResponse"]
    payload: AddContextListenerResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class ContextListenerUnsubscribeRequestPayload(BaseModel):
    listenerUuid: ListenerUuid


@register_message_type("contextListenerUnsubscribe")
class ContextListenerUnsubscribeRequest(BaseModel):
    type: Literal["contextListenerUnsubscribe"]
    payload: ContextListenerUnsubscribeRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class ContextListenerUnsubscribeResponsePayload(BaseModel):
    pass


class ContextListenerUnsubscribeResponse(BaseModel):
    type: Literal["contextListenerUnsubscribeResponse"]
    payload: ContextListenerUnsubscribeResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# DesktopAgent event listeners
class AddEventListenerRequestPayload(BaseModel):
    eventType: str


@register_message_type("addEventListener")
class AddEventListenerRequest(BaseModel):
    type: Literal["addEventListener"]
    payload: AddEventListenerRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class AddEventListenerResponsePayload(BaseModel):
    listenerUuid: ListenerUuid


class AddEventListenerResponse(BaseModel):
    type: Literal["addEventListenerResponse"]
    payload: AddEventListenerResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class RemoveEventListenerRequestPayload(BaseModel):
    listenerUuid: ListenerUuid


@register_message_type("removeEventListener")
class RemoveEventListenerRequest(BaseModel):
    type: Literal["removeEventListener"]
    payload: RemoveEventListenerRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class RemoveEventListenerResponsePayload(BaseModel):
    pass


class RemoveEventListenerResponse(BaseModel):
    type: Literal["removeEventListenerResponse"]
    payload: RemoveEventListenerResponsePayload = Field(
        default_factory=RemoveEventListenerResponsePayload
    )
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class FDC3EventMessagePayload(BaseModel):
    event: FDC3Event


class FDC3EventMessage(BaseModel):
    type: Literal["fdc3Event"]
    payload: FDC3EventMessagePayload
    meta: AgentEventMeta = Field(default_factory=AgentEventMeta)


class PrivateChannelEventPayload(BaseModel):
    channelId: str
    eventType: PrivateChannelEventListenerTypes
    details: Optional[dict[str, Any]] = None


class PrivateChannelEvent(BaseModel):
    type: Literal["privateChannelEvent"]
    payload: PrivateChannelEventPayload
    meta: AgentEventMeta = Field(default_factory=AgentEventMeta)


# user channel membership APIs
class GetUserChannelsRequestPayload(BaseModel):
    pass


@register_message_type("getUserChannels")
class GetUserChannelsRequest(BaseModel):
    type: Literal["getUserChannels"]
    payload: GetUserChannelsRequestPayload = Field(
        default_factory=GetUserChannelsRequestPayload
    )
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class GetUserChannelsResponsePayload(BaseModel):
    channels: List[Channel]


class GetUserChannelsResponse(BaseModel):
    type: Literal["getUserChannelsResponse"]
    payload: GetUserChannelsResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# deprecated user channel APIs (2.2 compatibility)
class GetSystemChannelsRequestPayload(BaseModel):
    pass


@register_message_type("getSystemChannels")
class GetSystemChannelsRequest(BaseModel):
    type: Literal["getSystemChannels"]
    payload: GetSystemChannelsRequestPayload = Field(
        default_factory=GetSystemChannelsRequestPayload
    )
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class GetSystemChannelsResponsePayload(BaseModel):
    channels: List[Channel]


class GetSystemChannelsResponse(BaseModel):
    type: Literal["getSystemChannelsResponse"]
    payload: GetSystemChannelsResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class GetCurrentChannelRequestPayload(BaseModel):
    pass


@register_message_type("getCurrentChannel")
class GetCurrentChannelRequest(BaseModel):
    type: Literal["getCurrentChannel"]
    payload: GetCurrentChannelRequestPayload = Field(
        default_factory=GetCurrentChannelRequestPayload
    )
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class GetCurrentChannelResponsePayload(BaseModel):
    channel: Optional[Channel] = None


class GetCurrentChannelResponse(BaseModel):
    type: Literal["getCurrentChannelResponse"]
    payload: GetCurrentChannelResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# channel object APIs
class GetCurrentContextRequestPayload(BaseModel):
    contextType: Optional[str] = None
    channelId: Optional[str] = None


@register_message_type("getCurrentContext")
class GetCurrentContextRequest(BaseModel):
    type: Literal["getCurrentContext"]
    payload: GetCurrentContextRequestPayload = Field(
        default_factory=GetCurrentContextRequestPayload
    )
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class GetCurrentContextResponsePayload(BaseModel):
    context: Optional[Fdc3Context] = None


class GetCurrentContextResponse(BaseModel):
    type: Literal["getCurrentContextResponse"]
    payload: GetCurrentContextResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class JoinUserChannelRequestPayload(BaseModel):
    channelId: str


@register_message_type("joinUserChannel")
class JoinUserChannelRequest(BaseModel):
    type: Literal["joinUserChannel"]
    payload: JoinUserChannelRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class JoinUserChannelResponsePayload(BaseModel):
    channel: Channel


class JoinUserChannelResponse(BaseModel):
    type: Literal["joinUserChannelResponse"]
    payload: JoinUserChannelResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class JoinChannelRequestPayload(BaseModel):
    channelId: str


@register_message_type("joinChannel")
class JoinChannelRequest(BaseModel):
    type: Literal["joinChannel"]
    payload: JoinChannelRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class JoinChannelResponsePayload(BaseModel):
    channel: Channel


class JoinChannelResponse(BaseModel):
    type: Literal["joinChannelResponse"]
    payload: JoinChannelResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class LeaveCurrentChannelRequestPayload(BaseModel):
    pass


@register_message_type("leaveCurrentChannel")
class LeaveCurrentChannelRequest(BaseModel):
    type: Literal["leaveCurrentChannel"]
    payload: LeaveCurrentChannelRequestPayload = Field(
        default_factory=LeaveCurrentChannelRequestPayload
    )
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class LeaveCurrentChannelResponsePayload(BaseModel):
    pass


class LeaveCurrentChannelResponse(BaseModel):
    type: Literal["leaveCurrentChannelResponse"]
    payload: LeaveCurrentChannelResponsePayload = Field(
        default_factory=LeaveCurrentChannelResponsePayload
    )
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# private channel management
class CreatePrivateChannelRequestPayload(BaseModel):
    """Payload for creating a private channel.

    The caller becomes the channel owner and is joined automatically.
    """

    displayMetadata: Optional[DisplayMetadata] = None


@register_message_type("createPrivateChannel")
class CreatePrivateChannelRequest(BaseModel):
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
class CreatePrivateChannelInvitationRequest(BaseModel):
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
class JoinPrivateChannelRequest(BaseModel):
    """Join a private channel using a valid invitation token."""

    type: Literal["joinPrivateChannel"]
    payload: JoinPrivateChannelRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class JoinPrivateChannelResponsePayload(BaseModel):
    channel: Channel


class JoinPrivateChannelResponse(BaseModel):
    type: Literal["joinPrivateChannelResponse"]
    payload: JoinPrivateChannelResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class LeavePrivateChannelRequestPayload(BaseModel):
    """Payload for leaving a private channel."""

    channelId: str


@register_message_type("leavePrivateChannel")
class LeavePrivateChannelRequest(BaseModel):
    """Leave a private channel."""

    type: Literal["leavePrivateChannel"]
    payload: LeavePrivateChannelRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class LeavePrivateChannelResponsePayload(BaseModel):
    pass


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
class PrivateChannelAddEventListenerRequest(BaseModel):
    """Subscribe to private channel lifecycle events."""

    type: Literal["privateChannelAddEventListener"]
    payload: PrivateChannelAddEventListenerRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class PrivateChannelAddEventListenerResponsePayload(BaseModel):
    listenerUuid: ListenerUuid


class PrivateChannelAddEventListenerResponse(BaseModel):
    type: Literal["privateChannelAddEventListenerResponse"]
    payload: PrivateChannelAddEventListenerResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class PrivateChannelDisconnectRequestPayload(BaseModel):
    """Payload to disconnect a private channel session."""

    channelId: str


@register_message_type("privateChannelDisconnect")
class PrivateChannelDisconnectRequest(BaseModel):
    """Disconnect from a private channel and fire lifecycle events."""

    type: Literal["privateChannelDisconnect"]
    payload: PrivateChannelDisconnectRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class PrivateChannelDisconnectResponsePayload(BaseModel):
    pass


class PrivateChannelDisconnectResponse(BaseModel):
    type: Literal["privateChannelDisconnectResponse"]
    payload: PrivateChannelDisconnectResponsePayload = Field(
        default_factory=PrivateChannelDisconnectResponsePayload
    )
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# getInfo
class GetInfoRequestPayload(BaseModel):
    pass


@register_message_type("getInfo")
class GetInfoRequest(BaseModel):
    type: Literal["getInfo"]
    payload: GetInfoRequestPayload = Field(default_factory=GetInfoRequestPayload)
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class GetInfoResponsePayload(BaseModel):
    implementationMetadata: ImplementationMetadata


class GetInfoResponse(BaseModel):
    type: Literal["getInfoResponse"]
    payload: GetInfoResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# getAppMetadata
class GetAppMetadataRequestPayload(BaseModel):
    app: AppIdentifier


@register_message_type("getAppMetadata")
class GetAppMetadataRequest(BaseModel):
    type: Literal["getAppMetadata"]
    payload: GetAppMetadataRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class GetAppMetadataResponsePayload(BaseModel):
    appMetadata: AppMetadata


class GetAppMetadataResponse(BaseModel):
    type: Literal["getAppMetadataResponse"]
    payload: GetAppMetadataResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# intent listeners
class AddIntentListenerRequestPayload(BaseModel):
    intent: str


@register_message_type("addIntentListener")
class AddIntentListenerRequest(BaseModel):
    type: Literal["addIntentListener"]
    payload: AddIntentListenerRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class AddIntentListenerResponsePayload(BaseModel):
    listenerUuid: ListenerUuid


class AddIntentListenerResponse(BaseModel):
    type: Literal["addIntentListenerResponse"]
    payload: AddIntentListenerResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class IntentListenerUnsubscribeRequestPayload(BaseModel):
    listenerUuid: ListenerUuid


@register_message_type("intentListenerUnsubscribe")
class IntentListenerUnsubscribeRequest(BaseModel):
    type: Literal["intentListenerUnsubscribe"]
    payload: IntentListenerUnsubscribeRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class IntentListenerUnsubscribeResponsePayload(BaseModel):
    pass


class IntentListenerUnsubscribeResponse(BaseModel):
    type: Literal["intentListenerUnsubscribeResponse"]
    payload: IntentListenerUnsubscribeResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# findIntent
class FindIntentRequestPayload(BaseModel):
    intent: str
    context: Optional[Fdc3Context] = None
    resultType: Optional[str] = None
    target: Optional["AppIdentifier"] = None


@register_message_type("findIntent")
class FindIntentRequest(BaseModel):
    type: Literal["findIntent"]
    payload: FindIntentRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class FindIntentResponsePayload(BaseModel):
    appIntent: AppIntent


class FindIntentResponse(BaseModel):
    type: Literal["findIntentResponse"]
    payload: FindIntentResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# findIntentsByContext
class FindIntentsByContextRequestPayload(BaseModel):
    context: Fdc3Context
    resultType: Optional[str] = None


@register_message_type("findIntentsByContext")
class FindIntentsByContextRequest(BaseModel):
    type: Literal["findIntentsByContext"]
    payload: FindIntentsByContextRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class FindIntentsByContextResponsePayload(BaseModel):
    appIntents: List[AppIntent]


class FindIntentsByContextResponse(BaseModel):
    type: Literal["findIntentsByContextResponse"]
    payload: FindIntentsByContextResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# findInstances
class FindInstancesRequestPayload(BaseModel):
    app: "AppIdentifier"


@register_message_type("findInstances")
class FindInstancesRequest(BaseModel):
    type: Literal["findInstances"]
    payload: FindInstancesRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class FindInstancesResponsePayload(BaseModel):
    instances: List[AppIdentifier]


class FindInstancesResponse(BaseModel):
    type: Literal["findInstancesResponse"]
    payload: FindInstancesResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# raiseIntent
class RaiseIntentRequestPayload(BaseModel):
    intent: str
    context: Optional[Fdc3Context] = None
    target: Optional[Union["AppIdentifier", str]] = None


@register_message_type("raiseIntent")
class RaiseIntentRequest(BaseModel):
    type: Literal["raiseIntent"]
    payload: RaiseIntentRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class RaiseIntentResponsePayload(BaseModel):
    intentResolution: IntentResolution


class RaiseIntentResponse(BaseModel):
    type: Literal["raiseIntentResponse"]
    payload: RaiseIntentResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# raiseIntentForContext
class RaiseIntentForContextRequestPayload(BaseModel):
    context: Fdc3Context
    resultType: Optional[str] = None
    target: Optional["AppIdentifier"] = None


@register_message_type("raiseIntentForContext")
class RaiseIntentForContextRequest(BaseModel):
    type: Literal["raiseIntentForContext"]
    payload: RaiseIntentForContextRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class RaiseIntentForContextResponsePayload(BaseModel):
    intentResolution: IntentResolution


class RaiseIntentForContextResponse(BaseModel):
    type: Literal["raiseIntentForContextResponse"]
    payload: RaiseIntentForContextResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# intentEvent
class IntentEventPayload(BaseModel):
    intent: str
    context: Optional[Fdc3Context] = None
    originatingApp: Optional["AppIdentifier"] = None


class IntentEvent(BaseModel):
    type: Literal["intentEvent"]
    payload: IntentEventPayload
    meta: AgentEventMeta = Field(default_factory=AgentEventMeta)


# intentResult
class IntentResultRequestPayload(BaseModel):
    intentResult: dict  # IntentResult


@register_message_type("intentResultRequest")
class IntentResultRequest(BaseModel):
    type: Literal["intentResultRequest"]
    payload: IntentResultRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class IntentResultResponsePayload(BaseModel):
    pass


class IntentResultResponse(BaseModel):
    type: Literal["intentResultResponse"]
    payload: IntentResultResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# raiseIntentResultResponse
class RaiseIntentResultResponsePayload(BaseModel):
    pass


@register_message_type("raiseIntentResultResponse")
class RaiseIntentResultResponse(BaseModel):
    type: Literal["raiseIntentResultResponse"]
    payload: RaiseIntentResultResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)
