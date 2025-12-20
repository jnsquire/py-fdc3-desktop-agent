import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, Optional, cast

import pytest

from fdc3.desktop_agent.bridging.client import (
    BridgeClient,
    BridgeConnectionSettings,
    RequestHandlerProtocol,
)


class FakeWebSocket:
    """Minimal async websocket-like object for BridgeClient tests."""

    def __init__(
        self,
        *,
        incoming: list[dict] | None = None,
        on_send: Optional[Callable[[dict], Awaitable[None]]] = None,
    ):
        self._q: asyncio.Queue[Any] = asyncio.Queue()
        for msg in incoming or []:
            self._q.put_nowait(json.dumps(msg))

        self.sent: list[str] = []
        self.closed = False
        self._on_send = on_send

    def push_incoming(self, msg: dict) -> None:
        self._q.put_nowait(json.dumps(msg))

    async def recv(self):
        return await self._q.get()

    async def send(self, data: str):
        self.sent.append(data)
        if self._on_send is not None:
            await self._on_send(json.loads(data))

    async def close(self):
        self.closed = True


async def _wait_for(predicate: Callable[[], bool], timeout: float = 1.0) -> None:
    start = asyncio.get_running_loop().time()
    while True:
        if predicate():
            return
        if (asyncio.get_running_loop().time() - start) > timeout:
            raise AssertionError("Timed out waiting for condition")
        await asyncio.sleep(0.01)


def impl_meta_factory():
    return {"provider": "test"}


def channels_state_factory():
    return {}


async def _noop_request_handler(msg: dict) -> None:
    await asyncio.sleep(0, result=None)


noop_request_handler = _noop_request_handler


def make_client(
    settings,
    ws,
    *,
    request_handler: Optional[Callable] = None,
    connect_func: Optional[Callable] = None,
):
    async def _connect(url: str):
        return ws

    handler = request_handler or noop_request_handler
    return BridgeClient(
        settings,
        implementation_metadata_factory=impl_meta_factory,
        channels_state_factory=channels_state_factory,
        request_handler=cast(RequestHandlerProtocol, handler),
        connect_func=connect_func or _connect,
    )


@pytest.mark.asyncio
async def test_bridge_client_connect_and_handshake_sends_handshake_and_sets_assigned_name():
    settings = BridgeConnectionSettings(
        host="127.0.0.1",
        port_start=4475,
        port_end=4475,
        requested_name="agent-requested",
        retry_seconds=0.01,
        request_timeout_seconds=0.2,
    )

    ws = FakeWebSocket(
        incoming=[
            {"type": "hello", "payload": {"desktopAgentBridgeVersion": "1.0"}},
            {
                "type": "connectedAgentsUpdate",
                "payload": {"addAgent": "agent-assigned", "allAgents": []},
                "meta": {"requestUuid": "ignored"},
            },
        ]
    )

    async def connect_func(url: str):
        assert url == "ws://127.0.0.1:4475"
        return ws

    client = make_client(
        settings,
        FakeWebSocket(),
        request_handler=cast(
            RequestHandlerProtocol, lambda msg: asyncio.sleep(0, result=None)
        ),
        connect_func=connect_func,
    )

    await client._connect_and_handshake()

    # First outbound message should be handshake
    assert ws.sent, "expected handshake to be sent"
    handshake = json.loads(ws.sent[0])
    assert handshake["type"] == "handshake"
    assert handshake["payload"]["requestedName"] == "agent-requested"
    impl = handshake["payload"]["implementationMetadata"]
    assert impl["provider"] == "test"
    assert "fdc3Version" in impl
    assert isinstance(impl.get("optionalFeatures"), dict)
    assert handshake["payload"]["channelsState"] == {}
    assert handshake["meta"]["requestUuid"]

    assert client.assigned_name == "agent-assigned"
    assert client.is_connected is True

    await client.stop()


@pytest.mark.asyncio
async def test_bridge_client_send_agent_request_correlates_response_by_request_uuid():
    settings = BridgeConnectionSettings(
        host="127.0.0.1",
        port_start=4475,
        port_end=4475,
        requested_name="agent-requested",
        retry_seconds=0.01,
        request_timeout_seconds=0.5,
    )

    async def on_send(parsed: dict) -> None:
        # When the agent sends a request, inject a response with matching requestUuid.
        if parsed.get("type") == "getAppMetadataRequest":
            req_uuid = (parsed.get("meta") or {}).get("requestUuid")
            assert req_uuid
            ws.push_incoming(
                {
                    "type": "getAppMetadataResponse",
                    "payload": {"appMetadata": {"appId": "app-1"}},
                    "meta": {
                        "requestUuid": req_uuid,
                        "responseUuid": "resp-1",
                        "timestamp": "2025-01-01T00:00:00Z",
                    },
                }
            )

    ws = FakeWebSocket(
        incoming=[
            {"type": "hello", "payload": {"desktopAgentBridgeVersion": "1.0"}},
            {
                "type": "connectedAgentsUpdate",
                "payload": {"addAgent": "agent-assigned", "allAgents": []},
                "meta": {"requestUuid": "ignored"},
            },
        ],
        on_send=on_send,
    )

    async def connect_func(url: str):
        return ws

    client = make_client(
        settings,
        FakeWebSocket(),
        request_handler=cast(
            RequestHandlerProtocol, lambda msg: asyncio.sleep(0, result=None)
        ),
        connect_func=connect_func,
    )

    await client._connect_and_handshake()

    result = await client.send_agent_request(
        request_type="getAppMetadataRequest",
        payload={"app": {"appId": "app-1"}},
        source={"appId": "caller", "instanceId": "caller-1"},
        timeout=0.5,
    )

    assert result["type"] == "getAppMetadataResponse"
    assert result["meta"]["responseUuid"] == "resp-1"

    await client.stop()


@pytest.mark.asyncio
async def test_bridge_client_forwards_inbound_request_to_handler_and_sends_response():
    settings = BridgeConnectionSettings(
        host="127.0.0.1",
        port_start=4475,
        port_end=4475,
        requested_name="agent-requested",
        retry_seconds=0.01,
        request_timeout_seconds=0.2,
    )

    handled: dict[str, Any] = {}

    async def request_handler(msg: dict) -> dict:
        handled["msg"] = msg
        req_uuid = (msg.get("meta") or {}).get("requestUuid")
        return {
            "type": "openResponse",
            "payload": {"ok": True},
            "meta": {
                "requestUuid": req_uuid,
                "responseUuid": "resp-2",
                "timestamp": "2025-01-01T00:00:00Z",
            },
        }

    ws = FakeWebSocket(
        incoming=[
            {"type": "hello", "payload": {"desktopAgentBridgeVersion": "1.0"}},
            {
                "type": "connectedAgentsUpdate",
                "payload": {"addAgent": "agent-assigned", "allAgents": []},
                "meta": {"requestUuid": "ignored"},
            },
        ]
    )

    async def connect_func(url: str):
        return ws

    client = make_client(
        settings, ws, request_handler=request_handler, connect_func=connect_func
    )

    await client._connect_and_handshake()

    # Push an inbound request (has requestUuid but no responseUuid)
    ws.push_incoming(
        {
            "type": "openRequest",
            "payload": {"app": {"appId": "app-1"}},
            "meta": {"requestUuid": "req-2", "timestamp": "2025-01-01T00:00:00Z"},
        }
    )

    await _wait_for(
        lambda: any(
            json.loads(s).get("meta", {}).get("responseUuid") == "resp-2"
            for s in ws.sent
        )
    )
    assert handled["msg"]["type"] == "openRequest"

    await client.stop()


@pytest.mark.asyncio
async def test_bridge_client_connect_and_handshake_raises_when_no_bridge_found():
    settings = BridgeConnectionSettings(
        host="127.0.0.1",
        port_start=4475,
        port_end=4475,
        requested_name="agent-requested",
        retry_seconds=0.01,
        request_timeout_seconds=0.2,
    )

    async def connect_func(url: str):
        raise RuntimeError("nope")

    client = make_client(
        settings,
        FakeWebSocket(),
        request_handler=cast(
            RequestHandlerProtocol, lambda msg: asyncio.sleep(0, result=None)
        ),
        connect_func=connect_func,
    )

    with pytest.raises(RuntimeError, match="No bridge found"):
        await client._connect_and_handshake()


@pytest.mark.asyncio
async def test_bridge_client_connect_and_handshake_raises_on_invalid_hello():
    settings = BridgeConnectionSettings(
        host="127.0.0.1",
        port_start=4475,
        port_end=4475,
        requested_name="agent-requested",
        retry_seconds=0.01,
        request_timeout_seconds=0.2,
    )

    ws = FakeWebSocket(incoming=[{"type": "notHello", "payload": {}}])

    async def connect_func(url: str):
        return ws

    client = make_client(
        settings,
        ws,
        request_handler=cast(
            RequestHandlerProtocol, lambda msg: asyncio.sleep(0, result=None)
        ),
        connect_func=connect_func,
    )

    with pytest.raises(RuntimeError, match="did not send a valid bridge hello"):
        await client._connect_and_handshake()


@pytest.mark.asyncio
async def test_bridge_client_connect_and_handshake_times_out_waiting_for_connected_agents_update(
    monkeypatch,
):
    settings = BridgeConnectionSettings(
        host="127.0.0.1",
        port_start=4475,
        port_end=4475,
        requested_name="agent-requested",
        retry_seconds=0.01,
        request_timeout_seconds=0.2,
    )

    # Provide hello, but never send connectedAgentsUpdate.
    ws = FakeWebSocket(
        incoming=[{"type": "hello", "payload": {"desktopAgentBridgeVersion": "1.0"}}]
    )

    async def connect_func(url: str):
        return ws

    client = make_client(
        settings,
        ws,
        request_handler=cast(
            RequestHandlerProtocol, lambda msg: asyncio.sleep(0, result=None)
        ),
        connect_func=connect_func,
    )

    # _connect_and_handshake uses asyncio.wait_for(..., 3.0) for hello and 5.0 for assigned-name.
    real_wait_for = asyncio.wait_for

    async def fake_wait_for(awaitable, timeout=None):
        if timeout == 5.0:
            # Avoid leaking an un-awaited coroutine when simulating a timeout.
            close = getattr(awaitable, "close", None)
            if callable(close):
                close()
            raise asyncio.TimeoutError()
        return await real_wait_for(awaitable, timeout=timeout)

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    with pytest.raises(asyncio.TimeoutError):
        await client._connect_and_handshake()

    await client.stop()


@pytest.mark.asyncio
async def test_bridge_client_recv_loop_raises_on_authentication_failed():
    settings = BridgeConnectionSettings(
        host="127.0.0.1",
        port_start=4475,
        port_end=4475,
        requested_name="agent-requested",
        retry_seconds=0.01,
        request_timeout_seconds=0.2,
    )

    ws = FakeWebSocket(
        incoming=[
            {"type": "hello", "payload": {"desktopAgentBridgeVersion": "1.0"}},
            {
                "type": "connectedAgentsUpdate",
                "payload": {"addAgent": "agent-assigned", "allAgents": []},
                "meta": {"requestUuid": "ignored"},
            },
            {
                "type": "authenticationFailed",
                "payload": {"message": "bad token"},
                "meta": {"requestUuid": "x"},
            },
        ]
    )

    async def connect_func(url: str):
        return ws

    client = make_client(
        settings,
        ws,
        request_handler=cast(
            RequestHandlerProtocol, lambda msg: asyncio.sleep(0, result=None)
        ),
        connect_func=connect_func,
    )

    await client._connect_and_handshake()
    assert client.is_connected is True

    assert client._recv_task is not None
    with pytest.raises(RuntimeError, match="bad token"):
        await client._recv_task

    # stop() awaits the recv loop task; if it failed, it will re-raise.
    with pytest.raises(RuntimeError, match="bad token"):
        await client.stop()


@pytest.mark.asyncio
async def test_bridge_client_send_agent_request_raises_when_not_connected():
    settings = BridgeConnectionSettings(
        host="127.0.0.1",
        port_start=4475,
        port_end=4475,
        requested_name="agent-requested",
        retry_seconds=0.01,
        request_timeout_seconds=0.2,
    )

    client = make_client(
        settings,
        FakeWebSocket(),
        request_handler=cast(
            RequestHandlerProtocol, lambda msg: asyncio.sleep(0, result=None)
        ),
        connect_func=lambda url: asyncio.sleep(0, result=None),
    )

    with pytest.raises(RuntimeError, match="NotConnectedToBridge"):
        await client.send_agent_request(
            request_type="openRequest",
            payload={"app": {"appId": "app-1"}},
            source={"appId": "caller", "instanceId": "c1"},
            timeout=0.01,
        )


@pytest.mark.asyncio
async def test_bridge_client_send_request_no_wait_raises_when_not_connected():
    settings = BridgeConnectionSettings(
        host="127.0.0.1",
        port_start=4475,
        port_end=4475,
        requested_name="agent-requested",
        retry_seconds=0.01,
        request_timeout_seconds=0.2,
    )

    client = BridgeClient(
        settings,
        implementation_metadata_factory=lambda: {"provider": "test"},
        channels_state_factory=lambda: {},
        request_handler=cast(
            RequestHandlerProtocol, lambda msg: asyncio.sleep(0, result=None)
        ),
        connect_func=lambda url: asyncio.sleep(0, result=None),
    )

    with pytest.raises(RuntimeError, match="NotConnectedToBridge"):
        await client.send_request_no_wait(
            request_type="broadcastRequest",
            payload={"context": {"type": "fdc3.instrument"}},
            source={"appId": "caller", "instanceId": "c1"},
        )


@pytest.mark.asyncio
async def test_bridge_client_send_agent_request_times_out_and_cleans_pending():
    settings = BridgeConnectionSettings(
        host="127.0.0.1",
        port_start=4475,
        port_end=4475,
        requested_name="agent-requested",
        retry_seconds=0.01,
        request_timeout_seconds=0.05,
    )

    ws = FakeWebSocket(
        incoming=[
            {"type": "hello", "payload": {"desktopAgentBridgeVersion": "1.0"}},
            {
                "type": "connectedAgentsUpdate",
                "payload": {"addAgent": "agent-assigned", "allAgents": []},
                "meta": {"requestUuid": "ignored"},
            },
        ]
    )

    async def connect_func(url: str):
        return ws

    client = make_client(
        settings,
        ws,
        request_handler=cast(
            RequestHandlerProtocol, lambda msg: asyncio.sleep(0, result=None)
        ),
        connect_func=connect_func,
    )

    await client._connect_and_handshake()

    with pytest.raises(asyncio.TimeoutError):
        await client.send_agent_request(
            request_type="findInstancesRequest",
            payload={"app": {"appId": "app-1"}},
            source={"appId": "caller", "instanceId": "c1"},
            timeout=0.01,
        )

    # Pending map should be cleaned up even on timeout
    assert len(client._pending) == 0

    await client.stop()


@pytest.mark.asyncio
async def test_bridge_client_handle_response_unknown_request_uuid_is_ignored():
    settings = BridgeConnectionSettings(
        host="127.0.0.1",
        port_start=4475,
        port_end=4475,
        requested_name="agent-requested",
        retry_seconds=0.01,
        request_timeout_seconds=0.2,
    )

    client = make_client(
        settings,
        FakeWebSocket(),
        request_handler=cast(
            RequestHandlerProtocol, lambda msg: asyncio.sleep(0, result=None)
        ),
        connect_func=lambda url: asyncio.sleep(0, result=None),
    )

    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    client._pending["req-1"] = fut

    await client._handle_response("different-req", {"type": "x", "meta": {}})
    assert fut.done() is False

    # Cleanup
    client._pending.clear()


@pytest.mark.asyncio
async def test_bridge_client_stop_fails_all_pending_futures():
    settings = BridgeConnectionSettings(
        host="127.0.0.1",
        port_start=4475,
        port_end=4475,
        requested_name="agent-requested",
        retry_seconds=0.01,
        request_timeout_seconds=0.2,
    )

    client = make_client(
        settings,
        FakeWebSocket(),
        request_handler=cast(
            RequestHandlerProtocol, lambda msg: asyncio.sleep(0, result=None)
        ),
        connect_func=lambda url: asyncio.sleep(0, result=None),
    )

    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    client._pending["req-pending"] = fut

    await client.stop()
    assert fut.done() is True
    with pytest.raises(RuntimeError, match="bridge stopped"):
        fut.result()


@pytest.mark.asyncio
async def test_bridge_client_stop_cancels_run_task_and_swallows_cancelled_error():
    settings = BridgeConnectionSettings(
        host="127.0.0.1",
        port_start=4475,
        port_end=4475,
        requested_name="agent-requested",
        retry_seconds=0.01,
        request_timeout_seconds=0.2,
    )

    client = make_client(
        settings,
        FakeWebSocket(),
        request_handler=lambda msg: asyncio.sleep(0, result=None),
        connect_func=lambda url: asyncio.sleep(0, result=None),
    )

    client._run_task = asyncio.create_task(asyncio.sleep(10), name="test-run")

    await client.stop()
    assert client._run_task is None


@pytest.mark.asyncio
async def test_bridge_client_stop_ignores_ws_close_exception_and_still_fails_pending():
    settings = BridgeConnectionSettings(
        host="127.0.0.1",
        port_start=4475,
        port_end=4475,
        requested_name="agent-requested",
        retry_seconds=0.01,
        request_timeout_seconds=0.2,
    )

    class ExplodingWebSocket:
        async def close(self):
            raise RuntimeError("close failed")

    client = make_client(
        settings,
        FakeWebSocket(),
        request_handler=lambda msg: asyncio.sleep(0, result=None),
        connect_func=lambda url: asyncio.sleep(0, result=None),
    )

    client._ws = ExplodingWebSocket()  # type: ignore[assignment]

    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    client._pending["req-pending"] = fut

    # close() raises, but stop should swallow it.
    await client.stop()
    assert client._ws is None
    assert fut.done() is True
    with pytest.raises(RuntimeError, match="bridge stopped"):
        fut.result()


@pytest.mark.asyncio
async def test_bridge_client_run_loop_resets_state_and_fails_pending_on_disconnect():
    settings = BridgeConnectionSettings(
        host="127.0.0.1",
        port_start=4475,
        port_end=4475,
        requested_name="agent-requested",
        retry_seconds=0.01,
        request_timeout_seconds=0.2,
    )

    ws = FakeWebSocket(incoming=[])
    client = make_client(
        settings, ws, request_handler=lambda msg: asyncio.sleep(0, result=None)
    )

    calls: list[str] = []

    async def fake_fail_all_pending(error: str) -> None:
        calls.append(error)

    async def fake_connect_and_handshake() -> None:
        # Simulate a connected state and a recv task that exits quickly.
        client._ws = ws  # ty:ignore[invalid-assignment]
        client._assigned_name = "agent-assigned"
        client._connected_agents = [{"name": "a"}]
        client._recv_task = asyncio.create_task(asyncio.sleep(0), name="test-recv")
        # End the outer loop after this iteration.
        client._stopping.set()

    client._fail_all_pending = fake_fail_all_pending  # type: ignore[method-assign]
    client._connect_and_handshake = fake_connect_and_handshake  # type: ignore[method-assign]

    await client._run_loop()

    assert client.assigned_name is None
    assert client._connected_agents == []
    assert ws.closed is True
    assert client._ws is None
    assert "bridge disconnected" in calls


@pytest.mark.asyncio
async def test_bridge_client_run_loop_retries_after_error(monkeypatch):
    settings = BridgeConnectionSettings(
        host="127.0.0.1",
        port_start=4475,
        port_end=4475,
        requested_name="agent-requested",
        retry_seconds=0.01,
        request_timeout_seconds=0.2,
    )

    client = make_client(
        settings,
        FakeWebSocket(),
        request_handler=lambda msg: asyncio.sleep(0, result=None),
        connect_func=lambda url: asyncio.sleep(0, result=None),
    )

    attempts = {"count": 0}
    sleeps: list[float] = []

    real_sleep = asyncio.sleep

    async def fast_sleep(delay: float):
        sleeps.append(delay)
        # Yield once without actually delaying the test.
        await real_sleep(0)

    async def fake_connect_and_handshake() -> None:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("boom")
        # Second attempt succeeds and then stops the loop.
        client._recv_task = asyncio.create_task(asyncio.sleep(0), name="test-recv")
        client._stopping.set()

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    client._connect_and_handshake = fake_connect_and_handshake  # type: ignore[method-assign]

    await client._run_loop()

    assert attempts["count"] == 2
    assert settings.retry_seconds in sleeps
