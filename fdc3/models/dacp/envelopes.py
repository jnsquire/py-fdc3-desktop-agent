"""DACP Envelopes and Base Classes."""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, Union, Any, TypeAlias, ClassVar
from fdc3.models.identifiers import AppIdentifier
from fdc3.models.context_types import ContextBase
from fdc3.models.primitives import (
    RequestUuid,
    ResponseUuid,
    EventUuid,
    Timestamp,
)

Fdc3Context: TypeAlias = ContextBase

# Global registry for message types
MESSAGE_TYPE_MAP: dict[str, "DacpMessageType"] = {}


class DacpMessage(BaseModel):
    """Base class for DACP messages parsed by message_parser."""

    MESSAGE_TYPE_MAP: ClassVar[dict[str, "DacpMessageType"]] = MESSAGE_TYPE_MAP

    pass


DacpMessageType: TypeAlias = type[DacpMessage]


def register_message_type(message_type: str):
    def decorator(cls: DacpMessageType) -> DacpMessageType:
        MESSAGE_TYPE_MAP[message_type] = cls
        return cls

    return decorator


class AppRequestMeta(BaseModel):
    requestUuid: RequestUuid = Field(default_factory=RequestUuid)
    timestamp: Timestamp = Field(default_factory=Timestamp)
    source: Optional["AppIdentifier"] = None


class AppRequest(BaseModel):
    type: str
    payload: dict  # The specific payload depends on the type
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class AgentResponseMeta(BaseModel):
    requestUuid: RequestUuid = Field(default_factory=RequestUuid)
    responseUuid: ResponseUuid = Field(default_factory=ResponseUuid)
    timestamp: Timestamp = Field(default_factory=Timestamp)
    errorSources: Optional[Any] = None
    errorDetails: Optional[Any] = None

    @field_validator("requestUuid", mode="before")
    @classmethod
    def _coerce_request_uuid(cls, v):
        # Accept either a string or an object with `root` (RootModel)
        if isinstance(v, str):
            return RequestUuid(root=v)
        if hasattr(v, "root"):
            return RequestUuid(root=getattr(v, "root"))
        return v


class AgentResponse(BaseModel):
    # NOTE: Concrete response classes (e.g. `openResponse`,
    # `getAppMetadataResponse`, etc.) are intentionally NOT registered in
    # `MESSAGE_TYPE_MAP`. We register request/event message types that need
    # direct parsing. Responses are parsed via this generic `AgentResponse`
    # envelope instead to centralize error handling and avoid over-eager
    # Pydantic validation of agent-generated responses leaking into callers.
    type: str
    payload: Union[dict, "ErrorResponsePayload"]  # Or specific error payload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


class ErrorResponsePayload(BaseModel):
    error: str  # Error enum value as string


class AgentEventMeta(BaseModel):
    eventUuid: EventUuid = Field(default_factory=EventUuid)
    timestamp: Timestamp = Field(default_factory=Timestamp)


class AgentEventPayload(BaseModel):
    eventType: str
    instanceUuid: str


class AgentEvent(BaseModel):
    type: str
    payload: AgentEventPayload
    meta: AgentEventMeta = Field(default_factory=AgentEventMeta)
