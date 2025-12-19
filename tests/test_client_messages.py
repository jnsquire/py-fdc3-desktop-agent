import asyncio
import json
import pytest

from fdc3.client import models
from fdc3.client.client import FDC3Client


def test_message_subclasses_have_expected_type_strings():
    assert models.WCP1Hello().type == "WCP1Hello"
    assert models.WCP4ValidateAppIdentity().type == "WCP4ValidateAppIdentity"
    assert models.RegisterExternalHandler().type == "registerExternalHandler"
    assert models.UnregisterExternalHandler().type == "unregisterExternalHandler"
    assert models.AddContextListener().type == "addContextListener"
    assert models.ContextListenerUnsubscribe().type == "contextListenerUnsubscribe"
    assert models.AddIntentListener().type == "addIntentListener"
    assert models.IntentListenerUnsubscribe().type == "intentListenerUnsubscribe"
    assert models.IntentResult().type == "intentResult"
    assert models.Broadcast().type == "broadcast"


class FakeWS:
    def __init__(self, client):
        self.client = client
        self.sent = None

    async def send(self, message: str):
        # Store the raw message and schedule a resolution of the pending future
        self.sent = message
        data = json.loads(message)
        req_uuid = data.get("meta", {}).get("requestUuid")

        async def _resolve_later():
            # yield to event loop to allow client to register the future
            await asyncio.sleep(0)
            # Simulate agent response
            self.client._resolve_pending_response(req_uuid, result={"ok": True})

        asyncio.create_task(_resolve_later())


@pytest.mark.asyncio
async def test_send_and_wait_injects_meta_and_awaits():
    client = FDC3Client("ws://example")
    fake = FakeWS(client)
    client._ws = fake

    msg = models.RegisterExternalHandler(payload={"handler_id": "h1", "intents": ["i"]})
    result = await client._send_and_wait(msg, timeout=1.0)

    # The fake websocket recorded the sent JSON - ensure meta present
    sent = json.loads(fake.sent)
    assert "meta" in sent and "requestUuid" in sent["meta"]
    assert isinstance(sent["meta"]["requestUuid"], str)
    assert "timestamp" in sent["meta"]
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_send_and_wait_uses_existing_request_uuid_if_provided():
    client = FDC3Client("ws://example")
    fake = FakeWS(client)
    client._ws = fake

    msg = models.RegisterExternalHandler(
        payload={"handler_id": "h1"}, meta={"requestUuid": "existing"}
    )

    result = await client._send_and_wait(msg, timeout=1.0)

    sent = json.loads(fake.sent)
    assert sent["meta"]["requestUuid"] == "existing"
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_send_and_wait_timeout_raises():
    client = FDC3Client("ws://example")

    # FakeWS that does not resolve
    class SilentWS:
        def __init__(self):
            self.sent = None

        async def send(self, message: str):
            self.sent = message

    fake = SilentWS()
    client._ws = fake

    msg = models.RegisterExternalHandler(payload={"handler_id": "h1"})

    with pytest.raises(asyncio.TimeoutError):
        await client._send_and_wait(msg, timeout=0.01)
