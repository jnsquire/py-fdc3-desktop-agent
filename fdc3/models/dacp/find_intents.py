"""DACP Find Intent Models."""

from pydantic import BaseModel, Field
from typing import Literal, Optional, List
from .envelopes import (
    DacpMessage,
    AppRequestMeta,
    AgentResponseMeta,
    register_message_type,
    Fdc3Context,
)
from fdc3.models.identifiers import AppIdentifier, AppIntent


# findIntent
class FindIntentRequestPayload(BaseModel):
    intent: str
    context: Optional["Fdc3Context"] = None
    resultType: Optional[str] = None
    target: Optional["AppIdentifier"] = None


@register_message_type("findIntent")
class FindIntentRequest(DacpMessage):
    type: Literal["findIntent"]
    payload: FindIntentRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class FindIntentResponsePayload(BaseModel):
    appIntent: AppIntent


# Contains nested `AppIntent` data; parsed via the generic
# `AgentResponse` envelope to avoid duplicate type registration.
class FindIntentResponse(BaseModel):
    type: Literal["findIntentResponse"]
    payload: FindIntentResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# findIntentsByContext
class FindIntentsByContextRequestPayload(BaseModel):
    context: "Fdc3Context"
    resultType: Optional[str] = None


@register_message_type("findIntentsByContext")
class FindIntentsByContextRequest(DacpMessage):
    type: Literal["findIntentsByContext"]
    payload: FindIntentsByContextRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class FindIntentsByContextResponsePayload(BaseModel):
    appIntents: List[AppIntent]


# Returns a list of `AppIntent` entries from the agent; parsed via the
# generic `AgentResponse` envelope to accept implementation-specific items.
class FindIntentsByContextResponse(BaseModel):
    type: Literal["findIntentsByContextResponse"]
    payload: FindIntentsByContextResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# findInstances
class FindInstancesRequestPayload(BaseModel):
    app: "AppIdentifier"


@register_message_type("findInstances")
class FindInstancesRequest(DacpMessage):
    type: Literal["findInstances"]
    payload: FindInstancesRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class FindInstancesResponsePayload(BaseModel):
    instances: List[AppIdentifier]


# Returns `AppIdentifier` instances from the agent; parsed via the
# generic `AgentResponse` envelope to allow implementation variations.
class FindInstancesResponse(BaseModel):
    type: Literal["findInstancesResponse"]
    payload: FindInstancesResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# Rebuild models with forward references
FindIntentRequest.model_rebuild()
FindIntentResponse.model_rebuild()
FindIntentsByContextRequest.model_rebuild()
FindIntentsByContextResponse.model_rebuild()
FindInstancesRequest.model_rebuild()
FindInstancesResponse.model_rebuild()
