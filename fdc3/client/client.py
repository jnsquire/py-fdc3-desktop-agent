"""Async client for connecting external intent handlers to the desktop agent.

This module implements the `FDC3Client` used to connect external handlers
to the desktop agent.
"""

from __future__ import annotations

import asyncio
import threading
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from .events import EventEmitter

from pydantic import ValidationError
from fdc3.client.models import (
    parse_message,
    Message,
    WCP1Hello,
    WCP4ValidateAppIdentity,
    RegisterExternalHandler,
    UnregisterExternalHandler,
    AddContextListener,
    ContextListenerUnsubscribe,
    AddIntentListener,
    IntentListenerUnsubscribe,
    IntentResult,
    Broadcast,
)
import urllib.parse
import httpx
from websockets.asyncio.client import connect, ClientConnection

logger = logging.getLogger(__name__)


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
        # Public event emitters — multiple handlers may subscribe via `.add()`
        # Handlers will receive validated Pydantic models for known message
        # types.
        self.forwarded_intent_handlers: EventEmitter[Any] = EventEmitter()
        self.broadcast_handlers: EventEmitter[Any] = EventEmitter()
        self.intent_event_handlers: EventEmitter[Any] = EventEmitter()
        # maps request_uuid -> (Future, loop)
        self._pending_responses: Dict[
            str, Tuple[asyncio.Future, asyncio.AbstractEventLoop]
        ] = {}
        self._pending_responses_lock = threading.Lock()
        self._handlers: Dict[str, Dict[str, Any]] = {}
        self._running = False
        self._instance_uuid: Optional[str] = None
        self._handshake_complete = asyncio.Event()

    # ─── Internal helpers ────────────────────────────────────────────────────
    def _ensure_connected(self) -> ClientConnection:
        """Return the websocket connection, raising if not connected."""
        if self._ws is None:
            raise RuntimeError("Not connected")
        return self._ws

    async def _ensure_handshake(self, timeout: float = 10.0) -> None:
        """Wait for WCP handshake if not already complete; raise on failure."""
        if not self._handshake_complete.is_set():
            if not await self.wait_for_handshake(timeout):
                raise RuntimeError("WCP handshake failed or timed out")

    @staticmethod
    def _extract_listener_uuid(value: Any) -> Any:
        """Extract listener UUID, unwrapping a dict with a 'root' key if present."""
        if isinstance(value, dict) and value.get("root"):
            return value["root"]
        return value

    # Pending response helpers
    def _register_pending_response(self, request_uuid: str) -> asyncio.Future:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as exc:
            raise RuntimeError(
                "_register_pending_response must be called from an async context"
            ) from exc

        fut: asyncio.Future = loop.create_future()
        with self._pending_responses_lock:
            self._pending_responses[request_uuid] = (fut, loop)
        return fut

    def _clear_pending_response(self, request_uuid: str) -> None:
        with self._pending_responses_lock:
            self._pending_responses.pop(request_uuid, None)

    def _fail_all_pending_responses(self, *, error: Optional[str] = None) -> None:
        with self._pending_responses_lock:
            items = list(self._pending_responses.items())
            self._pending_responses.clear()

        for request_uuid, (fut, loop) in items:
            if fut.done():
                continue
            if loop is not asyncio.get_running_loop():
                # Use thread-safe scheduling if we're not on the same loop
                try:
                    loop.call_soon_threadsafe(
                        fut.set_exception, Exception(error or "connection closed")
                    )
                except Exception:
                    # best-effort: if scheduling fails, ignore
                    pass
            else:
                fut.set_exception(Exception(error or "connection closed"))

    def _resolve_pending_response(
        self, request_uuid: str, *, result: Any = None, error: Optional[str] = None
    ) -> None:
        with self._pending_responses_lock:
            entry = self._pending_responses.pop(request_uuid, None)

        if not entry:
            logger.warning(f"No pending future for requestUuid={request_uuid}")
            return

        fut, fut_loop = entry
        if fut.done():
            logger.warning(
                "pending future %s already done when resolving response", request_uuid
            )
            return

        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if fut_loop is not None and fut_loop is not current_loop:
            # schedule resolution on the future's loop
            if error is not None:
                fut_loop.call_soon_threadsafe(fut.set_exception, Exception(error))
            else:
                fut_loop.call_soon_threadsafe(fut.set_result, result)
        else:
            if error is not None:
                fut.set_exception(Exception(error))
            else:
                fut.set_result(result)

    async def _send_and_wait(self, msg: Message, timeout: float = 5.0) -> Any:
        """Send a `Message` and wait for the correlated response using its `meta.requestUuid`.

        If the message doesn't include a `requestUuid` in `meta`, one will be generated
        and injected into the message meta.
        """
        ws = self._ensure_connected()

        # Ensure message has a requestUuid in meta
        meta = msg.meta or {}
        request_uuid = meta.get("requestUuid")
        if not request_uuid:
            request_uuid = str(uuid.uuid4())
            meta = {
                **meta,
                "requestUuid": request_uuid,
                "timestamp": datetime.now().isoformat(),
            }
            msg.meta = meta

        await ws.send(msg.model_dump_json())

        fut = self._register_pending_response(request_uuid)
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._clear_pending_response(request_uuid)

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
        connection_uuid = str(uuid.uuid4())
        self._instance_uuid = str(uuid.uuid4())

        # Send WCP1Hello
        wcp1 = WCP1Hello(
            payload={
                "identityUrl": f"http://external-handler.local/{self.handler_id}",
                "actualUrl": f"http://external-handler.local/{self.handler_id}",
                "fdc3Version": "2.0",
            },
            meta={
                "connectionAttemptUuid": connection_uuid,
                "timestamp": datetime.now().isoformat(),
            },
        )
        await self._ensure_connected().send(wcp1.model_dump_json())
        logger.debug("Sent WCP1Hello")
        # Wait for WCP3Handshake (handled in _handle_message)
        # Then send WCP4ValidateAppIdentity
        # The handshake_complete event will be set when WCP5 is received

    async def close(self) -> None:
        self._running = False
        # Cancel and await background tasks so they can clean up properly.
        for task in (self._recv_task, self._ping_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._recv_task = None
        self._ping_task = None
        if self._ws:
            try:
                await self._ws.close()
            finally:
                self._ws = None

    async def _ping_loop(self) -> None:
        while self._running and self._ws:
            try:
                await self._ws.ping()
            except Exception:
                logger.debug("Ping failed")
            await asyncio.sleep(self.ping_interval)

    async def _recv_loop(self) -> None:
        ws = self._ensure_connected()
        try:
            while True:
                try:
                    raw = await ws.recv()
                except Exception as exc:
                    # Connection closed or recv error
                    logger.debug("WebSocket recv error or closed: %s", exc)
                    break

                try:
                    parsed = json.loads(raw)
                except Exception:
                    logger.exception("Failed to parse message JSON from agent")
                    continue

                try:
                    msg = Message.model_validate(parsed)
                except Exception:
                    logger.exception("Invalid message envelope from agent")
                    continue

                await self._handle_message(msg)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Receive loop error")
        finally:
            # Mark client no longer running and fail any pending responses so
            # callers waiting for replies don't hang forever.
            self._running = False
            try:
                self._fail_all_pending_responses(error="connection closed")
            except Exception:
                logger.exception("Error failing pending responses on close")

    async def _handle_message(self, msg: Message) -> None:
        t = msg.type
        payload = msg.payload or {}
        meta = msg.meta or {}
        logger.debug(f"Received message type={t} meta={meta}")

        # WCP handshake messages
        if t == "WCP3Handshake":
            await self._send_wcp4_validate(
                meta.get("connectionAttemptUuid") or str(uuid.uuid4())
            )

        elif t == "WCP5ValidateAppIdentityResponse":
            self._instance_uuid = payload.get("instanceUuid")
            logger.info(f"WCP handshake complete, instanceUuid={self._instance_uuid}")
            self._handshake_complete.set()

        elif t == "WCP5ValidateAppIdentityFailedResponse":
            logger.error(f"WCP handshake failed: {payload.get('message')}")
            self._handshake_complete.set()

        # DACP messages
        elif t in (
            "registerExternalHandlerResponse",
            "unregisterExternalHandlerResponse",
        ):
            request_uuid = meta.get("requestUuid", "")
            if t == "registerExternalHandlerResponse":
                handler_uuid = payload.get("handler_uuid")
                logger.debug(
                    f"Received registerExternalHandlerResponse: requestUuid={request_uuid} "
                    f"handler_uuid={handler_uuid} pending_keys={list(self._pending_responses.keys())}"
                )
            if request_uuid:
                err = payload.get("error")
                if err:
                    self._resolve_pending_response(request_uuid, error=err)
                else:
                    result = (
                        payload.get("handler_uuid")
                        if t == "registerExternalHandlerResponse"
                        else None
                    )
                    self._resolve_pending_response(request_uuid, result=result)

        elif t == "forwardedIntent":
            try:
                model = parse_message(msg)
            except ValidationError as exc:
                logger.exception("Invalid forwardedIntent payload")
                # If we have a request UUID, inform the agent/caller with an intentResult error
                request_uuid = (
                    payload.get("request_uuid")
                    or payload.get("requestUuid")
                    or meta.get("requestUuid")
                    or meta.get("request_uuid")
                )
                if request_uuid:
                    try:
                        await self.send_intent_result(
                            request_uuid,
                            error=f"Invalid forwardedIntent payload: {exc}",
                        )
                    except Exception:
                        logger.exception(
                            "Failed to send intentResult error for forwardedIntent"
                        )
                return

            if model is None:
                logger.debug("No model mapping for forwardedIntent; dropping message")
                return

            await self.forwarded_intent_handlers.emit(model)

        elif t == "addContextListenerResponse":
            request_uuid = meta.get("requestUuid", "")
            if request_uuid:
                listener = self._extract_listener_uuid(payload.get("listenerUuid"))
                self._resolve_pending_response(request_uuid, result=listener)

        elif t == "addIntentListenerResponse":
            request_uuid = meta.get("requestUuid", "")
            if request_uuid:
                listener = self._extract_listener_uuid(payload.get("listenerUuid"))
                self._resolve_pending_response(request_uuid, result=listener)

        elif t in (
            "contextListenerUnsubscribeResponse",
            "intentListenerUnsubscribeResponse",
        ):
            request_uuid = meta.get("requestUuid", "")
            if request_uuid:
                self._resolve_pending_response(request_uuid, result=None)

        elif t == "broadcastEvent":
            try:
                model = parse_message(msg)
            except ValidationError:
                logger.exception("Invalid broadcastEvent payload")
                # Drop unparsable payloads
                return

            if model is None:
                logger.debug("No model mapping for broadcastEvent; dropping message")
                return

            await self.broadcast_handlers.emit(model)

        elif t == "intentEvent":
            try:
                model = parse_message(msg)
            except ValidationError:
                logger.exception("Invalid intentEvent payload")
                # Drop unparsable payloads
                return

            if model is None:
                logger.debug("No model mapping for intentEvent; dropping message")
                return

            await self.intent_event_handlers.emit(model)

        else:
            logger.debug(f"Unhandled message type: {t}")

    async def _send_wcp4_validate(self, connection_uuid: str) -> None:
        """Send WCP4ValidateAppIdentity for self-registration."""
        wcp4 = WCP4ValidateAppIdentity(
            payload={
                "appId": f"external-handler:{self.handler_id}",
                "instanceId": str(uuid.uuid4()),
                "instanceUuid": self._instance_uuid,
            },
            meta={
                "connectionAttemptUuid": connection_uuid,
                "timestamp": datetime.now().isoformat(),
            },
        )
        await self._ensure_connected().send(wcp4.model_dump_json())
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
        await self._ensure_handshake()

        msg = RegisterExternalHandler(
            payload={
                "handler_id": handler_id,
                "intents": intents,
                "priority": priority,
                "metadata": metadata or {},
            },
        )
        handler_uuid = await self._send_and_wait(msg, timeout=timeout)

        # Store handler metadata locally
        self._handlers[handler_uuid] = {"handler_id": handler_id, "intents": intents}
        return handler_uuid

    async def add_context_listener(
        self, context_type: Optional[str] = None, timeout: float = 5.0
    ) -> str:
        """Register a context listener with the agent and return the listener UUID."""
        msg = AddContextListener(payload={"contextType": context_type})
        return await self._send_and_wait(msg, timeout=timeout)

    async def remove_context_listener(
        self, listener_uuid: str, timeout: float = 5.0
    ) -> None:
        msg = ContextListenerUnsubscribe(
            payload={"listenerUuid": {"root": listener_uuid}}
        )
        try:
            await self._send_and_wait(msg, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                f"Unsubscribe response timed out for listener {listener_uuid}"
            )

    async def add_intent_listener(self, intent: str, timeout: float = 5.0) -> str:
        msg = AddIntentListener(payload={"intent": intent})
        return await self._send_and_wait(msg, timeout=timeout)

    async def remove_intent_listener(
        self, listener_uuid: str, timeout: float = 5.0
    ) -> None:
        msg = IntentListenerUnsubscribe(
            payload={"listenerUuid": {"root": listener_uuid}}
        )
        try:
            await self._send_and_wait(msg, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                f"Unsubscribe response timed out for listener {listener_uuid}"
            )

    # Public `EventEmitter` attributes are exposed for subscribing handlers:
    # - `forwarded_intent_handlers`
    # - `broadcast_handlers`
    # - `intent_event_handlers`

    async def unregister_handler(self, handler_uuid: str, timeout: float = 5.0) -> None:
        """Unregister a handler by its UUID."""
        msg = UnregisterExternalHandler(payload={"handler_uuid": handler_uuid})
        try:
            await self._send_and_wait(msg, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"Unregister response timed out for {handler_uuid}")

        self._handlers.pop(handler_uuid, None)

    # Use `client.forwarded_intent_handlers.add(handler)` to register handlers
    # and `client.forwarded_intent_handlers.remove(handler)` to remove them.

    async def send_intent_result(
        self,
        request_uuid: str,
        *,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        ws = self._ensure_connected()
        payload: Dict[str, Any] = {"request_uuid": request_uuid}
        if result is not None:
            payload["result"] = result
        if error is not None:
            payload["error"] = error
        msg = IntentResult(payload=payload)
        await ws.send(msg.model_dump_json())

    async def emit_channel_event(
        self,
        event_type: str,
        channel_id: str,
        *,
        instance_uuid: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit a dev-only channel event via the server GraphQL `emitChannelEvent` mutation.

        This is intended for examples and demos only.
        """
        parsed = urllib.parse.urlparse(self.agent_url)
        scheme = "https" if parsed.scheme == "wss" else "http"
        netloc = parsed.netloc
        base = f"{scheme}://{netloc}"

        mutation = (
            "mutation EmitEvent($channelId: String!, $eventType: String!, $instanceUuid: String, $context: String) {"
            " emitChannelEvent(channelId: $channelId, eventType: $eventType, instanceUuid: $instanceUuid, context: $context) }"
        )

        variables = {
            "channelId": channel_id,
            "eventType": event_type,
            "instanceUuid": instance_uuid,
            "context": json.dumps(context) if context is not None else None,
        }

        async with httpx.AsyncClient(base_url=base, timeout=10.0) as client:
            resp = await client.post(
                "/graphql", json={"query": mutation, "variables": variables}
            )
            resp.raise_for_status()

    async def broadcast(self, context: Dict[str, Any]) -> None:
        """Send a DACP `broadcast` request to the agent to broadcast `context`.

        This will cause the agent to deliver the context to the channel the
        sending instance is currently joined to.
        """
        await self._ensure_handshake()
        ws = self._ensure_connected()

        msg = Broadcast(
            payload={"context": context},
            meta={
                "timestamp": datetime.now().isoformat(),
                "source": {
                    "appId": f"external-handler:{self.handler_id}",
                    "instanceId": self._instance_uuid,
                },
            },
        )

        await ws.send(msg.model_dump_json())

    async def run_forever(self) -> None:
        """Block until the connection closes, then clean up."""
        try:
            if self._recv_task:
                await self._recv_task
        finally:
            await self.close()
