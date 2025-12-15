"""Pydantic models for external handler protocol messages.

These models provide runtime validation for messages sent by external
intent handlers (register, unregister, intentResult) and for messages
sent to external handlers (forwardedIntent).
"""

from __future__ import annotations

from typing import Optional, Any, Literal
from pydantic import BaseModel, Field, field_validator

from .dacp import AppRequestMeta


# --- Outgoing messages (to external handlers) ---


class ForwardedIntentPayload(BaseModel):
    """Payload for a forwarded intent sent to an external handler."""

    request_uuid: str = Field(..., description="Correlation UUID for response matching")
    intent: str = Field(..., description="The intent name being raised")
    context: dict[str, Any] = Field(
        default_factory=dict, description="Intent context data"
    )
    source: dict[str, Any] = Field(
        default_factory=dict, description="Source app identifier"
    )
    timeout: Optional[int] = Field(
        default=None, description="Optional timeout in seconds"
    )


class ForwardedIntentMessage(BaseModel):
    """Message sent to external handler when forwarding an intent."""

    type: Literal["forwardedIntent"] = "forwardedIntent"
    payload: ForwardedIntentPayload


class RegisterExternalHandlerResponsePayload(BaseModel):
    """Payload for registration response."""

    handler_uuid: str = Field(
        ..., description="Assigned UUID for the registered handler"
    )


class RegisterExternalHandlerResponseMeta(BaseModel):
    """Meta for registration response - includes requestUuid for correlation."""

    requestUuid: str = Field(..., description="Original request UUID for correlation")


class RegisterExternalHandlerResponse(BaseModel):
    """Response sent after successfully registering an external handler."""

    type: Literal["registerExternalHandlerResponse"] = "registerExternalHandlerResponse"
    payload: RegisterExternalHandlerResponsePayload
    meta: RegisterExternalHandlerResponseMeta


class UnregisterExternalHandlerResponsePayload(BaseModel):
    """Payload for unregistration response."""

    pass  # Empty on success


class UnregisterExternalHandlerResponse(BaseModel):
    """Response sent after unregistering an external handler."""

    type: Literal["unregisterExternalHandlerResponse"] = (
        "unregisterExternalHandlerResponse"
    )
    payload: UnregisterExternalHandlerResponsePayload = Field(
        default_factory=UnregisterExternalHandlerResponsePayload
    )
    meta: RegisterExternalHandlerResponseMeta  # Reuse same meta structure


class IntentResultMessagePayload(BaseModel):
    """Payload for intent result message (client-side use)."""

    request_uuid: str = Field(..., description="Correlation UUID from forwarded intent")
    result: Optional[dict[str, Any]] = Field(
        default=None, description="Intent result data"
    )
    error: Optional[str] = Field(
        default=None, description="Error message if intent failed"
    )


class IntentResultMessage(BaseModel):
    """Intent result message sent by external handler back to agent."""

    type: Literal["intentResult"] = "intentResult"
    payload: IntentResultMessagePayload


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


class RegisterExternalHandlerRequest(BaseModel):
    """Request to register an external intent handler."""

    type: Literal["registerExternalHandler"] = "registerExternalHandler"
    payload: RegisterExternalHandlerPayload
    meta: AppRequestMeta


class UnregisterExternalHandlerPayload(BaseModel):
    """Payload for unregistering an external intent handler."""

    handler_uuid: str = Field(
        ..., min_length=1, description="Handler UUID to unregister"
    )


class UnregisterExternalHandlerRequest(BaseModel):
    """Request to unregister an external intent handler."""

    type: Literal["unregisterExternalHandler"] = "unregisterExternalHandler"
    payload: UnregisterExternalHandlerPayload
    meta: AppRequestMeta


class ExternalIntentResultPayload(BaseModel):
    """Payload for an intent result from an external handler."""

    request_uuid: str = Field(
        ..., min_length=1, description="Correlation UUID from forwarded intent"
    )
    result: Optional[dict[str, Any]] = Field(
        default=None, description="Intent result data"
    )
    error: Optional[str] = Field(
        default=None, description="Error message if intent failed"
    )

    @field_validator("error", mode="before")
    @classmethod
    def validate_result_or_error(cls, v: Optional[str], info) -> Optional[str]:
        # At least one of result or error should be present (validated at model level)
        return v


class ExternalIntentResultRequest(BaseModel):
    """Intent result message from an external handler."""

    type: Literal["intentResult"] = "intentResult"
    payload: ExternalIntentResultPayload
    # External handlers may not send full meta; make it optional
    meta: Optional[dict[str, Any]] = None

    def model_post_init(self, __context: Any) -> None:
        """Validate that either result or error is present."""
        if self.payload.result is None and self.payload.error is None:
            raise ValueError("Either result or error must be present in intentResult")
