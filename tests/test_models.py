from fdc3.client import models
from pydantic import ValidationError
import pytest


def test_parse_broadcast_event():
    msg = {
        "type": "broadcastEvent",
        "payload": {"context": {"type": "test", "value": 1}},
        "meta": {"eventUuid": "e1", "timestamp": "2025-01-01T00:00:00Z"},
    }

    model = models.parse_message(msg)
    assert model is not None
    assert isinstance(model, models.BroadcastEvent)
    assert model.type == "broadcastEvent"
    assert model.payload.context["type"] == "test"


def test_parse_forwarded_intent():
    msg = {
        "type": "forwardedIntent",
        "payload": {
            "request_uuid": "r1",
            "intent": "TestIntent",
            "context": {"type": "test"},
        },
        "meta": {"requestUuid": "r1", "timestamp": "2025-01-01T00:00:00Z"},
    }

    model = models.parse_message(msg)
    assert model is not None
    assert isinstance(model, models.ForwardedIntentMessage)
    assert model.type == "forwardedIntent"
    assert model.payload.intent == "TestIntent"


def test_invalid_message_raises():
    msg = {"type": "broadcastEvent", "payload": {"bad": object()}, "meta": {}}
    with pytest.raises(ValidationError):
        models.parse_message(msg)
