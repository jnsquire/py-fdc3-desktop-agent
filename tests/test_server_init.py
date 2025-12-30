import json
from typing import Any, Callable, Optional, cast

import pytest
from fastapi.testclient import TestClient
from fastapi import WebSocket
from fastapi.websockets import WebSocketDisconnect

from fdc3.desktop_agent.config import DesktopAgentConfig
from fdc3.desktop_agent.tools import yield_once


class _AppsStub:
    def __init__(self):
        self.added: list[Any] = []

    async def add_app(self, metadata: Any) -> None:
        self.added.append(metadata)


class _StorageStub:
    def __init__(self):
        self.apps = _AppsStub()
        self.initialized = False
        self.closed = False

    async def initialize(self) -> None:
        self.initialized = True

    async def close(self) -> None:
        self.closed = True


class _LauncherStub:
    def __init__(self, *, raise_on_stop: bool = False):
        self.raise_on_stop = raise_on_stop
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True
        if self.raise_on_stop:
            raise RuntimeError("stop failed")


class _PluginStub:
    def __init__(self, name: str = "p1"):
        self.name = name

    async def on_register(self, core_services: Any) -> None:  # pragma: no cover
        return

    async def on_unregister(self, core_services: Any) -> None:  # pragma: no cover
        return


class _PluginRegistryStub:
    def __init__(self):
        self._plugins: list[Any] = []

    def register(self, plugin: Any) -> None:
        self._plugins.append(plugin)

    def list_plugins(self) -> list[Any]:
        return list(self._plugins)


class _ChannelManagerStub:
    def __init__(self):
        self.emitted: list[tuple[Any, ...]] = []

    def _emit_event(
        self,
        event_type: Any,
        channel_id: Any,
        instance_uuid: Any,
        context: Any,
        *,
        remote: bool,
    ) -> None:
        self.emitted.append((event_type, channel_id, instance_uuid, context, remote))


class _CoreServicesStub:
    def __init__(self):
        self.plugin_registry = _PluginRegistryStub()
        self.channel_manager = _ChannelManagerStub()
        self.registered: list[Any] = []

    async def register_plugin(self, plugin: Any) -> None:
        self.plugin_registry.register(plugin)
        self.registered.append(plugin)

    async def unregister_plugin(self, plugin: Any) -> None:
        raise RuntimeError("unregister failed")


class _DistributedAdapterStub:
    def __init__(self, *, fail_start: bool = False, fail_subscribe: bool = False):
        self.fail_start = fail_start
        self.fail_subscribe = fail_subscribe
        self.started = False
        self.subscribed = False
        self.unsubscribed = False
        self.stopped = False
        self.cb: Optional[Callable[[Any], None]] = None

    async def start(self) -> None:
        if self.fail_start:
            raise RuntimeError("start failed")
        self.started = True

    async def subscribe(self, topic: str, cb: Callable[[Any], None]) -> str:
        if self.fail_subscribe:
            raise RuntimeError("subscribe failed")
        self.subscribed = True
        self.cb = cb
        return "sub-1"

    async def unsubscribe(self, sub_id: str) -> None:
        self.unsubscribed = True
        raise RuntimeError("unsubscribe failed")

    async def stop(self) -> None:
        self.stopped = True
        raise RuntimeError("stop failed")


@pytest.mark.asyncio
async def test_server_lifespan_bridge_channels_state_factory_populates_state(
    monkeypatch,
):
    from fdc3.desktop_agent import server as server_mod

    class _ChannelStub:
        def __init__(self, channel_id: str, members: list[str]):
            self.id = channel_id
            self.members = members

    class _ChannelManagerStateStub:
        def __init__(self):
            self.channels = {
                "red": _ChannelStub("red", ["uuid1"]),
                "blue": _ChannelStub("blue", []),
            }

        def list_channels(self):
            return list(self.channels.values())

        def get_channel_members(self, channel_id: str) -> list[str]:
            if channel_id in self.channels:
                return list(self.channels[channel_id].members)
            return []

    class _AppInstanceStub:
        def __init__(self, app_id: str, instance_id: str, instance_uuid: str):
            self.app_id = app_id
            self.instance_id = instance_id
            self.instance_uuid = instance_uuid

    class _AppRegistryStub:
        def __init__(self):
            self.instances = {
                "uuid1": _AppInstanceStub("app1", "inst1", "uuid1"),
            }

        def get_instance(self, instance_uuid: str):
            return self.instances.get(instance_uuid)

    class _CoreServicesBridgeStub:
        def __init__(self):
            self.plugin_registry = _PluginRegistryStub()
            self.channel_manager = _ChannelManagerStateStub()
            self.app_registry = _AppRegistryStub()

        async def register_plugin(self, plugin: Any) -> None:
            self.plugin_registry.register(plugin)

        async def unregister_plugin(self, plugin: Any) -> None:
            return

    monkeypatch.setattr(server_mod, "core_services", _CoreServicesBridgeStub())

    class _BridgeClientCapture:
        def __init__(
            self,
            settings: Any,
            *,
            implementation_metadata_factory: Any,
            channels_state_factory: Any,
            request_handler: Any,
        ):
            self.channels_state_factory = channels_state_factory
            self.captured_state: Optional[dict] = None

        async def start(self) -> None:
            self.captured_state = self.channels_state_factory()

        async def stop(self) -> None:
            return

    monkeypatch.setattr(server_mod, "BridgeClient", _BridgeClientCapture)

    storage = _StorageStub()
    config = DesktopAgentConfig(
        storage=cast(Any, storage),
        launcher=cast(Any, _LauncherStub()),
        auto_discover_plugins=False,
        bridge_enabled=True,
        bridge_requested_name="agent-1",
    )

    app = server_mod.create_app(config)

    async with app.router.lifespan_context(app):
        bridge_client = app.state.bridge_client
        assert bridge_client is not None
        captured = cast(Any, bridge_client).captured_state
        assert captured is not None
        assert captured["red"] == [
            {
                "desktopAgent": "agent-1",
                "appId": "app1",
                "instanceId": "inst1",
                "instanceUuid": "uuid1",
            }
        ]
        assert captured["blue"] == []


@pytest.mark.asyncio
async def test_server_lifespan_registers_plugins_and_handles_get_adapter_error(
    monkeypatch,
):
    # Patch core_services for deterministic plugin tracking
    from fdc3.desktop_agent import server as server_mod

    monkeypatch.setattr(server_mod, "core_services", _CoreServicesStub())

    class AgentClientManagerBoom:
        def __init__(self):
            pass

        async def close_all(self) -> None:
            raise RuntimeError("close_all failed")

    class InstanceConnManagerBoom:
        def __init__(self):
            pass

        async def close_all(self) -> None:
            raise RuntimeError("close_all failed")

    monkeypatch.setattr(
        server_mod, "AgentClientConnectionManager", AgentClientManagerBoom
    )
    monkeypatch.setattr(
        server_mod, "WebSocketConnectionManager", InstanceConnManagerBoom
    )

    # Force adapter discovery failure (covers the get_adapter() exception branch)
    monkeypatch.setattr(
        server_mod, "get_adapter", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    storage = _StorageStub()
    launcher = _LauncherStub(raise_on_stop=True)

    config = DesktopAgentConfig(
        host="0.0.0.0",
        port=8000,
        storage=cast(Any, storage),
        launcher=cast(Any, launcher),
        auto_discover_plugins=False,
        plugins=cast(Any, [_PluginStub("p1")]),
        distributed_adapter=None,
        allowed_origins=["example.com"],
    )

    app = server_mod.create_app(config)

    async with app.router.lifespan_context(app):
        assert app.state.storage is storage
        assert storage.initialized is True
        assert app.state.distributed_adapter is None
        assert app.state.distributed_subscription_id is None
        assert len(app.state.core_services.registered) == 1

    # shutdown should not propagate stop failure
    assert storage.closed is True


@pytest.mark.asyncio
async def test_server_lifespan_distributed_adapter_event_handling(monkeypatch):
    from fdc3.desktop_agent import server as server_mod

    monkeypatch.setattr(server_mod, "core_services", _CoreServicesStub())

    adapter = _DistributedAdapterStub()
    storage = _StorageStub()

    config = DesktopAgentConfig(
        storage=cast(Any, storage),
        launcher=cast(Any, _LauncherStub()),
        auto_discover_plugins=False,
        distributed_adapter=cast(Any, adapter),
    )

    app = server_mod.create_app(config)

    async with app.router.lifespan_context(app):
        assert app.state.distributed_adapter is adapter
        assert adapter.started is True
        assert adapter.subscribed is True
        assert adapter.cb is not None

        # Valid JSON string event with JSON context (covers the json.loads branches)
        adapter.cb(
            {
                "event_type": "join",
                "channel_id": "red",
                "instance_uuid": "uuid1",
                "context": json.dumps({"foo": "bar"}),
            }
        )
        await yield_once()

        # Dict event should bypass string parsing
        adapter.cb(
            {
                "event_type": "leave",
                "channel_id": "blue",
                "instance_uuid": "uuid2",
                "context": None,
            }
        )
        await yield_once()

        # Invalid JSON string event should be swallowed by handler
        adapter.cb("not-json")
        await yield_once()

        emitted = app.state.core_services.channel_manager.emitted
        assert ("join", "red", "uuid1", {"foo": "bar"}, True) in emitted
        assert ("leave", "blue", "uuid2", None, True) in emitted

    # adapter unsubscribe/stop failures are swallowed
    assert adapter.unsubscribed is True
    assert adapter.stopped is True


@pytest.mark.asyncio
async def test_server_lifespan_distributed_adapter_start_failure_sets_state_none(
    monkeypatch,
):
    from fdc3.desktop_agent import server as server_mod

    monkeypatch.setattr(server_mod, "core_services", _CoreServicesStub())

    adapter = _DistributedAdapterStub(fail_start=True)
    storage = _StorageStub()

    config = DesktopAgentConfig(
        storage=cast(Any, storage),
        launcher=cast(Any, _LauncherStub()),
        auto_discover_plugins=False,
        distributed_adapter=cast(Any, adapter),
    )

    app = server_mod.create_app(config)

    async with app.router.lifespan_context(app):
        assert app.state.distributed_adapter is None
        assert app.state.distributed_subscription_id is None


def test_server_template_routes_render(monkeypatch):
    from fdc3.desktop_agent import server as server_mod

    monkeypatch.setattr(server_mod, "get_adapter", lambda: None)

    storage = _StorageStub()
    config = DesktopAgentConfig(
        storage=cast(Any, storage),
        launcher=cast(Any, _LauncherStub()),
        auto_discover_plugins=False,
        distributed_adapter=None,
    )
    app = server_mod.create_app(config)

    with TestClient(app) as client:
        for path in [
            "/admin",
            "/app-directory",
            "/system-settings",
            "/diagnostics",
            "/channel-monitor",
            "/channel-sequence",
            "/public-channels",
        ]:
            res = client.get(path)
            assert res.status_code == 200


@pytest.mark.asyncio
async def test_agent_client_connection_manager_paths():
    from fdc3.desktop_agent.server import AgentClientConnectionManager

    class WS:
        def __init__(self, *, fail_send: bool = False, fail_close: bool = False):
            self.accepted = False
            self.sent: list[str] = []
            self.fail_send = fail_send
            self.fail_close = fail_close

        async def accept(self) -> None:
            self.accepted = True

        async def send_text(self, data: str) -> None:
            if self.fail_send:
                raise RuntimeError("send failed")
            self.sent.append(data)

        async def close(self) -> None:
            if self.fail_close:
                raise RuntimeError("close failed")

    mgr = AgentClientConnectionManager()

    ws_ok = WS()
    await mgr.connect(cast(WebSocket, ws_ok), "i1")
    assert ws_ok.accepted is True

    # Add a broken socket to cover broadcast failure path
    ws_bad = WS(fail_send=True)
    mgr._active_connections.add(
        cast(WebSocket, ws_bad)
    )  # intentionally reaching in for coverage

    await mgr.broadcast_agent_event("connected", "i1")
    assert ws_bad not in mgr._active_connections

    assert await mgr.send_to_instance("i1", "hello") is True
    assert ws_ok.sent

    # unknown instance id -> False
    assert await mgr.send_to_instance("missing", "hello") is False

    # send failure should disconnect
    ws_fail = WS(fail_send=True)
    mgr._connections["i2"] = cast(WebSocket, ws_fail)
    mgr._active_connections.add(cast(WebSocket, ws_fail))
    assert await mgr.send_to_instance("i2", "hello") is False

    # disconnect should delete mapping
    await mgr.disconnect(cast(WebSocket, ws_ok), "i1")
    assert "i1" not in mgr._connections

    # close_all swallows close failures
    mgr._active_connections.add(cast(WebSocket, WS(fail_close=True)))
    await mgr.close_all()


@pytest.mark.asyncio
async def test_websocket_endpoint_denied_by_access_control(monkeypatch):
    from fdc3.desktop_agent import server as server_mod

    class DenyAccess:
        def __init__(self, *args, **kwargs):
            pass

        async def validate_connection(self, websocket: WebSocket, headers: Any) -> bool:
            return False

    monkeypatch.setattr(server_mod, "AccessControlHandler", DenyAccess)
    monkeypatch.setattr(server_mod, "get_adapter", lambda: None)

    config = DesktopAgentConfig(
        storage=cast(Any, _StorageStub()),
        launcher=cast(Any, _LauncherStub()),
        auto_discover_plugins=False,
        distributed_adapter=None,
    )
    app = server_mod.create_app(config)

    ws_route = next(r for r in app.router.routes if getattr(r, "path", None) == "/ws")
    endpoint = ws_route.endpoint

    class FakeWS:
        def __init__(self):
            self.headers = {}
            self.accepted = False

        async def accept(self) -> None:
            self.accepted = True

    fake = FakeWS()
    await endpoint(fake)
    assert fake.accepted is False


@pytest.mark.asyncio
async def test_websocket_endpoint_heartbeat_send_error(monkeypatch):
    from fdc3.desktop_agent import server as server_mod

    class AllowAccess:
        def __init__(self, *args, **kwargs):
            pass

        async def validate_connection(self, websocket: WebSocket, headers: Any) -> bool:
            return True

    class WCPStub:
        def __init__(self, *args, **kwargs):
            pass

        async def handle_message(
            self, message: dict, session_id: str, wcp_sessions: dict, websocket: Any
        ):
            return "dacp"

    class DACPStub:
        def __init__(self, *args, **kwargs):
            pass

        async def handle_message(self, *args, **kwargs):
            return

    async def fast_sleep(_seconds: float) -> None:
        return

    monkeypatch.setattr(server_mod, "AccessControlHandler", AllowAccess)
    monkeypatch.setattr(server_mod, "WCPHandler", WCPStub)
    monkeypatch.setattr(server_mod, "DACPHandler", DACPStub)
    monkeypatch.setattr(server_mod.asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(server_mod, "get_adapter", lambda: None)

    config = DesktopAgentConfig(
        storage=cast(Any, _StorageStub()),
        launcher=cast(Any, _LauncherStub()),
        auto_discover_plugins=False,
        distributed_adapter=None,
    )
    app = server_mod.create_app(config)

    ws_route = next(r for r in app.router.routes if getattr(r, "path", None) == "/ws")
    endpoint = ws_route.endpoint

    class FakeWS:
        def __init__(self):
            self.headers = {}
            self.accepted = False
            self._recv_calls = 0

        async def accept(self) -> None:
            self.accepted = True

        async def receive_text(self) -> str:
            self._recv_calls += 1
            if self._recv_calls == 1:
                return json.dumps(
                    {
                        "type": "WCP1Hello",
                        "meta": {"connectionAttemptUuid": "sess-1"},
                        "payload": {},
                    }
                )
            await yield_once()
            raise WebSocketDisconnect()

        async def send_text(self, data: str) -> None:
            raise RuntimeError("send failed")

    fake = FakeWS()

    async with app.router.lifespan_context(app):
        await endpoint(fake)

    assert fake.accepted is True
