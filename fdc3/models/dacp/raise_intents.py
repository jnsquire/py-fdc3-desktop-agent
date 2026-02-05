"""DACP Raise Intent Models."""

from pydantic import BaseModel, Field
from typing import Literal, Optional, Union
from .envelopes import (
    DacpMessage,
    AppRequestMeta,
    AgentResponseMeta,
    AgentEventMeta,
    register_message_type,
    Fdc3Context,
)
from fdc3.models.identifiers import AppIdentifier, IntentResolution


# raiseIntent
class RaiseIntentRequestPayload(BaseModel):
    intent: str
    context: Optional["Fdc3Context"] = None
    target: Optional[Union["AppIdentifier", str]] = None


@register_message_type("raiseIntent")
class RaiseIntentRequest(DacpMessage):
    type: Literal["raiseIntent"]
    payload: RaiseIntentRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class RaiseIntentResponsePayload(BaseModel):
    intentResolution: IntentResolution


# Contains `IntentResolution` from the agent; parsed via the generic
# `AgentResponse` envelope to centralize result handling.
class RaiseIntentResponse(BaseModel):
    type: Literal["raiseIntentResponse"]
    payload: RaiseIntentResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# raiseIntentForContext
class RaiseIntentForContextRequestPayload(BaseModel):
    context: "Fdc3Context"
    resultType: Optional[str] = None
    target: Optional["AppIdentifier"] = None


@register_message_type("raiseIntentForContext")
class RaiseIntentForContextRequest(DacpMessage):
    type: Literal["raiseIntentForContext"]
    payload: RaiseIntentForContextRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class RaiseIntentForContextResponsePayload(BaseModel):
    intentResolution: IntentResolution


# Contains `IntentResolution` for context-based raises; parsed via the
# generic `AgentResponse` envelope to centralize result handling.
class RaiseIntentForContextResponse(BaseModel):
    type: Literal["raiseIntentForContextResponse"]
    payload: RaiseIntentForContextResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# intentEvent
class IntentEventPayload(BaseModel):
    intent: str
    context: Optional["Fdc3Context"] = None
    originatingApp: Optional["AppIdentifier"] = None


@register_message_type("intentEvent")
class IntentEvent(BaseModel):
    type: Literal["intentEvent"]
    payload: IntentEventPayload
    meta: AgentEventMeta = Field(default_factory=AgentEventMeta)


# intentResult
class IntentResultRequestPayload(BaseModel):
    intentResult: dict  # IntentResult


@register_message_type("intentResultRequest")
class IntentResultRequest(DacpMessage):
    type: Literal["intentResultRequest"]
    payload: IntentResultRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class IntentResultResponsePayload(BaseModel):
    pass


# Simple intent-result acknowledgement (empty payload); parsed via the
# generic `AgentResponse` envelope to keep response handling uniform.
class IntentResultResponse(BaseModel):
    type: Literal["intentResultResponse"]
    payload: IntentResultResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# raiseIntentResultResponse
class RaiseIntentResultResponsePayload(BaseModel):
    pass


@register_message_type("raiseIntentResultResponse")
class RaiseIntentResultResponse(DacpMessage):
    type: Literal["raiseIntentResultResponse"]
    payload: RaiseIntentResultResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# Rebuild models with forward references
RaiseIntentRequest.model_rebuild()
RaiseIntentResponse.model_rebuild()
RaiseIntentForContextRequest.model_rebuild()
RaiseIntentForContextResponse.model_rebuild()
IntentEvent.model_rebuild()
IntentResultRequest.model_rebuild()
IntentResultResponse.model_rebuild()
RaiseIntentResultResponse.model_rebuild()
