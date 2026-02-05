"""Message parser relocated into `fdc3.models.dacp`."""

from __future__ import annotations

from typing import Mapping
from pydantic import ValidationError
import logging

from . import external_models as _external_models  # noqa: F401
from .dacp import DacpMessage

logger = logging.getLogger(__name__)


class MessageParseError(Exception):
    """Raised when a message cannot be parsed or validated."""

    def __init__(self, message: str, request_uuid: str | None = None):
        super().__init__(message)
        self.request_uuid = request_uuid


def parse_message(raw: Mapping[str, object]) -> DacpMessage:
    """Parse and validate a DACP message into a typed model.

    Accepts a dict-like payload.
    """
    data = dict(raw)

    msg_type = data.get("type")
    request_uuid = (data.get("meta") or {}).get("requestUuid")

    if not msg_type:
        raise MessageParseError("Missing message type", request_uuid)

    model_class = DacpMessage.MESSAGE_TYPE_MAP.get(msg_type)
    if not model_class:
        raise MessageParseError(f"Unknown message type: {msg_type}", request_uuid)

    try:
        return model_class.model_validate(data)
    except ValidationError as e:
        # Extract a clean error message from Pydantic validation errors
        errors = e.errors()
        if errors:
            first = errors[0]
            loc = ".".join(str(x) for x in first.get("loc", []))
            msg = first.get("msg", "Validation error")
            raise MessageParseError(f"{loc}: {msg}", request_uuid) from e
        raise MessageParseError("Validation failed", request_uuid) from e
