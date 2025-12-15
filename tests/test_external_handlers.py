import asyncio
import json
import pytest
from typing import cast
from fastapi import WebSocket
from fdc3.desktop_agent.protocol.dacp.external_models import (
    RegisterExternalHandlerRequest,
    UnregisterExternalHandlerRequest,
    ExternalIntentResultRequest,
)

from fdc3.desktop_agent.core.external_registry import ExternalHandlerRegistry
from fdc3.desktop_agent.core import core_services


def test_external_registry_basic():
    reg = ExternalHandlerRegistry()
    h1 = reg.register("inst-1", "h1", ["I.a", "I.b"], priority=5)
    reg.register("inst-2", "h2", ["I.a"], priority=1)

    handlers = reg.get_handlers_for_intent("I.a")
    assert len(handlers) == 2
    # h1 has higher priority and should be first
    assert handlers[0].handler_id == "h1"

    # unregister h1
    reg.unregister(h1)
    handlers = reg.get_handlers_for_intent("I.a")
    assert len(handlers) == 1
    assert handlers[0].handler_id == "h2"

    # unregister by instance
    reg.unregister_by_instance("inst-2")
    assert not reg.list_handlers()


class DummyWebSocket:
    def __init__(self):
        self.last = None

    async def send_text(self, text: str):
        self.last = text


class DummyConnectionManager:
    def __init__(self):
        self.sent = []

    async def send_to_instance(self, instance_uuid: str, message: str):
        self.sent.append((instance_uuid, message))


class DummyStorage:
    pass


class DummyLauncher:
    pass


@pytest.mark.asyncio
async def test_dacp_register_and_forward(tmp_path):
    from fdc3.desktop_agent.handlers.dacp import DACPHandler

    storage = DummyStorage()
    launcher = DummyLauncher()
    conn_mgr = DummyConnectionManager()
    from fdc3.desktop_agent.storage.interfaces import Storage as _Storage
    from fdc3.desktop_agent.launcher.interfaces import (
        ProcessLauncher as _ProcessLauncher,
    )
    from fdc3.desktop_agent.handlers.connection_manager import (
        WebSocketConnectionManager as _WCM,
    )

    handler = DACPHandler(
        cast(_Storage, storage), cast(_ProcessLauncher, launcher), cast(_WCM, conn_mgr)
    )

    # Prepare wcp_sessions and fake websocket
    session_id = "sess1"
    wcp_sessions = {session_id: {"identity": {"instanceUuid": "inst-1"}}}
    ws = DummyWebSocket()

    # Register external handler via the register handler path
    reg_msg = {
        "type": "registerExternalHandler",
        "payload": {
            "handler_id": "h-ex",
            "intents": ["X.intent"],
            "priority": 2,
            "metadata": {},
        },
        "meta": {"requestUuid": "r-1"},
    }

    reg_request = RegisterExternalHandlerRequest.model_validate(reg_msg)
    await handler._handle_register_external_handler(
        reg_request, session_id, wcp_sessions, cast(WebSocket, ws)
    )

    # Parse response
    assert ws.last is not None
    resp = json.loads(ws.last)
    assert resp.get("payload") and resp["payload"].get("handler_uuid")
    handler_uuid = resp["payload"]["handler_uuid"]

    # Confirm registry has handler
    all_handlers = core_services.external_registry.list_handlers()
    assert any(h.handler_uuid == handler_uuid for h in all_handlers)

    # Now raise an intent and test forwarding+response correlation
    from fdc3.desktop_agent.protocol.dacp.dacp import (
        RaiseIntentRequest,
    )

    message = {
        "type": "raiseIntent",
        "payload": {"intent": "X.intent", "context": {}, "target": None},
        "meta": {"requestUuid": "caller-req", "source": None},
    }

    req = RaiseIntentRequest(**message)

    # run _try_external_handler in background
    task = asyncio.create_task(handler._try_external_handler(req, cast(WebSocket, ws)))

    # wait for forwarded message to be sent
    for _ in range(50):
        if conn_mgr.sent:
            break
        await asyncio.sleep(0.02)

    assert conn_mgr.sent, "No forwarded intent sent"
    inst_uuid, sent = conn_mgr.sent[-1]
    assert inst_uuid == "inst-1"
    sent_msg = json.loads(sent)
    req_uuid = sent_msg.get("payload", {}).get("request_uuid")
    assert req_uuid

    # Simulate external handler returning a result
    result_msg = {
        "type": "intentResult",
        "payload": {"request_uuid": req_uuid, "result": {"ok": True}},
    }
    result_request = ExternalIntentResultRequest.model_validate(result_msg)
    await handler._handle_external_intent_result(result_request)

    # await task completion
    res = await asyncio.wait_for(task, timeout=1.0)
    assert res is not None

    # Unregister handler
    unreg_msg = {
        "type": "unregisterExternalHandler",
        "payload": {"handler_uuid": handler_uuid},
        "meta": {"requestUuid": "r-2"},
    }
    unreg_request = UnregisterExternalHandlerRequest.model_validate(unreg_msg)
    await handler._handle_unregister_external_handler(
        unreg_request, session_id, wcp_sessions, cast(WebSocket, ws)
    )

    # Ensure removed
    assert not any(
        h.handler_uuid == handler_uuid
        for h in core_services.external_registry.list_handlers()
    )


@pytest.mark.asyncio
async def test_register_invalid_payload_and_forward_failure():
    from fdc3.desktop_agent.handlers.dacp import DACPHandler
    from fdc3.desktop_agent.protocol.dacp.message_parser import (
        parse_message,
        MessageParseError,
    )

    storage = DummyStorage()
    launcher = DummyLauncher()

    # Connection manager that raises when sending to instance
    class FailingConnMgr(DummyConnectionManager):
        async def send_to_instance(self, instance_uuid: str, message: str):
            raise RuntimeError("send failed")

    conn_mgr = FailingConnMgr()
    from fdc3.desktop_agent.storage.interfaces import Storage as _Storage
    from fdc3.desktop_agent.launcher.interfaces import (
        ProcessLauncher as _ProcessLauncher,
    )
    from fdc3.desktop_agent.handlers.connection_manager import (
        WebSocketConnectionManager as _WCM,
    )

    handler = DACPHandler(
        cast(_Storage, storage), cast(_ProcessLauncher, launcher), cast(_WCM, conn_mgr)
    )

    session_id = "sess2"
    wcp_sessions = {session_id: {"identity": {"instanceUuid": "inst-2"}}}
    ws = DummyWebSocket()

    # Invalid register (missing handler_id) - test that parser catches the validation error
    bad_reg_msg = {
        "type": "registerExternalHandler",
        "payload": {"intents": ["A.intent"]},
        "meta": {"requestUuid": "r-bad"},
    }
    with pytest.raises(MessageParseError):
        parse_message(bad_reg_msg)

    # Now register properly so registry has an entry
    good_reg_msg = {
        "type": "registerExternalHandler",
        "payload": {"handler_id": "h2", "intents": ["A.intent"]},
        "meta": {"requestUuid": "r-good"},
    }
    good_request = RegisterExternalHandlerRequest.model_validate(good_reg_msg)
    await handler._handle_register_external_handler(
        good_request,
        session_id,
        wcp_sessions,
        cast(WebSocket, ws),
    )
    assert ws.last is not None
    resp = json.loads(ws.last)
    assert "handler_uuid" in resp.get("payload", {})

    # Raise intent that will be forwarded but sending will fail
    from fdc3.desktop_agent.protocol.dacp.dacp import RaiseIntentRequest

    message = {
        "type": "raiseIntent",
        "payload": {"intent": "A.intent", "context": {}, "target": None},
        "meta": {"requestUuid": "r-intent", "source": None},
    }
    req = RaiseIntentRequest(**message)

    res = await handler._try_external_handler(req, cast(WebSocket, ws))
    # Forwarding failed; expect None result
    assert res is None

    # Unregister unknown handler (should ack without exception)
    ws.last = None
    unreg_msg = {
        "type": "unregisterExternalHandler",
        "payload": {"handler_uuid": "non-existent"},
        "meta": {"requestUuid": "r-unreg"},
    }
    unreg_request = UnregisterExternalHandlerRequest.model_validate(unreg_msg)
    await handler._handle_unregister_external_handler(
        unreg_request, session_id, wcp_sessions, cast(WebSocket, ws)
    )
    # ack was sent
    assert ws.last is not None
