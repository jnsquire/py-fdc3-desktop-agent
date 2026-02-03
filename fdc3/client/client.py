"""Async client for connecting external intent handlers to the desktop agent.

The primary entry point is `FDC3Client`, which
implements the WebSocket Connection Protocol (WCP) handshake and provides
helpers for registering an external handler, subscribing to context/intent
notifications, and sending results.

Typical usage:

    ```python
    import asyncio

    from fdc3.client.client import FDC3Client


    async def main() -> None:
        async with FDC3Client("ws://localhost:8000/ws", handler_id="my-handler") as c:
            await c.register_handler("my-handler", intents=["ViewChart"])

            async def on_intent(msg):
                # msg is a validated Pydantic model for known message types.
                await c.send_intent_result(msg.meta["requestUuid"], result={"type": "fdc3.nothing"})

            c.forwarded_intent_handlers.add(on_intent)
            await c.run_forever()


    asyncio.run(main())
    ```
"""

from __future__ import annotations

import asyncio
import threading
import json
import logging
import uuid
import urllib.parse
from datetime import datetime
from types import TracebackType
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

import httpx
from pydantic import ValidationError
from websockets.asyncio.client import connect, ClientConnection

from .events import EventEmitter
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
from fdc3.models.dacp.dacp import (
    JoinUserChannelRequest,
    JoinUserChannelResponse,
    LeaveCurrentChannelRequest,
    CreatePrivateChannelRequest,
    CreatePrivateChannelResponse,
    CreatePrivateChannelInvitationRequest,
    CreatePrivateChannelInvitationResponse,
    JoinPrivateChannelRequest,
    JoinPrivateChannelResponse,
    LeavePrivateChannelRequest,
    PrivateChannelAddEventListenerRequest,
    PrivateChannelAddEventListenerResponse,
    BroadcastEvent,
    IntentEvent,
    JoinUserChannelRequestPayload,
    CreatePrivateChannelRequestPayload,
    CreatePrivateChannelInvitationRequestPayload,
    JoinPrivateChannelRequestPayload,
    LeavePrivateChannelRequestPayload,
    PrivateChannelAddEventListenerRequestPayload,
)
from fdc3.models.dacp.external_models import ForwardedIntentMessage
from fdc3.models.dacp.enums import PrivateChannelEventListenerTypes
from fdc3.models.identifiers import DisplayMetadata
from fdc3.models.context_types import (
    ChatMessageContext,
    ChatRoomContext,
    MessageContext,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class DACPRequest(Protocol):
    """Protocol for DACP request models with meta attribute."""

    meta: Any

    def model_dump_json(self) -> str: ...


class FDC3Client:
    """Client for external intent handlers to connect to the FDC3 desktop agent.

    The client is designed for *external intent handler* processes that need to:

    - establish a WebSocket connection to an agent;
    - complete the WCP handshake;
    - register/unregister an external handler and supported intents;
    - receive forwarded intents and broadcasts via `EventEmitter`.

    Notes:
        - This is an asyncio-based client.
        - Message handlers registered on the public emitters receive validated
          Pydantic models for known message types.
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
        self.forwarded_intent_handlers: EventEmitter[ForwardedIntentMessage] = (
            EventEmitter()
        )
        self.broadcast_handlers: EventEmitter[BroadcastEvent] = EventEmitter()
        self.intent_event_handlers: EventEmitter[IntentEvent] = EventEmitter()
        self.private_channel_event_handlers: EventEmitter[Dict[str, Any]] = (
            EventEmitter()
        )
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

    @staticmethod
    def _format_channel_id(raw: str) -> str:
        """Ensure a channel id has a prefix (e.g., user:foo)."""
        if ":" in raw:
            return raw
        return f"user:{raw}"

    async def send_dacp_request(
        self, request: DACPRequest, timeout: float = 5.0
    ) -> Any:
        """Send a DACP request model and wait for the correlated response.

        Args:
            request: A Pydantic DACP request model (e.g., generated from the
                `fdc3.models.dacp` module) that includes a `meta.requestUuid`.
            timeout: Seconds to wait for the correlated response.

        Returns:
            The parsed response payload (model or raw dict) returned by the agent.

        Raises:
            asyncio.TimeoutError: If a response is not received within `timeout`.
            RuntimeError: If the client is not connected or handshake not complete.
        """
        await self._ensure_handshake()
        ws = self._ensure_connected()

        request_uuid = getattr(request.meta.requestUuid, "root", None)
        if not request_uuid:
            request_uuid = str(request.meta.requestUuid)

        fut = self._register_pending_response(request_uuid)
        try:
            await ws.send(request.model_dump_json())
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._clear_pending_response(request_uuid)

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
        # Args/doc are intentionally present for internal clarity — this helper
        # is used across public request helpers.
        #
        # Args:
        #     msg: A validated `Message` RootModel instance.
        #     timeout: Seconds to wait for the correlated response.
        #
        # Returns:
        #     The correlated response payload or model.
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

    async def __aenter__(self) -> "FDC3Client":
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.close()

    async def connect(self) -> None:
        """Connect to the agent and complete the WCP handshake.

        After this returns successfully, ``wait_for_handshake`` should be
        satisfied and request/response helper methods (e.g. ``register_handler``) can be used.

        Raises:
            Exception: If the websocket connection or handshake fails.
        """
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
        """Close the websocket connection and stop background tasks."""
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

        # Try to parse into a known model early. Not all message types are in _MODEL_MAP.
        model = None
        try:
            model = parse_message(msg)
        except ValidationError:
            # We log the error but don't exit, as some types might handle validation differently
            # or we might want to still resolve a pending response if possible.
            logger.debug(f"Parsing failed for {t}")

        # 1. SPECIAL: WCP Handshake & Identity Management
        if t == "WCP3Handshake":
            await self._send_wcp4_validate(
                meta.get("connectionAttemptUuid") or str(uuid.uuid4())
            )
            return

        if t == "WCP5ValidateAppIdentityResponse":
            self._instance_uuid = payload.get("instanceUuid")
            logger.info(f"WCP handshake complete, instanceUuid={self._instance_uuid}")
            self._handshake_complete.set()
            return

        if t == "WCP5ValidateAppIdentityFailedResponse":
            logger.error(f"WCP handshake failed: {payload.get('message')}")
            self._handshake_complete.set()
            return

        # 2. EVENTS: Emit to appropriate event emitters
        if t == "privateChannelEvent":
            await self.private_channel_event_handlers.emit(payload)
            return

        if t == "broadcastEvent" and isinstance(model, BroadcastEvent):
            await self.broadcast_handlers.emit(model)
            return

        if t == "intentEvent" and isinstance(model, IntentEvent):
            await self.intent_event_handlers.emit(model)
            return

        if t == "forwardedIntent":
            if isinstance(model, ForwardedIntentMessage):
                await self.forwarded_intent_handlers.emit(model)
                return

            # Error handling for invalid forwardedIntent
            logger.exception("Invalid forwardedIntent payload")
            req_uuid = self._extract_listener_uuid(
                payload.get("request_uuid")
                or payload.get("requestUuid")
                or meta.get("requestUuid")
                or meta.get("request_uuid")
            )
            if req_uuid:
                try:
                    await self.send_intent_result(
                        req_uuid, error="Invalid forwardedIntent payload"
                    )
                except Exception:
                    logger.exception("Failed to send intentResult error")
            return

        # 3. RESPONSES: Resolve pending futures registered via send_dacp_request
        request_uuid = self._extract_listener_uuid(meta.get("requestUuid"))
        if request_uuid:
            error = payload.get("error")
            if error:
                self._resolve_pending_response(request_uuid, error=error)
                return

            # Consolidate resolution result mapping
            result: Any = model or payload  # Default to parsed model or raw payload

            # Some types require extracting specific result fields from the payload
            if t in ("addContextListenerResponse", "addIntentListenerResponse"):
                listener_uuid = payload.get("listenerUuid")
                if model and hasattr(model, "payload"):
                    listener_uuid = getattr(
                        model.payload, "listenerUuid", listener_uuid
                    )
                result = self._extract_listener_uuid(listener_uuid)

            elif t == "registerExternalHandlerResponse":
                result = payload.get("handler_uuid")
                if model and hasattr(model, "payload"):
                    result = getattr(model.payload, "handler_uuid", result)

            elif t in (
                "contextListenerUnsubscribeResponse",
                "intentListenerUnsubscribeResponse",
                "unregisterExternalHandlerResponse",
            ):
                result = None

            self._resolve_pending_response(request_uuid, result=result)
            return

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
        """Register an external handler and return the agent-assigned handler UUID.

        Args:
            handler_id: A stable identifier for this handler.
            intents: Intent names the handler can service.
            priority: Higher values may win in resolver selection (agent-dependent).
            metadata: Arbitrary handler metadata for discovery/UI.
            timeout: Seconds to wait for the correlated response.

        Returns:
            The agent-assigned handler UUID.

        See also:
            Use :attr:`forwarded_intent_handlers` to receive forwarded intents.
        """
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
        """Register a context listener and return the listener UUID.

        Args:
            context_type: If provided, only contexts of this FDC3 type are delivered.
            timeout: Seconds to wait for the correlated response.

        Returns:
            Listener UUID that can be passed to ``remove_context_listener``.
        """
        msg = AddContextListener(payload={"contextType": context_type})
        return await self._send_and_wait(msg, timeout=timeout)

    async def remove_context_listener(
        self, listener_uuid: str, timeout: float = 5.0
    ) -> None:
        """Unsubscribe a previously-registered context listener."""
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
        """Register an intent listener and return its listener UUID.

        Args:
            intent: The intent name to listen for (e.g., "ViewChart").
            timeout: Seconds to wait for the agent's response.

        Returns:
            Listener UUID that can be passed to ``remove_intent_listener``.
        """
        msg = AddIntentListener(payload={"intent": intent})
        return await self._send_and_wait(msg, timeout=timeout)

    async def remove_intent_listener(
        self, listener_uuid: str, timeout: float = 5.0
    ) -> None:
        """Unsubscribe a previously-registered intent listener.

        Args:
            listener_uuid: The UUID returned from ``add_intent_listener``.
            timeout: Seconds to wait for the agent's response.
        """
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
        """Unregister a handler by its UUID.

        Args:
            handler_uuid: The UUID returned from ``register_handler``.
            timeout: Seconds to wait for the agent's response.
        """
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
        """Send a result for a previously forwarded intent.

        Args:
            request_uuid: The request UUID from the forwarded intent message meta.
            result: Optional result payload.
            error: Optional error string.

        Notes:
            Many handler processes call this from a callback registered via
            :attr:`forwarded_intent_handlers`.
        """
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

    async def create_user_channel(
        self,
        channel_id: str,
        *,
        display_metadata: Optional[DisplayMetadata] = None,
    ) -> None:
        """Create a user channel via the agent GraphQL API.

        Args:
            channel_id: The desired channel identifier (e.g., "demo" or
                "user:demo").
            display_metadata: Optional `DisplayMetadata` providing a human name
                and color for the channel.

        Raises:
            httpx.HTTPError: If the GraphQL request fails.
        """
        channel_id = self._format_channel_id(channel_id)
        parsed = urllib.parse.urlparse(self.agent_url)
        scheme = "https" if parsed.scheme == "wss" else "http"
        base = f"{scheme}://{parsed.netloc}"

        if display_metadata is None:
            display_metadata = DisplayMetadata(name=channel_id, color="#000000")

        mutation = (
            "mutation CreateChannel($input: CreateChannelInput!) {"
            " createChannel(input: $input) { id } }"
        )

        variables = {
            "input": {
                "channelId": channel_id,
                "channelType": "user",
                "displayMetadata": display_metadata.model_dump(exclude_none=True),
            }
        }

        async with httpx.AsyncClient(base_url=base, timeout=10.0) as client:
            resp = await client.post(
                "/graphql", json={"query": mutation, "variables": variables}
            )
            resp.raise_for_status()

    async def join_user_channel(
        self,
        channel_id: str,
        *,
        auto_create: bool = False,
    ) -> JoinUserChannelResponse:
        """Join a user channel, optionally auto-creating it if missing.

        Args:
            channel_id: The channel identifier (e.g., "demo" or "user:demo").
            auto_create: If True and the channel doesn't exist, create it first.

        Returns:
            The JoinUserChannelResponse containing the joined channel details.

        Raises:
            Exception: If the channel doesn't exist and auto_create is False.
        """
        channel_id = self._format_channel_id(channel_id)
        request = JoinUserChannelRequest(
            type="joinUserChannel",
            payload=JoinUserChannelRequestPayload(channelId=channel_id),
        )
        try:
            return await self.send_dacp_request(request)
        except Exception as exc:
            if auto_create and (
                "NoChannelFound" in str(exc)
                or "NoChannelFound" in getattr(exc, "args", [""])[0]
            ):
                await self.create_user_channel(channel_id)
                return await self.send_dacp_request(request)
            raise

    async def leave_current_channel(self) -> None:
        """Leave the currently joined channel.

        This sends a DACP `leaveCurrentChannel` request to the agent.

        Raises:
            Exception: If the agent returns an error or the request fails.
        """
        # LeaveCurrentChannelRequest requires the literal `type` field
        request = LeaveCurrentChannelRequest(type="leaveCurrentChannel")
        await self.send_dacp_request(request)

    async def create_private_channel(
        self, display_name: Optional[str] = None
    ) -> CreatePrivateChannelResponse:
        """Create a private channel and return the response.

        Args:
            display_name: Optional human-readable name for the channel.

        Returns:
            The CreatePrivateChannelResponse containing the new channel's metadata.
        """
        display_metadata = DisplayMetadata(name=display_name) if display_name else None
        request = CreatePrivateChannelRequest(
            type="createPrivateChannel",
            payload=CreatePrivateChannelRequestPayload(
                displayMetadata=display_metadata
            ),
        )
        return await self.send_dacp_request(request)

    async def create_private_channel_invite(
        self, channel_id: str, instance_id: Optional[str] = None
    ) -> CreatePrivateChannelInvitationResponse:
        """Create a private channel invitation.

        Args:
            channel_id: The private channel to create an invitation for.
            instance_id: Optional target instance to restrict the invitation to.

        Returns:
            The CreatePrivateChannelInvitationResponse containing the invitation token.
        """
        request = CreatePrivateChannelInvitationRequest(
            type="createPrivateChannelInvitation",
            payload=CreatePrivateChannelInvitationRequestPayload(
                channelId=channel_id, instanceId=instance_id
            ),
        )
        return await self.send_dacp_request(request)

    async def join_private_channel(
        self, channel_id: str, token: str
    ) -> JoinPrivateChannelResponse:
        """Join a private channel using an invitation token.

        Args:
            channel_id: The private channel to join.
            token: The invitation token received from the channel creator.

        Returns:
            The JoinPrivateChannelResponse confirming the join.
        """
        request = JoinPrivateChannelRequest(
            type="joinPrivateChannel",
            payload=JoinPrivateChannelRequestPayload(
                channelId=channel_id, invitationToken=token
            ),
        )
        return await self.send_dacp_request(request)

    async def leave_private_channel(self, channel_id: str) -> None:
        """Leave a private channel.

        Args:
            channel_id: The private channel to leave.
        """
        request = LeavePrivateChannelRequest(
            type="leavePrivateChannel",
            payload=LeavePrivateChannelRequestPayload(channelId=channel_id),
        )
        await self.send_dacp_request(request)

    async def add_private_channel_event_listener(
        self,
        channel_id: str,
        *,
        event_type: Optional[PrivateChannelEventListenerTypes] = None,
    ) -> PrivateChannelAddEventListenerResponse:
        """Subscribe to private channel events for a channel.

        Args:
            channel_id: The private channel to subscribe to.
            event_type: Optionally filter to a specific event type.

        Returns:
            The PrivateChannelAddEventListenerResponse containing listener details.
        """
        request = PrivateChannelAddEventListenerRequest(
            type="privateChannelAddEventListener",
            payload=PrivateChannelAddEventListenerRequestPayload(
                channelId=channel_id, eventType=event_type
            ),
        )
        return await self.send_dacp_request(request)

    # ─── Chat helpers ──────────────────────────────────────────────────────
    async def build_message(self, text: str) -> MessageContext:
        """Build a minimal `fdc3.message` payload for a chat message.

        Args:
            text: The plain text content of the message.

        Returns:
            A `MessageContext` object ready for use in chat operations.
        """
        return MessageContext(type="fdc3.message", text={"text/plain": text})

    async def get_chat_room(
        self,
        channel_id: str,
        *,
        provider_name: Optional[str] = None,
        auto_create: bool = False,
    ) -> ChatRoomContext:
        """Return a `fdc3.chat.room` object for a given channel id.

        Args:
            channel_id: The channel identifier to build a chat room for.
            provider_name: Optional provider name to include in the room.
            auto_create: If True, attempt to create a user channel on the agent
                (best-effort) before returning the room object.

        Returns:
            A `ChatRoomContext` representing the chat room for the given
            `channel_id`.
        """
        if auto_create:
            try:
                await self.create_user_channel(channel_id)
            except Exception:
                # best-effort: ignore failures creating the user channel
                pass

        room: ChatRoomContext = ChatRoomContext(
            type="fdc3.chat.room",
            providerName=(provider_name or self.handler_id),
            id={"channelId": channel_id},
        )
        return room

    async def send_chat_message(
        self,
        text: str,
        channel_id: str,
        *,
        provider_name: Optional[str] = None,
        auto_create_room: bool = False,
    ) -> None:
        """Send a `fdc3.chat.message` to the agent by broadcasting the
        appropriate context object.

        This constructs the `chatRoom` and `message` objects and calls
        ``broadcast`` with the resulting context.
        """
        room = await self.get_chat_room(
            channel_id, provider_name=provider_name, auto_create=auto_create_room
        )
        message = await self.build_message(text)

        ctx: ChatMessageContext = ChatMessageContext(
            type="fdc3.chat.message",
            chatRoom=room,
            message=message,
        )

        # Broadcast expects a plain dict; convert from Pydantic model or TypedDict
        md = getattr(ctx, "model_dump", None)
        if callable(md):
            try:
                payload = md()
            except Exception:
                payload = {}
        elif isinstance(ctx, dict):
            payload = ctx
        else:
            try:
                payload = dict(ctx)
            except Exception:
                payload = {}

        if not isinstance(payload, dict):
            payload = dict(payload)

        await self.broadcast(payload)

    async def broadcast(self, context: Any) -> None:
        """Send a DACP `broadcast` request to the agent to broadcast `context`.

        This will cause the agent to deliver the context to the channel the
        sending instance is currently joined to.

        Args:
            context: An FDC3 context object (dict or Pydantic model) to broadcast.

        Example:
            >>> await client.broadcast({"type": "fdc3.instrument", "id": {"ticker": "AAPL"}})
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
        """Block until the connection closes, then clean up.

        This is a convenience for long-running external handler processes.
        """
        try:
            if self._recv_task:
                await self._recv_task
        finally:
            await self.close()
