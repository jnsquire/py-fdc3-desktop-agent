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
from typing import (
    Any,
    Dict,
    List,
    Optional,
    TypedDict,
    Union,
    Callable,
    Awaitable,
)
from .events import EventEmitter

from pydantic import ValidationError
from fdc3.client import models
from fdc3.client.models import parse_message
import urllib.parse
import httpx
from websockets.asyncio.client import connect, ClientConnection

# Re-export commonly used Pydantic message models for handler authors.
# Prefer these models for handler type annotations instead of the older
# TypedDicts defined below.
ForwardedIntentModel = models.ForwardedIntentMessage
BroadcastEventModel = models.BroadcastEvent
IntentEventModel = models.IntentEvent

logger = logging.getLogger(__name__)


class ForwardedIntentPayload(TypedDict, total=False):
    request_uuid: str
    intent: str
    context: Dict[str, Any]
    source: Dict[str, Any]
    timeout: int


class ListenerUuidDict(TypedDict):
    root: str


class AddListenerResponsePayload(TypedDict, total=False):
    listenerUuid: Union[str, ListenerUuidDict]


class BroadcastEventPayload(TypedDict, total=False):
    context: Dict[str, Any]
    instanceUuid: Optional[str]


class IntentEventPayload(TypedDict, total=False):
    intent: str
    context: Optional[Dict[str, Any]]
    originatingApp: Optional[Dict[str, Any]]


class MessageDict(TypedDict, total=False):
    type: str
    payload: Dict[str, Any]


ForwardedIntentHandler = Callable[
    [models.ForwardedIntentMessage], Union[Awaitable[Any], Any]
]

BroadcastHandler = Callable[[models.BroadcastEvent], Union[Awaitable[Any], Any]]

IntentEventHandler = Callable[[models.IntentEvent], Union[Awaitable[Any], Any]]


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
        elif t == "registerExternalHandlerResponse":
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
                fut = self._pending_responses.pop(request_uuid, None)
                if fut and not fut.done():
                    listener = payload.get("listenerUuid")
                    if isinstance(listener, dict) and listener.get("root"):
                        fut.set_result(listener.get("root"))
                    else:
                        fut.set_result(listener)

        elif t == "addIntentListenerResponse":
            request_uuid = meta.get("requestUuid", "")
            if request_uuid:
                fut = self._pending_responses.pop(request_uuid, None)
                if fut and not fut.done():
                    listener = payload.get("listenerUuid")
                    if isinstance(listener, dict) and listener.get("root"):
                        fut.set_result(listener.get("root"))
                    else:
                        fut.set_result(listener)

        elif (
            t == "contextListenerUnsubscribeResponse"
            or t == "intentListenerUnsubscribeResponse"
        ):
            request_uuid = meta.get("requestUuid", "")
            if request_uuid:
                fut = self._pending_responses.pop(request_uuid, None)
                if fut and not fut.done():
                    fut.set_result(None)

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

    async def add_context_listener(
        self, context_type: Optional[str] = None, timeout: float = 5.0
    ) -> str:
        """Register a context listener with the agent and return the listener UUID."""
        assert self._ws is not None, "Not connected"

        request_uuid = str(uuid.uuid4())
        msg = {
            "type": "addContextListener",
            "payload": {"contextType": context_type},
            "meta": {
                "requestUuid": request_uuid,
                "timestamp": datetime.now().isoformat(),
            },
        }
        await self._ws.send(json.dumps(msg))

        fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._pending_responses[request_uuid] = fut

        try:
            listener_uuid = await asyncio.wait_for(fut, timeout=timeout)
            return listener_uuid
        finally:
            self._pending_responses.pop(request_uuid, None)

    async def remove_context_listener(
        self, listener_uuid: str, timeout: float = 5.0
    ) -> None:
        assert self._ws is not None, "Not connected"
        request_uuid = str(uuid.uuid4())
        msg = {
            "type": "contextListenerUnsubscribe",
            "payload": {"listenerUuid": {"root": listener_uuid}},
            "meta": {
                "requestUuid": request_uuid,
                "timestamp": datetime.now().isoformat(),
            },
        }
        await self._ws.send(json.dumps(msg))

        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._pending_responses[request_uuid] = fut
        try:
            await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                f"Unsubscribe response timed out for listener {listener_uuid}"
            )
        finally:
            self._pending_responses.pop(request_uuid, None)

    async def add_intent_listener(self, intent: str, timeout: float = 5.0) -> str:
        assert self._ws is not None, "Not connected"
        request_uuid = str(uuid.uuid4())
        msg = {
            "type": "addIntentListener",
            "payload": {"intent": intent},
            "meta": {
                "requestUuid": request_uuid,
                "timestamp": datetime.now().isoformat(),
            },
        }
        await self._ws.send(json.dumps(msg))

        fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._pending_responses[request_uuid] = fut
        try:
            listener_uuid = await asyncio.wait_for(fut, timeout=timeout)
            return listener_uuid
        finally:
            self._pending_responses.pop(request_uuid, None)

    async def remove_intent_listener(
        self, listener_uuid: str, timeout: float = 5.0
    ) -> None:
        assert self._ws is not None, "Not connected"
        request_uuid = str(uuid.uuid4())
        msg = {
            "type": "intentListenerUnsubscribe",
            "payload": {"listenerUuid": {"root": listener_uuid}},
            "meta": {
                "requestUuid": request_uuid,
                "timestamp": datetime.now().isoformat(),
            },
        }
        await self._ws.send(json.dumps(msg))

        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._pending_responses[request_uuid] = fut
        try:
            await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                f"Unsubscribe response timed out for listener {listener_uuid}"
            )
        finally:
            self._pending_responses.pop(request_uuid, None)

    # Public `EventEmitter` attributes are exposed for subscribing handlers:
    # - `forwarded_intent_handlers`
    # - `broadcast_handlers`
    # - `intent_event_handlers`

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

    # Use `client.forwarded_intent_handlers.add(handler)` to register handlers
    # and `client.forwarded_intent_handlers.remove(handler)` to remove them.

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
        assert self._ws is not None, "Not connected"

        # Ensure handshake complete so the agent knows our identity
        if not self._handshake_complete.is_set():
            if not await self.wait_for_handshake():
                raise Exception("WCP handshake failed or timed out")

        request_uuid = str(uuid.uuid4())
        msg = {
            "type": "broadcast",
            "payload": {"context": context},
            "meta": {
                "requestUuid": request_uuid,
                "timestamp": datetime.now().isoformat(),
                "source": {
                    "appId": f"external-handler:{self.handler_id}",
                    "instanceId": self._instance_uuid,
                },
            },
        }

        logger.debug(f"Sending broadcast request: requestUuid={request_uuid}")
        await self._ws.send(json.dumps(msg))

    async def run_forever(self) -> None:
        try:
            while self._running:
                await asyncio.sleep(1)
        finally:
            await self.close()
