"""DACP Private Channel Event Models."""

from pydantic import BaseModel, Field
from typing import Literal, Optional, Any, Dict
from .envelopes import AgentEventMeta, register_message_type
from .enums import PrivateChannelEventListenerTypes


class PrivateChannelEventPayload(BaseModel):
    channelId: str
    eventType: PrivateChannelEventListenerTypes
    details: Optional[Dict[str, Any]] = None


@register_message_type("privateChannelEvent")
class PrivateChannelEvent(BaseModel):
    type: Literal["privateChannelEvent"]
    payload: PrivateChannelEventPayload
    meta: AgentEventMeta = Field(default_factory=AgentEventMeta)
