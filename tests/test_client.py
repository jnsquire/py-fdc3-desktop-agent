import asyncio
from contextlib import suppress
import functools
import json
import pytest
import threading
from unittest.mock import AsyncMock, MagicMock, patch

from fdc3.client import models
from fdc3.client.client import FDC3Client


class TestFDC3ClientInit:
    """Test FDC3Client initialization"""

    def test_init_default_values(self):
        client = FDC3Client("ws://example.com")
        assert client.agent_url == "ws://example.com"
        assert client.handler_id == "external-handler"
        assert client.ping_interval == 20.0
        assert client._ws is None
        assert client._recv_task is None
        assert client._ping_task is None
        assert isinstance(
            client.forwarded_intent_handlers, type(client.forwarded_intent_handlers)
        )
        assert isinstance(client.broadcast_handlers, type(client.broadcast_handlers))
        assert isinstance(
            client.intent_event_handlers, type(client.intent_event_handlers)
        )
        assert client._pending_responses == {}
        assert isinstance(client._pending_responses_lock, type(threading.Lock()))
        assert client._handlers == {}
        assert client._running is False
        assert client._instance_uuid is None
        assert isinstance(client._handshake_complete, asyncio.Event)

    def test_init_custom_values(self):
        client = FDC3Client(
            "ws://example.com", handler_id="custom-handler", ping_interval=10.0
        )
        assert client.agent_url == "ws://example.com"
        assert client.handler_id == "custom-handler"
        assert client.ping_interval == 10.0


class TestFDC3ClientInternalHelpers:
    """Test internal helper methods"""

    def test_ensure_connected_success(self):
        client = FDC3Client("ws://example.com")
        mock_ws = MagicMock()
        client._ws = mock_ws
        assert client._ensure_connected() == mock_ws

    def test_ensure_connected_failure(self):
        client = FDC3Client("ws://example.com")
        with pytest.raises(RuntimeError, match="Not connected"):
            client._ensure_connected()

    @pytest.mark.asyncio
    async def test_ensure_handshake_already_complete(self):
        client = FDC3Client("ws://example.com")
        client._handshake_complete.set()
        await client._ensure_handshake()  # Should not raise

    @pytest.mark.asyncio
    async def test_ensure_handshake_timeout(self):
        client = FDC3Client("ws://example.com")
        with patch.object(client, "wait_for_handshake", return_value=False):
            with pytest.raises(RuntimeError, match="WCP handshake failed or timed out"):
                await client._ensure_handshake(timeout=0.1)

    def test_extract_listener_uuid_string(self):
        assert FDC3Client._extract_listener_uuid("test-uuid") == "test-uuid"

    def test_extract_listener_uuid_dict(self):
        assert FDC3Client._extract_listener_uuid({"root": "test-uuid"}) == "test-uuid"

    def test_extract_listener_uuid_dict_no_root(self):
        input_dict = {"other": "value"}
        assert FDC3Client._extract_listener_uuid(input_dict) == input_dict


class TestFDC3ClientPendingResponses:
    """Test pending response management"""

    @pytest.mark.asyncio
    async def test_register_pending_response(self):
        client = FDC3Client("ws://example.com")
        request_uuid = "test-uuid"

        future = client._register_pending_response(request_uuid)
        assert isinstance(future, asyncio.Future)
        assert request_uuid in client._pending_responses
        assert client._pending_responses[request_uuid][0] == future
        assert client._pending_responses[request_uuid][1] == asyncio.get_running_loop()

    def test_register_pending_response_no_loop(self):
        client = FDC3Client("ws://example.com")
        with pytest.raises(RuntimeError, match="must be called from an async context"):
            client._register_pending_response("test-uuid")

    def test_clear_pending_response(self):
        client = FDC3Client("ws://example.com")
        request_uuid = "test-uuid"
        loop = asyncio.new_event_loop()
        try:
            fut = loop.create_future()
            client._pending_responses[request_uuid] = (fut, loop)
            client._clear_pending_response(request_uuid)
            assert request_uuid not in client._pending_responses
        finally:
            loop.close()

    def test_clear_pending_response_nonexistent(self):
        client = FDC3Client("ws://example.com")
        client._clear_pending_response("nonexistent")  # Should not raise

    @pytest.mark.asyncio
    async def test_fail_all_pending_responses_same_loop(self):
        client = FDC3Client("ws://example.com")
        request_uuid = "test-uuid"
        future = client._register_pending_response(request_uuid)

        client._fail_all_pending_responses(error="test error")

        with pytest.raises(Exception, match="test error"):
            await future

    @pytest.mark.asyncio
    async def test_fail_all_pending_responses_different_loop(self):
        client = FDC3Client("ws://example.com")
        request_uuid = "test-uuid"

        # Mock a different loop
        mock_loop = MagicMock()
        mock_future = MagicMock()
        mock_future.done.return_value = False  # Ensure it's not done
        client._pending_responses[request_uuid] = (mock_future, mock_loop)

        client._fail_all_pending_responses(error="test error")

        # Should call call_soon_threadsafe on the different loop
        mock_loop.call_soon_threadsafe.assert_called_once()

    @pytest.mark.asyncio
    async def test_resolve_pending_response_success(self):
        client = FDC3Client("ws://example.com")
        request_uuid = "test-uuid"
        future = client._register_pending_response(request_uuid)

        client._resolve_pending_response(request_uuid, result="test result")

        assert await future == "test result"

    @pytest.mark.asyncio
    async def test_resolve_pending_response_error(self):
        client = FDC3Client("ws://example.com")
        request_uuid = "test-uuid"
        future = client._register_pending_response(request_uuid)

        client._resolve_pending_response(request_uuid, error="test error")

        with pytest.raises(Exception, match="test error"):
            await future

    @pytest.mark.asyncio
    async def test_resolve_pending_response_different_loop(self):
        client = FDC3Client("ws://example.com")
        request_uuid = "test-uuid"

        # Mock a different loop
        mock_loop = MagicMock()
        mock_future = MagicMock()
        mock_future.done.return_value = False  # Ensure it's not done
        client._pending_responses[request_uuid] = (mock_future, mock_loop)

        client._resolve_pending_response(request_uuid, result="test result")

        # Should call call_soon_threadsafe on the different loop
        mock_loop.call_soon_threadsafe.assert_called_once()

    def test_resolve_pending_response_no_pending(self):
        client = FDC3Client("ws://example.com")
        with patch("fdc3.client.client.logger") as mock_logger:
            client._resolve_pending_response("nonexistent", result="test")
            mock_logger.warning.assert_called()

    def test_resolve_pending_response_already_done(self):
        client = FDC3Client("ws://example.com")
        request_uuid = "test-uuid"
        future = asyncio.Future()
        future.set_result("already done")
        client._pending_responses[request_uuid] = (future, asyncio.get_event_loop())

        with patch("fdc3.client.client.logger") as mock_logger:
            client._resolve_pending_response(request_uuid, result="test")
            mock_logger.warning.assert_called()


class TestFDC3ClientSendAndWait:
    """Test _send_and_wait method"""

    @pytest.mark.asyncio
    async def test_send_and_wait_with_request_uuid(self):
        client = FDC3Client("ws://example.com")
        mock_ws = AsyncMock()
        client._ws = mock_ws

        msg = models.RegisterExternalHandler(
            payload={"handler_id": "h1"}, meta={"requestUuid": "existing-uuid"}
        )

        # Mock the response resolution
        def send_side_effect(data):
            sent_data = json.loads(data)
            request_uuid = sent_data["meta"]["requestUuid"]

            # Resolve the pending response
            async def resolve():
                await asyncio.sleep(0.01)
                client._resolve_pending_response(request_uuid, result="response")

            asyncio.create_task(resolve())

        mock_ws.send.side_effect = send_side_effect

        result = await client._send_and_wait(msg, timeout=1.0)

        mock_ws.send.assert_called_once()
        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["meta"]["requestUuid"] == "existing-uuid"
        # Since requestUuid was already present, timestamp is not added
        assert "timestamp" not in sent_data["meta"]
        assert result == "response"

    @pytest.mark.asyncio
    async def test_send_and_wait_generates_request_uuid(self):
        client = FDC3Client("ws://example.com")
        mock_ws = AsyncMock()
        client._ws = mock_ws

        msg = models.RegisterExternalHandler(payload={"handler_id": "h1"})

        sent_uuid = None

        def capture_send(data):
            nonlocal sent_uuid
            sent_data = json.loads(data)
            request_uuid: str = sent_data["meta"]["requestUuid"]
            sent_uuid = request_uuid

            # _send_and_wait registers the future *after* ws.send completes.
            # Schedule resolution on the next loop turn so the future exists.
            loop = asyncio.get_running_loop()
            loop.call_soon(
                functools.partial(
                    client._resolve_pending_response,
                    request_uuid,
                    result="response",
                )
            )

        mock_ws.send.side_effect = capture_send

        result = await client._send_and_wait(msg, timeout=1.0)

        assert sent_uuid is not None
        assert result == "response"

    @pytest.mark.asyncio
    async def test_send_and_wait_timeout(self):
        client = FDC3Client("ws://example.com")
        mock_ws = AsyncMock()
        client._ws = mock_ws

        msg = models.RegisterExternalHandler(payload={"handler_id": "h1"})

        with pytest.raises(asyncio.TimeoutError):
            await client._send_and_wait(msg, timeout=0.01)

    def test_send_and_wait_not_connected(self):
        client = FDC3Client("ws://example.com")
        msg = models.RegisterExternalHandler(payload={"handler_id": "h1"})

        with pytest.raises(RuntimeError, match="Not connected"):
            asyncio.run(client._send_and_wait(msg))


class TestFDC3ClientContextManager:
    """Test context manager methods"""

    @pytest.mark.asyncio
    async def test_context_manager(self):
        client = FDC3Client("ws://example.com")

        with (
            patch.object(client, "connect", new_callable=AsyncMock) as mock_connect,
            patch.object(client, "close", new_callable=AsyncMock) as mock_close,
        ):
            async with client:
                pass

            mock_connect.assert_called_once()
            mock_close.assert_called_once()


class TestFDC3ClientConnection:
    """Test connection and disconnection"""

    @pytest.mark.asyncio
    async def test_connect_basic(self):
        client = FDC3Client("ws://example.com")

        mock_ws = AsyncMock()

        async def mock_connect(*args, **kwargs):
            return mock_ws

        with (
            patch("fdc3.client.client.connect", side_effect=mock_connect),
            patch.object(client, "_wcp_handshake", new_callable=AsyncMock),
        ):
            try:
                await client.connect()

                assert client._ws == mock_ws
                assert client._running is True
                assert client._recv_task is not None
                assert client._ping_task is not None
            finally:
                await client.close()

    @pytest.mark.asyncio
    async def test_close_cancels_tasks(self):
        client = FDC3Client("ws://example.com")

        # Use real asyncio tasks so type checkers understand the fields.
        gate = asyncio.Event()

        async def _wait_forever() -> None:
            await gate.wait()

        mock_recv_task = asyncio.create_task(_wait_forever())
        mock_ping_task = asyncio.create_task(_wait_forever())
        mock_ws = AsyncMock()

        client._recv_task = mock_recv_task
        client._ping_task = mock_ping_task
        client._ws = mock_ws
        client._running = True

        await client.close()

        assert mock_recv_task.cancelled()
        assert mock_ping_task.cancelled()
        mock_ws.close.assert_called_once()
        assert client._running is False
        assert client._recv_task is None
        assert client._ping_task is None
        assert client._ws is None

    @pytest.mark.asyncio
    async def test_ping_loop(self):
        client = FDC3Client("ws://example.com")
        mock_ws = AsyncMock()
        client._ws = mock_ws
        client._running = True

        pinged = asyncio.Event()

        async def _ping_side_effect():
            pinged.set()

        mock_ws.ping.side_effect = _ping_side_effect

        # Run ping loop briefly
        ping_task = asyncio.create_task(client._ping_loop())
        await asyncio.wait_for(pinged.wait(), timeout=1.0)
        client._running = False
        ping_task.cancel()

        with suppress(asyncio.CancelledError):
            await ping_task

        mock_ws.ping.assert_called()

    @pytest.mark.asyncio
    async def test_recv_loop_processes_messages(self):
        client = FDC3Client("ws://example.com")
        mock_ws = AsyncMock()
        client._ws = mock_ws
        client._running = True

        # Mock receiving a message
        test_message = {"type": "test", "payload": {}, "meta": {}}
        mock_ws.recv.side_effect = [
            json.dumps(test_message),
            Exception("Connection closed"),
        ]

        with patch.object(
            client, "_handle_message", new_callable=AsyncMock
        ) as mock_handle:
            # Run recv loop briefly
            recv_task = asyncio.create_task(client._recv_loop())
            await asyncio.wait_for(recv_task, timeout=1.0)

            mock_handle.assert_called()

    @pytest.mark.asyncio
    async def test_recv_loop_invalid_json(self):
        client = FDC3Client("ws://example.com")
        mock_ws = AsyncMock()
        client._ws = mock_ws
        client._running = True

        mock_ws.recv.side_effect = ["invalid json", Exception("Connection closed")]

        with patch("fdc3.client.client.logger") as mock_logger:
            recv_task = asyncio.create_task(client._recv_loop())
            await asyncio.wait_for(recv_task, timeout=1.0)

            mock_logger.exception.assert_called_with(
                "Failed to parse message JSON from agent"
            )

    @pytest.mark.asyncio
    async def test_recv_loop_invalid_message(self):
        client = FDC3Client("ws://example.com")
        mock_ws = AsyncMock()
        client._ws = mock_ws
        client._running = True

        mock_ws.recv.side_effect = [
            json.dumps({"invalid": "message"}),
            Exception("Connection closed"),
        ]

        with patch("fdc3.client.client.logger") as mock_logger:
            recv_task = asyncio.create_task(client._recv_loop())
            await asyncio.wait_for(recv_task, timeout=1.0)

            mock_logger.exception.assert_called_with(
                "Invalid message envelope from agent"
            )


class TestFDC3ClientWCPHandshake:
    """Test WCP handshake process"""

    @pytest.mark.asyncio
    async def test_wcp_handshake(self):
        client = FDC3Client("ws://example.com")
        mock_ws = AsyncMock()
        client._ws = mock_ws

        await client._wcp_handshake()

        # Should have sent WCP1Hello
        assert mock_ws.send.called
        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["type"] == "WCP1Hello"
        assert "connectionAttemptUuid" in sent_data["meta"]

    @pytest.mark.asyncio
    async def test_send_wcp4_validate(self):
        client = FDC3Client("ws://example.com")
        mock_ws = AsyncMock()
        client._ws = mock_ws
        client._instance_uuid = "test-instance-uuid"

        await client._send_wcp4_validate("test-connection-uuid")

        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["type"] == "WCP4ValidateAppIdentity"
        assert sent_data["payload"]["instanceUuid"] == "test-instance-uuid"

    @pytest.mark.asyncio
    async def test_wait_for_handshake_success(self):
        client = FDC3Client("ws://example.com")
        client._instance_uuid = "test-uuid"

        # Set handshake as complete
        client._handshake_complete.set()

        result = await client.wait_for_handshake(timeout=1.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_for_handshake_timeout(self):
        client = FDC3Client("ws://example.com")

        with patch("fdc3.client.client.logger") as mock_logger:
            result = await client.wait_for_handshake(timeout=0.01)
            assert result is False
            mock_logger.error.assert_called_with("WCP handshake timed out")


class TestFDC3ClientHandlerManagement:
    """Test handler registration and management"""

    @pytest.mark.asyncio
    async def test_register_handler(self):
        client = FDC3Client("ws://example.com")
        client._handshake_complete.set()

        mock_ws = AsyncMock()
        client._ws = mock_ws

        def send_side_effect(data):
            sent_data = json.loads(data)
            request_uuid: str = sent_data["meta"]["requestUuid"]

            loop = asyncio.get_running_loop()
            loop.call_soon(
                functools.partial(
                    client._resolve_pending_response,
                    request_uuid,
                    result="handler-uuid",
                )
            )

        mock_ws.send.side_effect = send_side_effect

        with patch("uuid.uuid4", return_value=MagicMock(hex="testuuid")):
            result = await client.register_handler(
                "test-handler", ["intent1", "intent2"]
            )

        assert result == "handler-uuid"
        assert "handler-uuid" in client._handlers
        assert client._handlers["handler-uuid"]["handler_id"] == "test-handler"

    @pytest.mark.asyncio
    async def test_unregister_handler(self):
        client = FDC3Client("ws://example.com")
        client._handshake_complete.set()

        mock_ws = AsyncMock()
        client._ws = mock_ws

        # Add handler to local storage
        client._handlers["test-uuid"] = {"handler_id": "test", "intents": []}

        with patch.object(
            client, "_send_and_wait", new_callable=AsyncMock, return_value=None
        ):
            await client.unregister_handler("test-uuid")

        assert "test-uuid" not in client._handlers

    @pytest.mark.asyncio
    async def test_unregister_handler_timeout(self):
        client = FDC3Client("ws://example.com")
        client._handshake_complete.set()

        mock_ws = AsyncMock()
        client._ws = mock_ws

        with (
            patch.object(
                client,
                "_send_and_wait",
                new_callable=AsyncMock,
                side_effect=asyncio.TimeoutError,
            ),
            patch("fdc3.client.client.logger") as mock_logger,
        ):
            await client.unregister_handler("test-uuid")

        mock_logger.warning.assert_called()


class TestFDC3ClientListeners:
    """Test context and intent listener management"""

    @pytest.mark.asyncio
    async def test_add_context_listener(self):
        client = FDC3Client("ws://example.com")

        mock_ws = AsyncMock()
        client._ws = mock_ws

        def send_side_effect(data):
            sent_data = json.loads(data)
            request_uuid: str = sent_data["meta"]["requestUuid"]

            loop = asyncio.get_running_loop()
            loop.call_soon(
                functools.partial(
                    client._resolve_pending_response,
                    request_uuid,
                    result="listener-uuid",
                )
            )

        mock_ws.send.side_effect = send_side_effect

        with patch("uuid.uuid4", return_value=MagicMock(hex="testuuid")):
            result = await client.add_context_listener("test-context")

        assert result == "listener-uuid"

    @pytest.mark.asyncio
    async def test_remove_context_listener(self):
        client = FDC3Client("ws://example.com")

        mock_ws = AsyncMock()
        client._ws = mock_ws

        with patch.object(
            client, "_send_and_wait", new_callable=AsyncMock, return_value=None
        ):
            await client.remove_context_listener("listener-uuid")

    @pytest.mark.asyncio
    async def test_remove_context_listener_timeout(self):
        client = FDC3Client("ws://example.com")

        mock_ws = AsyncMock()
        client._ws = mock_ws

        with (
            patch.object(
                client,
                "_send_and_wait",
                new_callable=AsyncMock,
                side_effect=asyncio.TimeoutError,
            ),
            patch("fdc3.client.client.logger") as mock_logger,
        ):
            await client.remove_context_listener("listener-uuid")

        mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_add_intent_listener(self):
        client = FDC3Client("ws://example.com")

        mock_ws = AsyncMock()
        client._ws = mock_ws

        def send_side_effect(data):
            sent_data = json.loads(data)
            request_uuid: str = sent_data["meta"]["requestUuid"]

            loop = asyncio.get_running_loop()
            loop.call_soon(
                functools.partial(
                    client._resolve_pending_response,
                    request_uuid,
                    result="listener-uuid",
                )
            )

        mock_ws.send.side_effect = send_side_effect

        with patch("uuid.uuid4", return_value=MagicMock(hex="testuuid")):
            result = await client.add_intent_listener("test-intent")

        assert result == "listener-uuid"

    @pytest.mark.asyncio
    async def test_remove_intent_listener(self):
        client = FDC3Client("ws://example.com")

        mock_ws = AsyncMock()
        client._ws = mock_ws

        with patch.object(
            client, "_send_and_wait", new_callable=AsyncMock, return_value=None
        ):
            await client.remove_intent_listener("listener-uuid")

    @pytest.mark.asyncio
    async def test_remove_intent_listener_timeout(self):
        client = FDC3Client("ws://example.com")

        mock_ws = AsyncMock()
        client._ws = mock_ws

        with (
            patch.object(
                client,
                "_send_and_wait",
                new_callable=AsyncMock,
                side_effect=asyncio.TimeoutError,
            ),
            patch("fdc3.client.client.logger") as mock_logger,
        ):
            await client.remove_intent_listener("listener-uuid")

        mock_logger.warning.assert_called()


class TestFDC3ClientIntentResults:
    """Test intent result sending"""

    @pytest.mark.asyncio
    async def test_send_intent_result_success(self):
        client = FDC3Client("ws://example.com")
        mock_ws = AsyncMock()
        client._ws = mock_ws

        await client.send_intent_result("request-uuid", result={"test": "data"})

        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["type"] == "intentResult"
        assert sent_data["payload"]["request_uuid"] == "request-uuid"
        assert sent_data["payload"]["result"] == {"test": "data"}

    @pytest.mark.asyncio
    async def test_send_intent_result_error(self):
        client = FDC3Client("ws://example.com")
        mock_ws = AsyncMock()
        client._ws = mock_ws

        await client.send_intent_result("request-uuid", error="test error")

        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["payload"]["error"] == "test error"

    def test_send_intent_result_not_connected(self):
        client = FDC3Client("ws://example.com")

        with pytest.raises(RuntimeError, match="Not connected"):
            asyncio.run(client.send_intent_result("request-uuid"))


class TestFDC3ClientBroadcast:
    """Test broadcasting functionality"""

    @pytest.mark.asyncio
    async def test_broadcast(self):
        client = FDC3Client("ws://example.com")
        client._handshake_complete.set()
        client._instance_uuid = "test-instance"

        mock_ws = AsyncMock()
        client._ws = mock_ws

        test_context = {"type": "test", "data": "value"}
        await client.broadcast(test_context)

        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["type"] == "broadcast"
        assert sent_data["payload"]["context"] == test_context
        assert sent_data["meta"]["source"]["instanceId"] == "test-instance"


class TestFDC3ClientChannelEvents:
    """Test channel event emission"""

    @pytest.mark.asyncio
    async def test_emit_channel_event(self):
        client = FDC3Client("ws://example.com")

        mock_response = MagicMock()
        mock_response.json.return_value = {"data": {"emitChannelEvent": True}}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_response

            await client.emit_channel_event(
                "test-event",
                "test-channel",
                instance_uuid="test-instance",
                context={"test": "data"},
            )

            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert call_args[0][0] == "/graphql"
            request_data = call_args[1]["json"]
            assert "mutation" in request_data["query"]
            assert request_data["variables"]["channelId"] == "test-channel"
            assert request_data["variables"]["eventType"] == "test-event"


class TestFDC3ClientRunForever:
    """Test run_forever method"""

    @pytest.mark.asyncio
    async def test_run_forever(self):
        client = FDC3Client("ws://example.com")
        client._running = True

        # Create a task that completes immediately to simulate recv_task finishing
        async def instant_task():
            pass

        client._recv_task = asyncio.create_task(instant_task())

        with patch.object(client, "close", new_callable=AsyncMock) as mock_close:
            await client.run_forever()
            mock_close.assert_called_once()


class TestFDC3ClientMessageHandling:
    """Test message handling in _handle_message"""

    @pytest.mark.asyncio
    async def test_handle_message_wcp3_handshake(self):
        client = FDC3Client("ws://example.com")

        with patch.object(
            client, "_send_wcp4_validate", new_callable=AsyncMock
        ) as mock_send_wcp4:
            msg = models.Message(
                type="WCP3Handshake", meta={"connectionAttemptUuid": "test-uuid"}
            )

            await client._handle_message(msg)

            mock_send_wcp4.assert_called_once_with("test-uuid")

    @pytest.mark.asyncio
    async def test_handle_message_wcp5_success(self):
        client = FDC3Client("ws://example.com")

        msg = models.Message(
            type="WCP5ValidateAppIdentityResponse",
            payload={"instanceUuid": "test-uuid"},
        )

        await client._handle_message(msg)

        assert client._instance_uuid == "test-uuid"
        assert client._handshake_complete.is_set()

    @pytest.mark.asyncio
    async def test_handle_message_wcp5_failure(self):
        client = FDC3Client("ws://example.com")

        msg = models.Message(
            type="WCP5ValidateAppIdentityFailedResponse",
            payload={"message": "test error"},
        )

        with patch("fdc3.client.client.logger") as mock_logger:
            await client._handle_message(msg)

            mock_logger.error.assert_called_with("WCP handshake failed: test error")
            assert client._handshake_complete.is_set()

    @pytest.mark.asyncio
    async def test_handle_message_register_response_success(self):
        client = FDC3Client("ws://example.com")

        msg = models.Message(
            type="registerExternalHandlerResponse",
            meta={"requestUuid": "test-uuid"},
            payload={"handler_uuid": "handler-uuid"},
        )

        await client._handle_message(msg)

        # Should resolve the pending response
        assert "test-uuid" not in client._pending_responses

    @pytest.mark.asyncio
    async def test_handle_message_register_response_error(self):
        client = FDC3Client("ws://example.com")

        msg = models.Message(
            type="registerExternalHandlerResponse",
            meta={"requestUuid": "test-uuid"},
            payload={"error": "test error"},
        )

        await client._handle_message(msg)

        # Should resolve the pending response with error
        assert "test-uuid" not in client._pending_responses

    @pytest.mark.asyncio
    async def test_handle_message_forwarded_intent(self):
        client = FDC3Client("ws://example.com")

        msg = models.Message(
            type="forwardedIntent",
            payload={
                "request_uuid": "test-uuid",
                "intent": "test-intent",
                "context": {"type": "test"},
            },
        )

        with patch.object(
            client.forwarded_intent_handlers, "emit", new_callable=AsyncMock
        ) as mock_emit:
            await client._handle_message(msg)

            mock_emit.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_message_forwarded_intent_invalid(self):
        client = FDC3Client("ws://example.com")

        msg = models.Message(
            type="forwardedIntent",
            payload={"invalid": "payload"},
            meta={"requestUuid": "test-uuid"},
        )

        with (
            patch.object(
                client, "send_intent_result", new_callable=AsyncMock
            ) as mock_send_result,
            patch("fdc3.client.client.logger") as mock_logger,
        ):
            await client._handle_message(msg)

            mock_send_result.assert_called_once()
            mock_logger.exception.assert_called_with("Invalid forwardedIntent payload")

    @pytest.mark.asyncio
    async def test_handle_message_broadcast_event(self):
        client = FDC3Client("ws://example.com")

        msg = models.Message(
            type="broadcastEvent",
            payload={"context": {"type": "test"}},
            meta={"eventUuid": "test-uuid", "timestamp": "2023-01-01T00:00:00"},
        )

        with patch.object(
            client.broadcast_handlers, "emit", new_callable=AsyncMock
        ) as mock_emit:
            await client._handle_message(msg)

            mock_emit.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_message_intent_event(self):
        client = FDC3Client("ws://example.com")

        msg = models.Message(
            type="intentEvent",
            payload={"intent": "test-intent"},
            meta={"eventUuid": "test-uuid", "timestamp": "2023-01-01T00:00:00"},
        )

        with patch.object(
            client.intent_event_handlers, "emit", new_callable=AsyncMock
        ) as mock_emit:
            await client._handle_message(msg)

            mock_emit.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_message_unknown_type(self):
        client = FDC3Client("ws://example.com")

        msg = models.Message(type="unknownType")

        with patch("fdc3.client.client.logger") as mock_logger:
            await client._handle_message(msg)

            mock_logger.debug.assert_called_with("Unhandled message type: unknownType")
