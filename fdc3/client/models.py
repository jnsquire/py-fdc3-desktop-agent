from pydantic import BaseModel
from typing import Any, Optional, Dict, Literal

from fdc3.models.dacp.dacp import MESSAGE_TYPE_MAP


def parse_message(msg: Any) -> Optional[BaseModel]:
    """Validate and parse a message (dict or Pydantic model) into a Pydantic model.

    Accepts either a raw mapping (dict-like) or a Pydantic `BaseModel` envelope.
    When given a model, it is converted to a plain dict via `.model_dump()`.

    This function requires Pydantic v2 APIs (`model_dump`/`model_validate`).

    Returns a BaseModel instance on success or None if the message type
    is unrecognized. Raises `ValidationError` for malformed messages.
    """
    # Normalize to plain dict so downstream validators receive JSON-native types.
    if isinstance(msg, BaseModel):
        data = msg.model_dump()
    else:
        data = dict(msg)

    t = data.get("type")
    if not isinstance(t, str):
        return None
    model = MESSAGE_TYPE_MAP.get(t)
    if not model:
        return None
    # Use Pydantic v2 validation API.
    return model.model_validate(data)


# Typed message envelopes used by the client when sending WCP/DACP messages.
class Message(BaseModel):
    type: str
    payload: Optional[Dict[str, Any]] = None
    meta: Optional[Dict[str, Any]] = None

    model_config = {"extra": "allow"}


class WCP1Hello(Message):
    type: Literal["WCP1Hello"] = "WCP1Hello"


class WCP4ValidateAppIdentity(Message):
    type: Literal["WCP4ValidateAppIdentity"] = "WCP4ValidateAppIdentity"


class RegisterExternalHandler(Message):
    type: Literal["registerExternalHandler"] = "registerExternalHandler"


class UnregisterExternalHandler(Message):
    type: Literal["unregisterExternalHandler"] = "unregisterExternalHandler"


class AddContextListener(Message):
    type: Literal["addContextListener"] = "addContextListener"


class ContextListenerUnsubscribe(Message):
    type: Literal["contextListenerUnsubscribe"] = "contextListenerUnsubscribe"


class AddIntentListener(Message):
    type: Literal["addIntentListener"] = "addIntentListener"


class IntentListenerUnsubscribe(Message):
    type: Literal["intentListenerUnsubscribe"] = "intentListenerUnsubscribe"


class IntentResult(Message):
    type: Literal["intentResult"] = "intentResult"


class Broadcast(Message):
    type: Literal["broadcast"] = "broadcast"
