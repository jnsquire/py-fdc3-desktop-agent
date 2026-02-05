"""DACP Heartbeat Models."""

from pydantic import BaseModel, Field
from typing import Literal
from .envelopes import (
    DacpMessage,
    AppRequestMeta,
    AgentEventMeta,
    register_message_type,
)
from fdc3.models.primitives import EventUuid


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
class HeartbeatAcknowledgmentRequest(DacpMessage):
    type: Literal["heartbeatAcknowledgmentRequest"]
    payload: HeartbeatAcknowledgmentRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)
