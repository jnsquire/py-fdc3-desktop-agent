import types
import pytest
from typing import cast, Any

from fastapi import WebSocket

from fdc3.desktop_agent.handlers.connection_manager import WebSocketConnectionManager
from fdc3.desktop_agent.handlers.access_control import AccessControlHandler
from fdc3.desktop_agent.access_control import (
    AllowlistAccessPolicy,
    AccessControlManager,
)
from fdc3.desktop_agent.handlers.system_intent import SystemIntentHandler
from fdc3.desktop_agent.handlers.wcp import WCPHandler
from fdc3.desktop_agent.storage import Storage
from fdc3.desktop_agent.launcher import ProcessLauncher
from fdc3.models.primitives import RequestUuid


class FakeWebSocket:
    def __init__(self, headers=None):
        self.sent = []
        self.closed = False
        self.headers = headers or {}

    async def send_text(self, data):
        if data == "raise":
            raise RuntimeError("send failed")
        self.sent.append(data)

    async def close(self, code=1000):
        self.closed = True


@pytest.mark.asyncio
async def test_connection_manager_send_and_close():
    manager = WebSocketConnectionManager()
    ws = FakeWebSocket()

    manager.add_connection("inst1", cast(WebSocket, ws))
    assert "inst1" in manager.get_connected_instances()

    # send to instance
    await manager.send_to_instance("inst1", "hello")
    assert ws.sent == ["hello"]

    # simulate send failure removes connection
    ws2 = FakeWebSocket()
    manager.add_connection("inst2", cast(WebSocket, ws2))
    # cause send_text to raise
    await manager.send_to_instance("inst2", "raise")
    assert "inst2" not in manager.get_connected_instances()

    # close_all will clear remaining connections
    manager.add_connection("inst3", cast(WebSocket, FakeWebSocket()))
    await manager.close_all()
    assert manager.get_connected_instances() == []


@pytest.mark.asyncio
async def test_access_control_handler(monkeypatch):
    policy = AllowlistAccessPolicy(["example.com", "*.example.org", "site*"])
    mgr = AccessControlManager(policy)
    handler = AccessControlHandler(mgr, ["example.com"])

    class WS:
        def __init__(self, origin, ua=None):
            self.headers = {"origin": origin, "user-agent": ua}
            self.closed = False

        async def close(self, code=1000):
            self.closed = True

    ws_allowed = WS("http://example.com")
    allowed = await handler.validate_connection(cast(WebSocket, ws_allowed))
    assert allowed is True

    ws_blocked = WS("http://notallowed.com")
    # using a manager with the policy will reject
    blocked = await handler.validate_connection(cast(WebSocket, ws_blocked))
    assert blocked is False
    assert ws_blocked.closed is True


@pytest.mark.asyncio
async def test_system_intent_handler(monkeypatch):
    # prevent opening browser or files
    monkeypatch.setattr("webbrowser.open", lambda url: True)
    monkeypatch.setattr("os.startfile", lambda path: None, raising=False)

    s = SystemIntentHandler(templates_dir=".")
    assert s.is_system_intent("fdc3.openUrl")
    assert not s.is_system_intent("fdc3.unknownIntent")

    # test open_url success
    ws = FakeWebSocket()
    resp = await s.handle_system_intent(
        "fdc3.openUrl",
        {"url": "http://example.com"},
        None,
        cast(WebSocket, ws),
        RequestUuid(root="req-1"),
    )
    assert resp is not None

    # test open_file with missing path returns False
    resp2 = await s._handle_open_file({}, None)
    assert resp2 is False


@pytest.mark.asyncio
async def test_wcp_handler_send_and_hello(monkeypatch):
    # minimal fake storage with apps repository
    class AppsStub:
        async def get_app_metadata(self, app_id):
            from fdc3.desktop_agent.storage import AppMetadata

            return AppMetadata(app_id=app_id, name="x", allowed_origins=["example.com"])

    class FakeStorage:
        def __init__(self):
            self.apps = AppsStub()

    storage = FakeStorage()
    handler = WCPHandler(cast(Storage, storage))

    # fake websocket to capture send_text
    ws = FakeWebSocket()

    session_id = "sess1"
    wcp_sessions = {}

    # construct a minimal WCP1Hello message dict
    msg = {
        "type": "WCP1Hello",
        "payload": {
            "identityUrl": "http://example.com",
            "actualUrl": "http://example.com",
            "fdc3Version": "2.0",
        },
        "meta": {"connectionAttemptUuid": "cid", "timestamp": "now"},
    }

    await handler._handle_wcp1_hello(msg, session_id, wcp_sessions, cast(WebSocket, ws))
    assert session_id in wcp_sessions
    assert ws.sent, "Handshake response should be sent"

    # test goodbye removes session
    await handler._handle_wcp6_goodbye(session_id, wcp_sessions)
    assert session_id not in wcp_sessions


@pytest.mark.asyncio
async def test_wcp_validate_identity_cases():
    class FakeOrigins:
        async def get_allowed_origins(self, app_id):
            return []

    class AppsStubEmpty:
        async def get_app_metadata(self, app_id):
            return None

    class FakeStorage:
        def __init__(self):
            self.apps = AppsStubEmpty()

    storage = FakeStorage()
    handler = WCPHandler(cast(Storage, storage))

    from fdc3.desktop_agent.transport.wcp.wcp import (
        WCP4ValidateAppIdentity,
        WCP4ValidateAppIdentityPayload,
    )

    # Case: no wcp1_identity in sessions
    wcp4 = WCP4ValidateAppIdentity(
        payload=WCP4ValidateAppIdentityPayload(instanceId=None, instanceUuid=None),
        meta=cast(Any, {"connectionAttemptUuid": "cid", "timestamp": "now"}),
    )
    res = await handler._validate_app_identity(wcp4, "s", {"s": {}})
    assert res["valid"] is False

    # Case: wcp1_identity exists but instanceUuid missing
    sessions = {
        "s": {"wcp1_identity": {"identityUrl": "http://a", "actualUrl": "http://a"}}
    }
    res2 = await handler._validate_app_identity(wcp4, "s", sessions)
    assert res2["valid"] is False


@pytest.mark.asyncio
async def test_dacp_handler_send_and_unknown_message():
    # minimal fakes for constructor
    class FakeStorage:
        pass

    class FakeLauncher:
        pass

    from fdc3.desktop_agent.handlers.dacp import DACPHandler

    handler = DACPHandler(
        cast(Storage, FakeStorage()),
        cast(ProcessLauncher, FakeLauncher()),
        cast(WebSocketConnectionManager, None),
    )

    # fake websocket whose send_text raises
    class BadWS:
        async def send_text(self, data):
            raise RuntimeError("boom")

    fake_model = types.SimpleNamespace(
        model_dump_json=lambda: "{}", __class__=type("M", (), {})
    )
    # _send_model should swallow exceptions
    await handler._send_model(cast(WebSocket, BadWS()), fake_model)

    # unknown message type should not raise
    await handler.handle_message(
        {"type": "nonsense"}, "s", {}, cast(WebSocket, FakeWebSocket())
    )


@pytest.mark.asyncio
async def test_system_intent_many_handlers(monkeypatch):
    calls = []
    monkeypatch.setattr("webbrowser.open", lambda url: calls.append(url))
    monkeypatch.setattr("subprocess.run", lambda cmd: calls.append(cmd))
    monkeypatch.setattr("os.startfile", lambda p: calls.append(p), raising=False)

    s = SystemIntentHandler(templates_dir=".")

    # call many handler methods directly
    assert await s._handle_open_app_directory(None, None) is True
    assert await s._handle_manage_apps(None, None) is True
    assert await s._handle_install_app(None, None) is True
    assert await s._handle_uninstall_app(None, None) is True
    assert await s._handle_system_settings(None, None) is True
    assert await s._handle_configure_channels(None, None) is True
    assert await s._handle_system_diagnostics(None, None) is True
    assert await s._handle_create_channel(None, None) is True
    assert await s._handle_delete_channel(None, None) is True
    assert await s._handle_manage_channel(None, None) is True

    # resolve_intent with context
    assert await s._handle_resolve_intent({"intent": "doit"}, None) is True

    # open_url with missing url should return False
    assert await s._handle_open_url({}, None) is False
    # with url -> True
    assert await s._handle_open_url({"url": "http://x"}, None) is True

    # open_file: provide filePath (simulated)
    assert await s._handle_open_file({"filePath": "C:/tmp/file.txt"}, None) is True

    # system search
    assert await s._handle_system_search({"query": "hi"}, None) is True

    # notifications/alerts
    assert await s._handle_show_notification({"title": "T", "body": "B"}, None) is True
    assert await s._handle_system_alert({"message": "X"}, None) is True
