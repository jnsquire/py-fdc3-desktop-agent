from pydantic import BaseModel
from typing import Any, Optional, Mapping

from fdc3.models.dacp import (
    BroadcastEvent,
    IntentEvent,
    ForwardedIntentMessage,
    AddContextListenerResponse,
    AddIntentListenerResponse,
    ContextListenerUnsubscribeResponse,
    IntentListenerUnsubscribeResponse,
    RegisterExternalHandlerResponse,
    UnregisterExternalHandlerResponse,
)

# Helper: map a raw message dict to an appropriate Pydantic model instance.
# Returns the model instance on success or raises ValidationError on failure.
_MODEL_MAP = {
    "broadcastEvent": BroadcastEvent,
    "intentEvent": IntentEvent,
    "forwardedIntent": ForwardedIntentMessage,
    "addContextListenerResponse": AddContextListenerResponse,
    "addIntentListenerResponse": AddIntentListenerResponse,
    "contextListenerUnsubscribeResponse": ContextListenerUnsubscribeResponse,
    "intentListenerUnsubscribeResponse": IntentListenerUnsubscribeResponse,
    "registerExternalHandlerResponse": RegisterExternalHandlerResponse,
    "unregisterExternalHandlerResponse": UnregisterExternalHandlerResponse,
}


def parse_message(msg: Mapping[str, Any]) -> Optional[BaseModel]:
    """Validate and parse a raw message dict into a Pydantic model.

    Returns a BaseModel instance on success or None if the message type
    is unrecognized. Raises `ValidationError` for malformed messages.
    """
    t = msg.get("type")
    model = _MODEL_MAP.get(t)  # type: ignore
    if not model:
        return None
    # Use model validation; prefer model_validate if available (pydantic v2),
    # fall back to constructor.
    if hasattr(model, "model_validate"):
        return model.model_validate(dict(msg))
    return model(**dict(msg))
