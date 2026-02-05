"""DACP Event Listener Models."""

from pydantic import BaseModel, Field
from typing import Literal
from .envelopes import (
    DacpMessage,
    AppRequestMeta,
    AgentResponseMeta,
    AgentEventMeta,
    register_message_type,
)
from fdc3.models.identifiers import FDC3Event
from fdc3.models.primitives import ListenerUuid


# DesktopAgent event listeners
class AddEventListenerRequestPayload(BaseModel):
    eventType: str


@register_message_type("addEventListener")
class AddEventListenerRequest(DacpMessage):
    type: Literal["addEventListener"]
    payload: AddEventListenerRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class AddEventListenerResponsePayload(BaseModel):
    listenerUuid: ListenerUuid


# Contains a `listenerUuid` used to resolve pending listeners; handled
# via the generic `AgentResponse` envelope and pending-response logic.
class AddEventListenerResponse(BaseModel):
    type: Literal["addEventListenerResponse"]
    payload: AddEventListenerResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class RemoveEventListenerRequestPayload(BaseModel):
    listenerUuid: ListenerUuid


@register_message_type("removeEventListener")
class RemoveEventListenerRequest(DacpMessage):
    type: Literal["removeEventListener"]
    payload: RemoveEventListenerRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class RemoveEventListenerResponsePayload(BaseModel):
    pass


# Simple acknowledgement/empty payload — parsed via the generic
# `AgentResponse` envelope rather than being registered separately.
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
