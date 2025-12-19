"""Message parser relocated into `fdc3.models.dacp`."""

from __future__ import annotations

from typing import Dict, Any, Union, cast
from pydantic import BaseModel, ValidationError
import logging

from .dacp import (
    OpenRequest,
    BroadcastRequest,
    AddContextListenerRequest,
    AddIntentListenerRequest,
    IntentListenerUnsubscribeRequest,
    GetUserChannelsRequest,
    GetCurrentChannelRequest,
    JoinUserChannelRequest,
    LeaveCurrentChannelRequest,
    FindIntentRequest,
    FindIntentsByContextRequest,
    FindInstancesRequest,
    RaiseIntentRequest,
    RaiseIntentForContextRequest,
    IntentResultRequest,
    RaiseIntentResultResponse,
    ContextListenerUnsubscribeRequest,
    HeartbeatAcknowledgmentRequest,
)
from .external_models import (
    RegisterExternalHandlerRequest,
    UnregisterExternalHandlerRequest,
    ExternalIntentResultRequest,
)

logger = logging.getLogger(__name__)

# Type alias for all valid parsed message types
ParsedMessage = Union[
    OpenRequest,
    BroadcastRequest,
    AddContextListenerRequest,
    AddIntentListenerRequest,
    IntentListenerUnsubscribeRequest,
    GetUserChannelsRequest,
    GetCurrentChannelRequest,
    JoinUserChannelRequest,
    LeaveCurrentChannelRequest,
    FindIntentRequest,
    FindIntentsByContextRequest,
    FindInstancesRequest,
    RaiseIntentRequest,
    RaiseIntentForContextRequest,
    IntentResultRequest,
    RaiseIntentResultResponse,
    ContextListenerUnsubscribeRequest,
    HeartbeatAcknowledgmentRequest,
    RegisterExternalHandlerRequest,
    UnregisterExternalHandlerRequest,
    ExternalIntentResultRequest,
]

# Mapping from message type string to Pydantic model class
MESSAGE_TYPE_MAP: Dict[str, type[BaseModel]] = {
    "open": OpenRequest,
    "broadcast": BroadcastRequest,
    "addContextListener": AddContextListenerRequest,
    "addIntentListener": AddIntentListenerRequest,
    "intentListenerUnsubscribe": IntentListenerUnsubscribeRequest,
    "getUserChannels": GetUserChannelsRequest,
    "getCurrentChannel": GetCurrentChannelRequest,
    "joinUserChannel": JoinUserChannelRequest,
    "leaveCurrentChannel": LeaveCurrentChannelRequest,
    "findIntent": FindIntentRequest,
    "findIntentsByContext": FindIntentsByContextRequest,
    "findInstances": FindInstancesRequest,
    "raiseIntent": RaiseIntentRequest,
    "raiseIntentForContext": RaiseIntentForContextRequest,
    "intentResultRequest": IntentResultRequest,
    "raiseIntentResultResponse": RaiseIntentResultResponse,
    "contextListenerUnsubscribe": ContextListenerUnsubscribeRequest,
    "heartbeatAcknowledgmentRequest": HeartbeatAcknowledgmentRequest,
    "registerExternalHandler": RegisterExternalHandlerRequest,
    "unregisterExternalHandler": UnregisterExternalHandlerRequest,
    "intentResult": ExternalIntentResultRequest,
}


class MessageParseError(Exception):
    """Raised when a message cannot be parsed or validated."""

    def __init__(self, message: str, request_uuid: str | None = None):
        super().__init__(message)
        self.request_uuid = request_uuid


def parse_message(raw: Any) -> ParsedMessage:
    """Parse and validate a message (dict or Pydantic model) into a Pydantic model.

    Accepts either a raw mapping (dict-like) or a Pydantic `BaseModel` envelope.
    When given a model, it is converted to a plain dict via `.model_dump()`
    (or `.dict()` for older Pydantic versions) before validation.
    """
    # Normalize to plain dict so downstream validators receive JSON-native types.
    if isinstance(raw, BaseModel):
        if hasattr(raw, "model_dump"):
            data = raw.model_dump()
        else:
            data = raw.dict()
    else:
        data = dict(raw)

    msg_type = data.get("type")
    request_uuid = (data.get("meta") or {}).get("requestUuid")

    if not msg_type:
        raise MessageParseError("Missing message type", request_uuid)

    model_class = MESSAGE_TYPE_MAP.get(msg_type)
    if not model_class:
        raise MessageParseError(f"Unknown message type: {msg_type}", request_uuid)

    try:
        return cast(ParsedMessage, model_class.model_validate(data))
    except ValidationError as e:
        # Extract a clean error message from Pydantic validation errors
        errors = e.errors()
        if errors:
            first = errors[0]
            loc = ".".join(str(x) for x in first.get("loc", []))
            msg = first.get("msg", "Validation error")
            raise MessageParseError(f"{loc}: {msg}", request_uuid) from e
        raise MessageParseError("Validation failed", request_uuid) from e
