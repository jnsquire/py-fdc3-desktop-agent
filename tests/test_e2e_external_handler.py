"""Integration test for external handler registration via WebSocket."""

import asyncio
import json
import warnings
import pytest
import socket
from uuid import uuid4
from datetime import datetime

# Suppress known DeprecationWarnings from websockets/uvicorn internals (temporary)
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=r"websockets\.legacy is deprecated.*",
)
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=r"websockets\.server\.WebSocketServerProtocol is deprecated",
)
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=r"remove second argument of ws_handler",
)

# Use httpx for async WebSocket testing if available
pytest_plugins = ["pytest_asyncio"]


def _get_free_port(host: str = "127.0.0.1") -> int:
    """Get an ephemeral free TCP port from the OS."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


@pytest.mark.asyncio
async def test_external_handler_registration_e2e():
    """End-to-end test: connect via WebSocket, do WCP handshake, register handler."""
    from websockets.asyncio.client import connect
    from fdc3.desktop_agent.server import create_app
    from fdc3.desktop_agent.config import DesktopAgentConfig
    import uvicorn
    import threading

    started = threading.Event()

    # Create app with permissive config
    port = _get_free_port("127.0.0.1")
    config = DesktopAgentConfig(
        host="127.0.0.1",
        port=port,
        db_path=":memory:",
        allowed_origins=["*"],
    )
    app = create_app(config)

    # Wrap the ASGI app so we can signal readiness from the lifespan startup.
    async def app_with_start_signal(scope, receive, send):
        if scope["type"] == "lifespan":

            async def send_wrapper(message):
                if message.get("type") == "lifespan.startup.complete":
                    started.set()
                await send(message)

            return await app(scope, receive, send_wrapper)

        return await app(scope, receive, send)

    # Run server in background thread
    server_config = uvicorn.Config(
        app_with_start_signal, host="127.0.0.1", port=port, log_level="warning"
    )
    server = uvicorn.Server(server_config)

    def run_server():
        asyncio.run(server.serve())

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()

    # Wait for server startup without polling sleeps.
    if not await asyncio.to_thread(started.wait, 2.0):
        raise RuntimeError("Server did not signal startup in time")

    try:
        # Connect WebSocket client
        async with connect(f"ws://127.0.0.1:{port}/ws") as ws:
            connection_uuid = str(uuid4())
            instance_uuid = str(uuid4())

            # Send WCP1Hello
            wcp1 = {
                "type": "WCP1Hello",
                "payload": {
                    "identityUrl": "http://localhost:9999/test-handler",
                    "actualUrl": "http://localhost:9999/test-handler",
                    "fdc3Version": "2.0",
                },
                "meta": {
                    "connectionAttemptUuid": connection_uuid,
                    "timestamp": datetime.now().isoformat(),
                },
            }
            await ws.send(json.dumps(wcp1))

            # Receive WCP3Handshake
            wcp3_raw = await asyncio.wait_for(ws.recv(), timeout=5)
            wcp3 = json.loads(wcp3_raw)
            assert wcp3["type"] == "WCP3Handshake", (
                f"Expected WCP3Handshake, got {wcp3}"
            )

            # Send WCP4ValidateAppIdentity (external handler self-registration)
            wcp4 = {
                "type": "WCP4ValidateAppIdentity",
                "payload": {
                    "appId": "external-handler:test-handler",
                    "instanceId": str(uuid4()),
                    "instanceUuid": instance_uuid,
                },
                "meta": {
                    "connectionAttemptUuid": connection_uuid,
                    "timestamp": datetime.now().isoformat(),
                },
            }
            await ws.send(json.dumps(wcp4))

            # Receive WCP5ValidateAppIdentityResponse
            wcp5_raw = await asyncio.wait_for(ws.recv(), timeout=5)
            wcp5 = json.loads(wcp5_raw)
            assert wcp5["type"] == "WCP5ValidateAppIdentityResponse", (
                f"Expected WCP5, got {wcp5}"
            )

            # Now in DACP phase - send registerExternalHandler
            request_uuid = str(uuid4())
            register_msg = {
                "type": "registerExternalHandler",
                "payload": {
                    "handler_id": "test-handler",
                    "intents": ["Test.Intent"],
                    "priority": 5,
                    "metadata": {},
                },
                "meta": {
                    "requestUuid": request_uuid,
                    "timestamp": datetime.now().isoformat(),
                },
            }
            await ws.send(json.dumps(register_msg))

            # Receive registerExternalHandlerResponse
            resp_raw = await asyncio.wait_for(ws.recv(), timeout=5)
            resp = json.loads(resp_raw)
            assert resp["type"] == "registerExternalHandlerResponse", (
                f"Expected response, got {resp}"
            )
            assert "handler_uuid" in resp.get("payload", {}), (
                f"Missing handler_uuid in {resp}"
            )
            handler_uuid = resp["payload"]["handler_uuid"]
            print(f"SUCCESS: Registered handler with UUID: {handler_uuid}")

            # Unregister
            unreg_msg = {
                "type": "unregisterExternalHandler",
                "payload": {"handler_uuid": handler_uuid},
                "meta": {
                    "requestUuid": str(uuid4()),
                    "timestamp": datetime.now().isoformat(),
                },
            }
            await ws.send(json.dumps(unreg_msg))

            unreg_resp_raw = await asyncio.wait_for(ws.recv(), timeout=5)
            unreg_resp = json.loads(unreg_resp_raw)
            assert unreg_resp["type"] == "unregisterExternalHandlerResponse"
            print("SUCCESS: Unregistered handler")

    finally:
        server.should_exit = True
        # Avoid fixed sleeps: wait briefly for server thread to exit.
        await asyncio.to_thread(thread.join, 1.0)


if __name__ == "__main__":
    asyncio.run(test_external_handler_registration_e2e())
