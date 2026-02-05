"""DACP Open Models."""

from pydantic import BaseModel, Field
from typing import Literal, Optional, Union
from .envelopes import (
    DacpMessage,
    AppRequestMeta,
    AgentResponseMeta,
    register_message_type,
    Fdc3Context,
)
from fdc3.models.identifiers import AppIdentifier


# open
class OpenRequestPayload(BaseModel):
    app: Union["AppIdentifier", str]
    context: Optional["Fdc3Context"] = None  # Context data


@register_message_type("open")
class OpenRequest(DacpMessage):
    type: Literal["open"]
    payload: OpenRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class OpenResponsePayload(BaseModel):
    appIdentifier: Optional[AppIdentifier] = None


# Agent open responses can vary by implementation; parse via the
# generic `AgentResponse` envelope to avoid strict validation.
class OpenResponse(BaseModel):
    type: Literal["openResponse"]
    payload: OpenResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# Rebuild models with forward references
OpenRequest.model_rebuild()
