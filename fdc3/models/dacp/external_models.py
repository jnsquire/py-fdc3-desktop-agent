"""External handler protocol Pydantic models (migrated)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .envelopes import (
    AgentResponseMeta,
    AppRequestMeta,
    DacpMessage,
    Fdc3Context,
    register_message_type,
)
from ..identifiers import AppIdentifier


# --- Incoming messages (from external handlers) ---


class RegisterExternalHandlerPayload(BaseModel):
    """Payload for registering an external intent handler."""

    handler_id: str = Field(..., min_length=1, description="Unique handler identifier")
    intents: list[str] = Field(
        ..., min_length=1, description="List of intent names to handle"
    )
    priority: int = Field(
        default=0, description="Handler priority (higher = preferred)"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Optional metadata"
    )

    @field_validator("intents")
    @classmethod
    def validate_intents(cls, v: list[str]) -> list[str]:
        if not all(isinstance(i, str) and i for i in v):
            raise ValueError("intents must be a non-empty list of non-empty strings")
        return v


@register_message_type("registerExternalHandler")
class RegisterExternalHandlerRequest(DacpMessage):
    """Request to register an external intent handler."""

    type: Literal["registerExternalHandler"] = "registerExternalHandler"
    payload: RegisterExternalHandlerPayload
    meta: AppRequestMeta


class UnregisterExternalHandlerPayload(BaseModel):
    """Payload for unregistering an external intent handler."""

    handler_uuid: str = Field(
        ..., min_length=1, description="Handler UUID to unregister"
    )


@register_message_type("unregisterExternalHandler")
class UnregisterExternalHandlerRequest(DacpMessage):
    """Request to unregister an external intent handler."""

    type: Literal["unregisterExternalHandler"] = "unregisterExternalHandler"
    payload: UnregisterExternalHandlerPayload
    meta: AppRequestMeta


class ExternalIntentResultPayload(BaseModel):
    """Payload for an intent result from an external handler."""

    request_uuid: str = Field(
        ..., min_length=1, description="Correlation UUID from forwarded intent"
    )
    result: dict[str, Any] | None = Field(
        default=None, description="Intent result data"
    )
    error: str | None = Field(
        default=None, description="Error message if intent failed"
    )


@register_message_type("intentResult")
class ExternalIntentResultRequest(DacpMessage):
    """Intent result message from an external handler."""

    type: Literal["intentResult"] = "intentResult"
    payload: ExternalIntentResultPayload
    # External handlers may not send full meta; make it optional
    meta: dict[str, Any] | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.payload.result is None and self.payload.error is None:
            raise ValueError("Either result or error must be present in intentResult")


# --- Outgoing messages (to external handlers) ---


class ForwardedIntentPayload(BaseModel):
    """Payload for a forwarded intent sent to an external handler."""

    request_uuid: str = Field(..., description="Correlation UUID for response matching")
    intent: str = Field(..., description="The intent name being raised")
    context: Fdc3Context = Field(..., description="Intent context data")
    source: AppIdentifier | None = Field(None, description="Source app identifier")
    timeout: int | None = Field(default=None, description="Optional timeout in seconds")


@register_message_type("forwardedIntent")
class ForwardedIntentMessage(BaseModel):
    """Message sent to external handler when forwarding an intent."""

    type: Literal["forwardedIntent"] = "forwardedIntent"
    payload: ForwardedIntentPayload


class RegisterExternalHandlerResponsePayload(BaseModel):
    """Payload for registration response."""

    handler_uuid: str = Field(
        ..., description="Assigned UUID for the registered handler"
    )


@register_message_type("registerExternalHandlerResponse")
class RegisterExternalHandlerResponse(BaseModel):
    """Response sent after successfully registering an external handler."""

    type: Literal["registerExternalHandlerResponse"] = "registerExternalHandlerResponse"
    payload: RegisterExternalHandlerResponsePayload
    meta: AgentResponseMeta


class UnregisterExternalHandlerResponsePayload(BaseModel):
    """Payload for unregistration response."""

    pass


@register_message_type("unregisterExternalHandlerResponse")
class UnregisterExternalHandlerResponse(BaseModel):
    """Response sent after unregistering an external handler."""

    type: Literal["unregisterExternalHandlerResponse"] = (
        "unregisterExternalHandlerResponse"
    )
    payload: UnregisterExternalHandlerResponsePayload = Field(
        default_factory=UnregisterExternalHandlerResponsePayload
    )
    meta: AgentResponseMeta
