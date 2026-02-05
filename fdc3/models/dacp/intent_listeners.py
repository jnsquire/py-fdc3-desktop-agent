"""DACP Intent Listener Models."""

from pydantic import BaseModel, Field
from typing import Literal
from .envelopes import (
    DacpMessage,
    AppRequestMeta,
    AgentResponseMeta,
    register_message_type,
)
from fdc3.models.primitives import ListenerUuid


# intent listeners
class AddIntentListenerRequestPayload(BaseModel):
    intent: str


@register_message_type("addIntentListener")
class AddIntentListenerRequest(DacpMessage):
    type: Literal["addIntentListener"]
    payload: AddIntentListenerRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class AddIntentListenerResponsePayload(BaseModel):
    listenerUuid: ListenerUuid


@register_message_type("addIntentListenerResponse")
class AddIntentListenerResponse(BaseModel):
    type: Literal["addIntentListenerResponse"]
    payload: AddIntentListenerResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class IntentListenerUnsubscribeRequestPayload(BaseModel):
    listenerUuid: ListenerUuid


@register_message_type("intentListenerUnsubscribe")
class IntentListenerUnsubscribeRequest(DacpMessage):
    type: Literal["intentListenerUnsubscribe"]
    payload: IntentListenerUnsubscribeRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class IntentListenerUnsubscribeResponsePayload(BaseModel):
    pass


@register_message_type("intentListenerUnsubscribeResponse")
class IntentListenerUnsubscribeResponse(BaseModel):
    type: Literal["intentListenerUnsubscribeResponse"]
    payload: IntentListenerUnsubscribeResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)
