from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Literal,
    Optional,
    List,
    Mapping,
    Protocol,
)

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from websockets.asyncio.client import ClientConnection, connect

from fdc3.models.identifiers import AppIdentifier
from fdc3.models.identifiers import BaseImplementationMetadata

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_uuid() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True)
class BridgeConnectionSettings:
    host: str
    port_start: int
    port_end: int
    requested_name: str
    retry_seconds: float
    request_timeout_seconds: float


ConnectFunc = Callable[[str], Awaitable[ClientConnection]]


class ImplementationMetadataFactory(Protocol):
    def __call__(
        self,
    ) -> (
        Mapping[str, Any] | BaseImplementationMetadata
    ):  # pragma: no cover - typing helper
        ...


class ChannelsStateFactory(Protocol):
    def __call__(
        self,
    ) -> Mapping[str, List[Mapping[str, Any]]]:  # pragma: no cover - typing helper
        ...


class RequestHandlerProtocol(Protocol):
    def __call__(
        self, msg: Mapping[str, Any]
    ) -> Awaitable[Optional[Mapping[str, Any]]]: ...


class BridgeMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    requestUuid: Optional[str] = None
    responseUuid: Optional[str] = None
    timestamp: Optional[str] = None
    source: Optional[AppIdentifier] = None
    destination: Optional[AppIdentifier] = None


class BridgeMessage(BaseModel):
    """Generic envelope for any bridge message.

    We keep this permissive (extra fields allowed) so the client can safely
    ignore new/unknown message types while still getting typed `meta`.
    """

    model_config = ConfigDict(extra="allow")

    type: str
    payload: Optional[dict[str, Any]] = None
    meta: Optional[BridgeMeta] = None


class BridgeHelloPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    desktopAgentBridgeVersion: str


class BridgeHello(BridgeMessage):
    type: Literal["hello"]
    payload: BridgeHelloPayload


class BridgeHandshakePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    requestedName: str
    implementationMetadata: Mapping[str, Any]
    channelsState: Mapping[str, List[Mapping[str, Any]]] = Field(default_factory=dict)


class BridgeHandshake(BridgeMessage):
    type: Literal["handshake"]
    payload: BridgeHandshakePayload
    meta: BridgeMeta


class BridgeConnectedAgentsUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    addAgent: Optional[str] = None
    allAgents: list[dict] = Field(default_factory=list)


class BridgeConnectedAgentsUpdate(BridgeMessage):
    type: Literal["connectedAgentsUpdate"]
    payload: BridgeConnectedAgentsUpdatePayload
    meta: Optional[BridgeMeta] = None


class BridgeAuthenticationFailedPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    message: Optional[str] = None


class BridgeAuthenticationFailed(BridgeMessage):
    type: Literal["authenticationFailed"]
    payload: Optional[BridgeAuthenticationFailedPayload] = None


class BridgeClient:
    """Desktop Agent Bridge client implementing BCP/BMP.

    This is intentionally minimal: it supports
    - discovery + connect over the recommended port range (4475-4575)
    - BCP: hello -> handshake -> connectedAgentsUpdate
    - BMP: send request + await response by requestUuid
    - receive bridge-forwarded requests and respond via an injected handler

    The bridge is expected to validate/augment `meta.source.desktopAgent`.
    """

    def __init__(
        self,
        settings: BridgeConnectionSettings,
        *,
        implementation_metadata_factory: ImplementationMetadataFactory,
        channels_state_factory: ChannelsStateFactory,
        request_handler: RequestHandlerProtocol,
        connect_func: Optional[ConnectFunc] = None,
    ):
        self._settings = settings
        # Factories and handlers — keep runtime flexibility but tighten hints
        self._implementation_metadata_factory: ImplementationMetadataFactory = (
            implementation_metadata_factory
        )
        self._channels_state_factory: ChannelsStateFactory = channels_state_factory
        self._request_handler: RequestHandlerProtocol = request_handler
        self._connect: ConnectFunc = connect_func or (lambda url: connect(url))

        self._ws: Optional[ClientConnection] = None
        self._run_task: Optional[asyncio.Task] = None
        self._recv_task: Optional[asyncio.Task] = None
        self._stopping = asyncio.Event()

        self._assigned_name: Optional[str] = None
        self._connected_agents: list[dict] = []

        self._pending: Dict[str, asyncio.Future] = {}
        self._pending_lock = asyncio.Lock()

        # Used to ensure atomic processing of connectedAgentsUpdate.
        self._sync_lock = asyncio.Lock()

    @property
    def assigned_name(self) -> Optional[str]:
        return self._assigned_name

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and self._assigned_name is not None

    async def start(self) -> None:
        if self._run_task is not None:
            return
        self._stopping.clear()
        self._run_task = asyncio.create_task(self._run_loop(), name="bridge-client")

    async def stop(self) -> None:
        self._stopping.set()
        if self._recv_task is not None:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
            self._recv_task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._run_task is not None:
            self._run_task.cancel()
            try:
                await self._run_task
            except asyncio.CancelledError:
                pass
            self._run_task = None

        await self._fail_all_pending("bridge stopped")

    async def _fail_all_pending(self, error: str) -> None:
        async with self._pending_lock:
            items = list(self._pending.items())
            self._pending.clear()
        for _, fut in items:
            if not fut.done():
                fut.set_exception(RuntimeError(error))

    async def _run_loop(self) -> None:
        # Spec suggests retrying with a minimum 5s pause once ports exhausted.
        while not self._stopping.is_set():
            try:
                await self._connect_and_handshake()
                # Stay connected until recv loop exits.
                assert self._recv_task is not None
                await self._recv_task
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Bridge connection loop error")
            finally:
                # Reset connection state.
                self._assigned_name = None
                self._connected_agents = []
                if self._ws is not None:
                    try:
                        await self._ws.close()
                    except Exception:
                        pass
                    self._ws = None
                await self._fail_all_pending("bridge disconnected")

            if not self._stopping.is_set():
                await asyncio.sleep(self._settings.retry_seconds)

    async def _connect_and_handshake(self) -> None:
        ws = None
        url = None
        for port in range(self._settings.port_start, self._settings.port_end + 1):
            if self._stopping.is_set():
                return
            url = f"ws://{self._settings.host}:{port}"
            try:
                ws = await self._connect(url)
                break
            except Exception:
                continue

        if ws is None or url is None:
            raise RuntimeError("No bridge found in configured port range")

        self._ws = ws

        # Step 2: wait for hello
        raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
        hello_raw = self._parse_json(raw)
        try:
            BridgeHello.model_validate(hello_raw)
        except ValidationError as exc:
            raise RuntimeError(
                "Connected websocket did not send a valid bridge hello"
            ) from exc

        # Step 3: send handshake
        handshake_request_uuid = _make_uuid()

        def _normalize_impl_metadata(raw: Any) -> dict:
            # Accept either a Pydantic model or a raw mapping; ensure required
            # fields exist and `optionalFeatures` is a mapping.
            if isinstance(raw, BaseImplementationMetadata):
                return raw.model_dump()
            md = dict(raw or {})
            md.setdefault("fdc3Version", "0.0")
            md.setdefault("optionalFeatures", {})
            try:
                return BaseImplementationMetadata.model_validate(md).model_dump()
            except ValidationError:
                # Fallback: ensure minimal shape
                return {
                    "fdc3Version": md.get("fdc3Version", "0.0"),
                    "provider": md.get("provider", ""),
                    "optionalFeatures": md.get("optionalFeatures", {}),
                }

        impl_meta = _normalize_impl_metadata(self._implementation_metadata_factory())

        handshake = BridgeHandshake(
            type="handshake",
            payload=BridgeHandshakePayload(
                requestedName=self._settings.requested_name,
                implementationMetadata=impl_meta,
                channelsState=self._channels_state_factory(),
            ),
            meta=BridgeMeta(
                requestUuid=handshake_request_uuid,
                timestamp=_utc_now_iso(),
            ),
        )

        await ws.send(handshake.model_dump_json())

        # Start recv loop (handles connectedAgentsUpdate and BMP messages)
        self._recv_task = asyncio.create_task(self._recv_loop(), name="bridge-recv")

        # Wait until we receive the connectedAgentsUpdate corresponding to the handshake.
        # (Spec: requestUuid matches handshake requestUuid)
        await asyncio.wait_for(
            self._wait_for_assigned_name(handshake_request_uuid), 5.0
        )

    async def _wait_for_assigned_name(self, handshake_request_uuid: str) -> None:
        # Polling is fine here since recv loop sets `_assigned_name`.
        for _ in range(100):
            if self._stopping.is_set():
                return
            if self._assigned_name is not None:
                return
            await asyncio.sleep(0.05)
        raise RuntimeError("Timed out waiting for connectedAgentsUpdate")

    @staticmethod
    def _parse_json(raw: Any) -> dict:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        if not isinstance(raw, str):
            raise ValueError("Expected text websocket message")
        return json.loads(raw)

    async def _recv_loop(self) -> None:
        assert self._ws is not None
        ws = self._ws
        while not self._stopping.is_set():
            raw = await ws.recv()
            msg_raw = self._parse_json(raw)
            msg = BridgeMessage.model_validate(msg_raw)

            msg_type = msg.type
            meta = msg.meta

            # Step 4/6: connectedAgentsUpdate (atomic processing)
            if msg_type == "connectedAgentsUpdate":
                async with self._sync_lock:
                    try:
                        update = BridgeConnectedAgentsUpdate.model_validate(msg_raw)
                        payload = update.payload
                    except ValidationError:
                        payload = BridgeConnectedAgentsUpdatePayload.model_validate(
                            msg_raw.get("payload") or {}
                        )
                    # Newly connected agent gets addAgent assigned name.
                    if isinstance(payload.addAgent, str) and payload.addAgent:
                        self._assigned_name = payload.addAgent
                    self._connected_agents = payload.allAgents
                continue

            # Bridge auth failure
            if msg_type == "authenticationFailed":
                try:
                    failed = BridgeAuthenticationFailed.model_validate(msg_raw)
                except ValidationError:
                    failed = BridgeAuthenticationFailed(type="authenticationFailed")
                raise RuntimeError(
                    (failed.payload.message if failed.payload else None)
                    or "auth failed"
                )

            request_uuid = meta.requestUuid if meta else None
            response_uuid = meta.responseUuid if meta else None

            # Responses (meta.responseUuid present)
            if request_uuid and response_uuid:
                await self._handle_response(request_uuid, msg_raw)
                continue

            # Requests forwarded by bridge (requestUuid present, no responseUuid)
            if request_uuid and not response_uuid:
                async with self._sync_lock:
                    response = await self._request_handler(msg_raw)
                if response is not None:
                    await ws.send(json.dumps(response))
                continue

            logger.debug(
                "Ignoring bridge message without request/response UUID: %s", msg_type
            )

    async def _handle_response(self, request_uuid: str, msg: dict) -> None:
        async with self._pending_lock:
            fut = self._pending.pop(request_uuid, None)
        if fut is None:
            return
        if not fut.done():
            fut.set_result(msg)

    async def send_agent_request(
        self,
        *,
        request_type: str,
        payload: dict,
        source: AppIdentifier | dict,
        destination: Optional[AppIdentifier | dict] = None,
        timeout: Optional[float] = None,
    ) -> dict:
        """Send an agentRequest message and await the (bridge-collated) response."""
        if self._ws is None:
            raise RuntimeError("NotConnectedToBridge")

        req_uuid = _make_uuid()
        timeout = (
            timeout if timeout is not None else self._settings.request_timeout_seconds
        )

        msg: dict = {
            "type": request_type,
            "payload": payload,
            "meta": {
                "requestUuid": req_uuid,
                "timestamp": _utc_now_iso(),
                "source": source.model_dump()
                if isinstance(source, AppIdentifier)
                else dict(source),
            },
        }
        if destination is not None:
            msg["meta"]["destination"] = (
                destination.model_dump()
                if isinstance(destination, AppIdentifier)
                else dict(destination)
            )

        fut = asyncio.get_running_loop().create_future()
        async with self._pending_lock:
            self._pending[req_uuid] = fut

        # Validate + normalize before sending.
        await self._ws.send(BridgeMessage.model_validate(msg).model_dump_json())
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            async with self._pending_lock:
                self._pending.pop(req_uuid, None)

    async def send_request_no_wait(
        self,
        *,
        request_type: str,
        payload: dict,
        source: AppIdentifier | dict,
        destination: Optional[AppIdentifier | dict] = None,
    ) -> str:
        """Send a request message that does not generate a response.

        Used for BMP 'fire and forget' messages such as `broadcastRequest`.
        Returns the generated requestUuid.
        """
        if self._ws is None:
            raise RuntimeError("NotConnectedToBridge")

        req_uuid = _make_uuid()
        msg: dict = {
            "type": request_type,
            "payload": payload,
            "meta": {
                "requestUuid": req_uuid,
                "timestamp": _utc_now_iso(),
                "source": source.model_dump()
                if isinstance(source, AppIdentifier)
                else dict(source),
            },
        }
        if destination is not None:
            msg["meta"]["destination"] = (
                destination.model_dump()
                if isinstance(destination, AppIdentifier)
                else dict(destination)
            )

        # Validate + normalize before sending.
        await self._ws.send(BridgeMessage.model_validate(msg).model_dump_json())
        return req_uuid


def make_desktop_agent_identifier(desktop_agent: str) -> dict:
    return {"desktopAgent": desktop_agent}
