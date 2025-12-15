"""Async client for connecting external intent handlers to the desktop agent.

This module implements the `FDC3Client` used to connect external handlers
to the desktop agent.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypedDict

from websockets.asyncio.client import connect, ClientConnection

logger = logging.getLogger(__name__)


class ForwardedIntentPayload(TypedDict, total=False):
    request_uuid: str
    intent: str
    context: Dict[str, Any]
    source: Dict[str, Any]
    timeout: int


class MessageDict(TypedDict, total=False):
    type: str
    payload: Dict[str, Any]


MessageHandler = Callable[[SimpleNamespace], Awaitable[None]]


class FDC3Client:
    """Client for external intent handlers to connect to the FDC3 desktop agent.

    This client handles the WCP handshake, handler registration, and intent
    forwarding/result protocol.
    """

    def __init__(
        self,
        agent_url: str,
        handler_id: str = "external-handler",
        *,
        ping_interval: float = 20.0,
    ):
        self.agent_url = agent_url
        self.handler_id = handler_id
        self.ping_interval = ping_interval
        self._ws: Optional[ClientConnection] = None
        self._recv_task: Optional[asyncio.Task] = None
        self._ping_task: Optional[asyncio.Task] = None
        self._on_intent: Optional[MessageHandler] = None
        self._pending_responses: Dict[str, asyncio.Future] = {}
        self._handlers: Dict[str, Dict[str, Any]] = {}
        self._running = False
        self._instance_uuid: Optional[str] = None
        self._handshake_complete = asyncio.Event()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def connect(self) -> None:
        """Connect to the agent and complete WCP handshake."""
        logger.info(f"Connecting to agent at {self.agent_url}")
        self._ws = await connect(self.agent_url)
        self._running = True
        self._recv_task = asyncio.create_task(self._recv_loop())
        self._ping_task = asyncio.create_task(self._ping_loop())

        # Perform WCP handshake
        await self._wcp_handshake()

    async def _wcp_handshake(self) -> None:
        """Perform WCP handshake: WCP1Hello -> WCP3Handshake -> WCP4 -> WCP5."""
        assert self._ws is not None

        connection_uuid = str(uuid.uuid4())
        self._instance_uuid = str(uuid.uuid4())

        # Send WCP1Hello
        wcp1 = {
            "type": "WCP1Hello",
            "payload": {
                "identityUrl": f"http://external-handler.local/{self.handler_id}",
                "actualUrl": f"http://external-handler.local/{self.handler_id}",
                "fdc3Version": "2.0",
            },
            "meta": {
                "connectionAttemptUuid": connection_uuid,
                "timestamp": datetime.now().isoformat(),
            },
        }
        await self._ws.send(json.dumps(wcp1))
        logger.debug("Sent WCP1Hello")

        # Wait for WCP3Handshake (handled in _handle_message)
        # Then send WCP4ValidateAppIdentity
        # The handshake_complete event will be set when WCP5 is received

    async def close(self) -> None:
        self._running = False
        if self._recv_task:
            self._recv_task.cancel()
        if self._ping_task:
            self._ping_task.cancel()
        if self._ws:
            await self._ws.close()

    async def _ping_loop(self) -> None:
        while self._running and self._ws:
            try:
                await self._ws.ping()
            except Exception:
                logger.debug("Ping failed")
            await asyncio.sleep(self.ping_interval)

    async def _recv_loop(self) -> None:
        assert self._ws is not None
        try:
            while True:
                try:
                    raw = await self._ws.recv()
                except Exception as exc:
                    # Connection closed or recv error
                    logger.debug("WebSocket recv error or closed: %s", exc)
                    break

                try:
                    msg = json.loads(raw)
                except Exception:
                    logger.exception("Failed to parse message from agent")
                    continue

                await self._handle_message(msg)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Receive loop error")

    async def _handle_message(self, msg: MessageDict) -> None:
        t = msg.get("type")
        payload = msg.get("payload") or {}
        meta = msg.get("meta") or {}
        logger.debug(f"Received message type={t} meta={meta}")

        # WCP handshake messages
        if t == "WCP3Handshake":
            # Received handshake, now send WCP4ValidateAppIdentity
            await self._send_wcp4_validate(
                meta.get("connectionAttemptUuid") or str(uuid.uuid4())
            )

        elif t == "WCP5ValidateAppIdentityResponse":
            # Handshake complete
            self._instance_uuid = payload.get("instanceUuid")
            logger.info(f"WCP handshake complete, instanceUuid={self._instance_uuid}")
            self._handshake_complete.set()

        elif t == "WCP5ValidateAppIdentityFailedResponse":
            logger.error(f"WCP handshake failed: {payload.get('message')}")
            self._handshake_complete.set()  # Unblock waiters even on failure

        # DACP messages
        elif t == "registerExternalHandlerResponse":
            # Resolve pending register future by requestUuid
            request_uuid = meta.get("requestUuid", "")
            handler_uuid = payload.get("handler_uuid")
            logger.debug(
                f"Received registerExternalHandlerResponse: requestUuid={request_uuid} "
                f"handler_uuid={handler_uuid} pending_keys={list(self._pending_responses.keys())}"
            )
            if request_uuid:
                fut = self._pending_responses.pop(request_uuid, None)
                if fut and not fut.done():
                    if payload.get("error"):
                        fut.set_exception(Exception(payload.get("error")))
                    else:
                        fut.set_result(handler_uuid)
                else:
                    logger.warning(f"No pending future for requestUuid={request_uuid}")

        elif t == "unregisterExternalHandlerResponse":
            request_uuid = meta.get("requestUuid", "")
            if request_uuid:
                fut = self._pending_responses.pop(request_uuid, None)
                if fut and not fut.done():
                    if payload.get("error"):
                        fut.set_exception(Exception(payload.get("error")))
                    else:
                        fut.set_result(None)

        elif t == "forwardedIntent":
            # payload: request_uuid, intent, context, source, timeout
            if self._on_intent and isinstance(payload, dict):
                req_payload: ForwardedIntentPayload = payload  # type: ignore[arg-type]
                req = SimpleNamespace(**req_payload)
                await self._on_intent(req)

        else:
            logger.debug(f"Unhandled message type: {t}")

    async def _send_wcp4_validate(self, connection_uuid: str) -> None:
        """Send WCP4ValidateAppIdentity for self-registration."""
        assert self._ws is not None
        wcp4 = {
            "type": "WCP4ValidateAppIdentity",
            "payload": {
                "appId": f"external-handler:{self.handler_id}",
                "instanceId": str(uuid.uuid4()),
                "instanceUuid": self._instance_uuid,
            },
            "meta": {
                "connectionAttemptUuid": connection_uuid,
                "timestamp": datetime.now().isoformat(),
            },
        }
        await self._ws.send(json.dumps(wcp4))
        logger.debug("Sent WCP4ValidateAppIdentity")

    async def wait_for_handshake(self, timeout: float = 10.0) -> bool:
        """Wait for WCP handshake to complete.

        Returns:
            True if handshake succeeded, False if timed out.
        """
        try:
            await asyncio.wait_for(self._handshake_complete.wait(), timeout=timeout)
            return self._instance_uuid is not None
        except asyncio.TimeoutError:
            logger.error("WCP handshake timed out")
            return False

    async def register_handler(
        self,
        handler_id: str,
        intents: List[str],
        *,
        priority: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
        timeout: float = 5.0,
    ) -> str:
        """Register an external handler and return agent-assigned handler_uuid."""
        assert self._ws is not None, "Not connected"

        # Wait for handshake to complete first
        if not self._handshake_complete.is_set():
            if not await self.wait_for_handshake():
                raise Exception("WCP handshake failed or timed out")

        request_uuid = str(uuid.uuid4())
        payload = {
            "handler_id": handler_id,
            "intents": intents,
            "priority": priority,
            "metadata": metadata or {},
        }

        msg = {
            "type": "registerExternalHandler",
            "payload": payload,
            "meta": {
                "requestUuid": request_uuid,
                "timestamp": datetime.now().isoformat(),
            },
        }
        logger.debug(f"Sending registerExternalHandler: requestUuid={request_uuid}")
        await self._ws.send(json.dumps(msg))

        # Create a future to be resolved when response arrives
        fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._pending_responses[request_uuid] = fut

        try:
            handler_uuid = await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending_responses.pop(request_uuid, None)

        # Store handler metadata locally
        self._handlers[handler_uuid] = {"handler_id": handler_id, "intents": intents}
        return handler_uuid

    async def unregister_handler(self, handler_uuid: str, timeout: float = 5.0) -> None:
        """Unregister a handler by its UUID."""
        assert self._ws is not None

        request_uuid = str(uuid.uuid4())
        msg = {
            "type": "unregisterExternalHandler",
            "payload": {"handler_uuid": handler_uuid},
            "meta": {
                "requestUuid": request_uuid,
                "timestamp": datetime.now().isoformat(),
            },
        }
        await self._ws.send(json.dumps(msg))

        # Create a future for response
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._pending_responses[request_uuid] = fut

        try:
            await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"Unregister response timed out for {handler_uuid}")
        finally:
            self._pending_responses.pop(request_uuid, None)

        self._handlers.pop(handler_uuid, None)
        self._handlers.pop(handler_uuid, None)

    def on_intent(self, handler: MessageHandler) -> None:
        self._on_intent = handler

    async def send_intent_result(
        self,
        request_uuid: str,
        *,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        assert self._ws is not None
        payload: Dict[str, Any] = {"request_uuid": request_uuid}
        if result is not None:
            payload["result"] = result
        if error is not None:
            payload["error"] = error
        msg = {"type": "intentResult", "payload": payload}
        await self._ws.send(json.dumps(msg))

    async def run_forever(self) -> None:
        try:
            while self._running:
                await asyncio.sleep(1)
        finally:
            await self.close()
