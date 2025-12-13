from pydantic import BaseModel, Field
from typing import Optional, Literal, Union
from ...api import RequestUuid, ResponseUuid, EventUuid, Timestamp, AppIdentifier, ListenerUuid

# DACP Envelopes

class AppRequestMeta(BaseModel):
    requestUuid: RequestUuid
    timestamp: Timestamp = Field(default_factory=Timestamp)
    source: Optional[AppIdentifier] = None

class AppRequest(BaseModel):
    type: str
    payload: dict  # The specific payload depends on the type
    meta: AppRequestMeta

class AgentResponseMeta(BaseModel):
    requestUuid: RequestUuid
    responseUuid: ResponseUuid = Field(default_factory=ResponseUuid)
    timestamp: Timestamp = Field(default_factory=Timestamp)

class AgentResponse(BaseModel):
    type: str
    payload: Union[dict, "ErrorResponsePayload"]  # Or specific error payload
    meta: AgentResponseMeta

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
    meta: AgentEventMeta

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
    meta: AppRequestMeta

# Now, specific request/response types for the key messages

# open
class OpenRequestPayload(BaseModel):
    app: AppIdentifier
    context: Optional[dict] = None  # Context data

class OpenRequest(BaseModel):
    type: Literal["open"]
    payload: OpenRequestPayload
    meta: AppRequestMeta

class OpenResponsePayload(BaseModel):
    pass  # Success or error - error handled at envelope level

class OpenResponse(BaseModel):
    type: Literal["openResponse"]
    payload: OpenResponsePayload
    meta: AgentResponseMeta

# broadcast
class BroadcastRequestPayload(BaseModel):
    context: dict  # Context data

class BroadcastRequest(BaseModel):
    type: Literal["broadcast"]
    payload: BroadcastRequestPayload
    meta: AppRequestMeta

class BroadcastEventPayload(BaseModel):
    context: dict

class BroadcastEvent(BaseModel):
    type: Literal["broadcastEvent"]
    payload: BroadcastEventPayload
    meta: AgentEventMeta

# context listeners
class AddContextListenerRequestPayload(BaseModel):
    contextType: Optional[str] = None

class AddContextListenerRequest(BaseModel):
    type: Literal["addContextListener"]
    payload: AddContextListenerRequestPayload
    meta: AppRequestMeta

class AddContextListenerResponsePayload(BaseModel):
    listenerUuid: ListenerUuid

class AddContextListenerResponse(BaseModel):
    type: Literal["addContextListenerResponse"]
    payload: AddContextListenerResponsePayload
    meta: AgentResponseMeta

class ContextListenerUnsubscribeRequestPayload(BaseModel):
    listenerUuid: ListenerUuid

class ContextListenerUnsubscribeRequest(BaseModel):
    type: Literal["contextListenerUnsubscribe"]
    payload: ContextListenerUnsubscribeRequestPayload
    meta: AppRequestMeta

class ContextListenerUnsubscribeResponsePayload(BaseModel):
    pass

class ContextListenerUnsubscribeResponse(BaseModel):
    type: Literal["contextListenerUnsubscribeResponse"]
    payload: ContextListenerUnsubscribeResponsePayload
    meta: AgentResponseMeta

# intent listeners
class AddIntentListenerRequestPayload(BaseModel):
    intent: str

class AddIntentListenerRequest(BaseModel):
    type: Literal["addIntentListener"]
    payload: AddIntentListenerRequestPayload
    meta: AppRequestMeta

class AddIntentListenerResponsePayload(BaseModel):
    listenerUuid: ListenerUuid

class AddIntentListenerResponse(BaseModel):
    type: Literal["addIntentListenerResponse"]
    payload: AddIntentListenerResponsePayload
    meta: AgentResponseMeta

class IntentListenerUnsubscribeRequestPayload(BaseModel):
    listenerUuid: ListenerUuid

class IntentListenerUnsubscribeRequest(BaseModel):
    type: Literal["intentListenerUnsubscribe"]
    payload: IntentListenerUnsubscribeRequestPayload
    meta: AppRequestMeta

class IntentListenerUnsubscribeResponsePayload(BaseModel):
    pass

class IntentListenerUnsubscribeResponse(BaseModel):
    type: Literal["intentListenerUnsubscribeResponse"]
    payload: IntentListenerUnsubscribeResponsePayload
    meta: AgentResponseMeta

# raiseIntent
class RaiseIntentRequestPayload(BaseModel):
    intent: str
    context: Optional[dict] = None
    target: Optional[AppIdentifier] = None

class RaiseIntentRequest(BaseModel):
    type: Literal["raiseIntent"]
    payload: RaiseIntentRequestPayload
    meta: AppRequestMeta

class RaiseIntentResponsePayload(BaseModel):
    intentResolution: dict  # IntentResolution

class RaiseIntentResponse(BaseModel):
    type: Literal["raiseIntentResponse"]
    payload: RaiseIntentResponsePayload
    meta: AgentResponseMeta

# raiseIntentForContext
class RaiseIntentForContextRequestPayload(BaseModel):
    context: dict
    target: Optional[AppIdentifier] = None

class RaiseIntentForContextRequest(BaseModel):
    type: Literal["raiseIntentForContext"]
    payload: RaiseIntentForContextRequestPayload
    meta: AppRequestMeta

class RaiseIntentForContextResponsePayload(BaseModel):
    intentResolution: dict

class RaiseIntentForContextResponse(BaseModel):
    type: Literal["raiseIntentForContextResponse"]
    payload: RaiseIntentForContextResponsePayload
    meta: AgentResponseMeta

# intentEvent
class IntentEventPayload(BaseModel):
    intent: str
    context: Optional[dict] = None
    originatingApp: Optional[AppIdentifier] = None

class IntentEvent(BaseModel):
    type: Literal["intentEvent"]
    payload: IntentEventPayload
    meta: AgentEventMeta

# intentResult
class IntentResultRequestPayload(BaseModel):
    intentResult: dict  # IntentResult

class IntentResultRequest(BaseModel):
    type: Literal["intentResultRequest"]
    payload: IntentResultRequestPayload
    meta: AppRequestMeta

class IntentResultResponsePayload(BaseModel):
    pass

class IntentResultResponse(BaseModel):
    type: Literal["intentResultResponse"]
    payload: IntentResultResponsePayload
    meta: AgentResponseMeta

# raiseIntentResultResponse
class RaiseIntentResultResponsePayload(BaseModel):
    pass

class RaiseIntentResultResponse(BaseModel):
    type: Literal["raiseIntentResultResponse"]
    payload: RaiseIntentResultResponsePayload
    meta: AgentResponseMeta