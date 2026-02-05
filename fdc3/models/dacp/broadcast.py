"""DACP Broadcast Models."""

from pydantic import BaseModel, Field
from typing import Literal, Optional
from .envelopes import (
    DacpMessage,
    AppRequestMeta,
    AgentEventMeta,
    register_message_type,
    Fdc3Context,
)


# broadcast
class BroadcastRequestPayload(BaseModel):
    context: "Fdc3Context"  # Context data
    channelId: Optional[str] = None  # Optional channel override (used by bridge)


@register_message_type("broadcast")
class BroadcastRequest(DacpMessage):
    type: Literal["broadcast"]
    payload: BroadcastRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class BroadcastEventPayload(BaseModel):
    context: "Fdc3Context"


@register_message_type("broadcastEvent")
class BroadcastEvent(BaseModel):
    type: Literal["broadcastEvent"]
    payload: BroadcastEventPayload
    meta: AgentEventMeta = Field(default_factory=AgentEventMeta)


# Rebuild models with forward references
BroadcastRequest.model_rebuild()
BroadcastEvent.model_rebuild()
