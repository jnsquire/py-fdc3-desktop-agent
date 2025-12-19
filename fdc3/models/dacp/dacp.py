"""DACP Pydantic models (migrated from fdc3.desktop_agent.protocol.dacp.dacp).

This file is a straight relocation of the original DACP models and should
remain functionally equivalent.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal, Union, List
from fdc3.models.identifiers import AppIdentifier
from fdc3.models.identifiers import AppIntent
from fdc3.models.identifiers import IntentResolution
from fdc3.models.identifiers import Channel
from fdc3.models.primitives import (
    RequestUuid,
    ResponseUuid,
    EventUuid,
    Timestamp,
    ListenerUuid,
)

# DACP Envelopes


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


class HeartbeatAcknowledgmentRequest(BaseModel):
    type: Literal["heartbeatAcknowledgmentRequest"]
    payload: HeartbeatAcknowledgmentRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


# Now, specific request/response types for the key messages


# open
class OpenRequestPayload(BaseModel):
    app: "AppIdentifier"
    context: Optional[dict] = None  # Context data


class OpenRequest(BaseModel):
    type: Literal["open"]
    payload: OpenRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class OpenResponsePayload(BaseModel):
    pass  # Success or error - error handled at envelope level


class OpenResponse(BaseModel):
    type: Literal["openResponse"]
    payload: OpenResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# broadcast
class BroadcastRequestPayload(BaseModel):
    context: dict  # Context data


class BroadcastRequest(BaseModel):
    type: Literal["broadcast"]
    payload: BroadcastRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class BroadcastEventPayload(BaseModel):
    context: dict


class BroadcastEvent(BaseModel):
    type: Literal["broadcastEvent"]
    payload: BroadcastEventPayload
    meta: AgentEventMeta = Field(default_factory=AgentEventMeta)


# context listeners
class AddContextListenerRequestPayload(BaseModel):
    contextType: Optional[str] = None


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


# user channel membership APIs
class GetUserChannelsRequestPayload(BaseModel):
    pass


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


class GetCurrentChannelRequestPayload(BaseModel):
    pass


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


class JoinUserChannelRequestPayload(BaseModel):
    channelId: str


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


class LeaveCurrentChannelRequestPayload(BaseModel):
    pass


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


# intent listeners
class AddIntentListenerRequestPayload(BaseModel):
    intent: str


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
    context: Optional[dict] = None
    target: Optional["AppIdentifier"] = None


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
    context: dict


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
    context: Optional[dict] = None
    target: Optional["AppIdentifier"] = None


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
    context: dict
    target: Optional["AppIdentifier"] = None


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
    context: Optional[dict] = None
    originatingApp: Optional["AppIdentifier"] = None


class IntentEvent(BaseModel):
    type: Literal["intentEvent"]
    payload: IntentEventPayload
    meta: AgentEventMeta = Field(default_factory=AgentEventMeta)


# intentResult
class IntentResultRequestPayload(BaseModel):
    intentResult: dict  # IntentResult


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


class RaiseIntentResultResponse(BaseModel):
    type: Literal["raiseIntentResultResponse"]
    payload: RaiseIntentResultResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)
