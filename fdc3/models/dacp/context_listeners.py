"""DACP Context Listener Models."""

from pydantic import BaseModel, Field
from typing import Literal, Optional
from .envelopes import (
    DacpMessage,
    AppRequestMeta,
    AgentResponseMeta,
    register_message_type,
)
from fdc3.models.primitives import ListenerUuid


# context listeners
class AddContextListenerRequestPayload(BaseModel):
    contextType: Optional[str] = None
    channelId: Optional[str] = None


@register_message_type("addContextListener")
class AddContextListenerRequest(DacpMessage):
    type: Literal["addContextListener"]
    payload: AddContextListenerRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class AddContextListenerResponsePayload(BaseModel):
    listenerUuid: ListenerUuid


@register_message_type("addContextListenerResponse")
class AddContextListenerResponse(BaseModel):
    type: Literal["addContextListenerResponse"]
    payload: AddContextListenerResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class ContextListenerUnsubscribeRequestPayload(BaseModel):
    listenerUuid: ListenerUuid


@register_message_type("contextListenerUnsubscribe")
class ContextListenerUnsubscribeRequest(DacpMessage):
    type: Literal["contextListenerUnsubscribe"]
    payload: ContextListenerUnsubscribeRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class ContextListenerUnsubscribeResponsePayload(BaseModel):
    pass


@register_message_type("contextListenerUnsubscribeResponse")
class ContextListenerUnsubscribeResponse(BaseModel):
    type: Literal["contextListenerUnsubscribeResponse"]
    payload: ContextListenerUnsubscribeResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)
