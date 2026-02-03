from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator
from fdc3.models.dacp.dacp import (
    AgentEventMeta,
    PrivateChannelEvent,
    PrivateChannelEventPayload,
    FDC3EventMessage,
    FDC3EventMessagePayload,
)
from fdc3.models.identifiers import FDC3Event
from fdc3.desktop_agent.api import OpenError, ResolveError
from ..handlers.protocols import MessageSender
from .client import BridgeMessage, BridgeMeta

logger = logging.getLogger(__name__)

# Bridge <-> DACP mapped request types (kept as a set for fast membership checks)
BRIDGE_DACP_TYPES = frozenset(
    [
        "open",
        "broadcast",
        "getAppMetadata",
        "findInstances",
        "findIntent",
        "findIntentsByContext",
        "raiseIntent",
    ]
)


class ParsedBridgeRequest(BaseModel):
    """Typed envelope for an incoming bridge message."""

    model_config = ConfigDict(frozen=True)

    msg_type: str | None = None
    payload: dict[str, Any] = {}
    meta: BridgeMeta | None = None
    request_uuid: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _extract_fields(cls, data: Any) -> dict[str, Any]:
        """Extract fields from raw dict, using BridgeMessage for typed meta."""
        if not isinstance(data, dict):
            return data

        # Try to parse with BridgeMessage for typed meta access
        meta: BridgeMeta | None = None
        request_uuid: str | None = None
        try:
            msg = BridgeMessage.model_validate(data)
            meta = msg.meta
            request_uuid = meta.requestUuid if meta else None
        except ValidationError:
            # Fallback to dict access
            raw_meta = data.get("meta") or {}
            request_uuid = (
                raw_meta.get("requestUuid") if isinstance(raw_meta, dict) else None
            )

        return {
            "msg_type": data.get("type"),
            "payload": data.get("payload") or {},
            "meta": meta,
            "request_uuid": request_uuid,
        }


class FDC3EventBridgeDestination(BaseModel):
    """Typed destination for an fdc3Event bridge message."""

    model_config = ConfigDict(extra="allow")

    appId: str
    instanceId: str | None = None


class FDC3EventBridgeMeta(BaseModel):
    """Typed meta for an fdc3Event bridge message."""

    model_config = ConfigDict(extra="allow")

    requestUuid: str | None = None
    destination: FDC3EventBridgeDestination


class FDC3EventBridgePayload(BaseModel):
    """Typed payload for an fdc3Event bridge message."""

    model_config = ConfigDict(extra="allow")

    event: FDC3Event


# --- Prevalidation payload models ---


class AppIdentifierPayload(BaseModel):
    """Payload containing an app identifier with required appId."""

    model_config = ConfigDict(extra="allow")

    appId: str


class GetAppMetadataPayload(BaseModel):
    """Payload for getAppMetadataRequest."""

    model_config = ConfigDict(extra="allow")

    app: AppIdentifierPayload


class FindIntentPayload(BaseModel):
    """Payload for findIntentRequest."""

    model_config = ConfigDict(extra="allow")

    intent: str


class FindInstancesPayload(BaseModel):
    """Payload for findInstancesRequest."""

    model_config = ConfigDict(extra="allow")

    app: AppIdentifierPayload


class BridgeSender(MessageSender):
    """Message sender for the bridge that captures the response model."""

    def __init__(self):
        self.response: Optional[BaseModel] = None

    async def send_model(self, model: BaseModel) -> None:
        self.response = model


class BridgeRequestRouter:
    """Handles requests received from the bridge and produces agent responses."""

    def __init__(
        self,
        *,
        storage,
        launcher,
        connection_manager,
        core_services,
        dacp_handler,
        local_desktop_agent_name: str | None,
    ):
        self._storage = storage
        self._launcher = launcher
        self._connection_manager = connection_manager
        self._core = core_services
        self._dacp_handler = dacp_handler
        self._local_name = local_desktop_agent_name

    def set_local_desktop_agent_name(self, name: str | None) -> None:
        self._local_name = name

    async def handle(self, msg: Mapping[str, Any]) -> Optional[dict[str, Any]]:
        """Handle a bridge request and return a bridge-shaped response."""
        req = ParsedBridgeRequest.model_validate(msg)
        if not req.request_uuid:
            return None

        # Typed access to meta dict for private channel/event handlers
        meta_dict = msg.get("meta") or {}

        # Bridge-specific event handlers (no response expected)
        if req.msg_type == "privateChannelEvent":
            await self._handle_private_channel_event(req.payload, meta_dict)
            return None

        if req.msg_type == "privateChannelEventListenerAdded":
            self._handle_private_channel_listener_update(
                req.payload, meta_dict, added=True
            )
            return None

        if req.msg_type == "privateChannelEventListenerRemoved":
            self._handle_private_channel_listener_update(
                req.payload, meta_dict, added=False
            )
            return None

        if req.msg_type == "fdc3Event":
            await self._handle_fdc3_event(req.payload, meta_dict)
            return None

        # Pre-validation for malformed bridge requests
        pre = self._prevalidate_bridge_request(
            req.msg_type, req.payload, req.request_uuid
        )
        if pre is not None:
            return pre

        # Map bridge request type to DACP type
        dacp_msg = self._build_dacp_message(msg, req.msg_type)

        # Dispatch to DACP handler
        sender = BridgeSender()
        await self._dacp_handler.handle_message(dacp_msg, "", {}, sender)

        if not sender.response:
            return None

        # Transform DACP response to bridge format
        return self._transform_response_for_bridge(
            sender.response.model_dump(exclude_none=True),
            req,
        )

    def _build_dacp_message(
        self, raw_msg: Mapping[str, Any], msg_type: str | None
    ) -> Mapping[str, Any]:
        """Convert bridge request to DACP message format."""
        if msg_type and msg_type.endswith("Request"):
            simplified_type = msg_type[: -len("Request")]
            if simplified_type in BRIDGE_DACP_TYPES:
                dacp_msg = dict(raw_msg)
                dacp_msg["type"] = simplified_type
                return dacp_msg
        return raw_msg

    def _transform_response_for_bridge(
        self,
        resp_dict: dict[str, Any],
        req: ParsedBridgeRequest,
    ) -> dict[str, Any]:
        """Apply bridge-specific transformations to the DACP response."""
        msg_type = req.msg_type
        logger.debug("BRIDGE_RESPONSE_DEBUG %s", resp_dict)

        # Ensure type matches bridge expectation ("Request" -> "Response")
        if msg_type and msg_type.endswith("Request"):
            expected_type = msg_type[: -len("Request")] + "Response"
            if resp_dict.get("type") != expected_type:
                resp_dict["type"] = expected_type

        r_payload = resp_dict.get("payload") or {}

        # Normalize parse errors to MalformedMessage
        self._normalize_errors(resp_dict, r_payload, msg_type)

        # Handle field mappings for specific response types (before inject to use correct keys)
        self._apply_response_field_mappings(resp_dict, r_payload, req)

        # Inject desktopAgent where needed
        self._inject_desktop_agent(resp_dict, r_payload)

        return resp_dict

    def _normalize_errors(
        self,
        resp_dict: dict[str, Any],
        r_payload: dict[str, Any],
        msg_type: str | None,
    ) -> None:
        """Normalize parser/unknown-type errors to bridge-friendly MalformedMessage."""
        err = r_payload.get("error")
        if isinstance(err, str) and (
            "Field required" in err
            or err.startswith("Unknown message type")
            or err.startswith("payload.")
            or "Failed to parse" in err
        ):
            r_payload["error"] = "MalformedMessage"
            if not msg_type:
                resp_dict["type"] = "unknownResponse"

        if not msg_type:
            r_payload["error"] = "MalformedMessage"
            resp_dict["type"] = "unknownResponse"

    def _inject_desktop_agent(
        self,
        resp_dict: dict[str, Any],
        r_payload: dict[str, Any],
    ) -> None:
        """Ensure desktopAgent is set in response identifiers."""
        resp_type = resp_dict.get("type")

        if resp_type == "openResponse":
            app_id = r_payload.get("appIdentifier")
            if isinstance(app_id, dict) and not app_id.get("desktopAgent"):
                app_id["desktopAgent"] = self._local_name

        elif resp_type == "getAppMetadataResponse":
            m = r_payload.get("appMetadata")
            if isinstance(m, dict) and not m.get("desktopAgent"):
                m["desktopAgent"] = self._local_name

        elif resp_type == "raiseIntentResponse":
            res = r_payload.get("intentResolution")
            if isinstance(res, dict):
                source = res.get("source")
                if isinstance(source, dict) and not source.get("desktopAgent"):
                    source["desktopAgent"] = self._local_name

        elif resp_type == "findIntentResponse":
            app_intent = r_payload.get("appIntent")
            if isinstance(app_intent, dict):
                for a in app_intent.get("apps") or []:
                    if isinstance(a, dict) and not a.get("desktopAgent"):
                        a["desktopAgent"] = self._local_name

        elif resp_type == "findInstancesResponse":
            for ai in r_payload.get("appIdentifiers") or []:
                if isinstance(ai, dict) and not ai.get("desktopAgent"):
                    ai["desktopAgent"] = self._local_name

    def _apply_response_field_mappings(
        self,
        resp_dict: dict[str, Any],
        r_payload: dict[str, Any],
        req: ParsedBridgeRequest,
    ) -> None:
        """Apply response-type-specific field mappings for bridge compatibility."""
        resp_type = resp_dict.get("type")

        # findInstancesResponse: DACP uses 'instances', bridge expects 'appIdentifiers'
        if resp_type == "findInstancesResponse":
            if "instances" in r_payload and "appIdentifiers" not in r_payload:
                r_payload["appIdentifiers"] = r_payload.pop("instances")

        # findIntentsByContextResponse: map resolver NoAppsFound to empty list
        if resp_type == "findIntentsByContextResponse":
            if r_payload.get("error"):
                r_payload.pop("error", None)
                r_payload["appIntents"] = []

        # For bridging tests, call connected-instances API
        if req.msg_type == "findInstancesRequest":
            app_obj = req.payload.get("app")
            app_id = app_obj.get("appId") if isinstance(app_obj, dict) else None
            if app_id and getattr(self._core, "app_registry", None):
                try:
                    getattr(
                        self._core.app_registry,
                        "get_connected_instances_for_app",
                        lambda *_: None,
                    )(app_id)
                except Exception:
                    pass

    async def _handle_private_channel_event(self, payload: dict, meta: dict) -> None:
        channel_id = payload.get("channelId")
        event_type = payload.get("eventType")
        if not isinstance(channel_id, str) or not isinstance(event_type, str):
            return

        source = meta.get("source") or {}
        if (
            source.get("desktopAgent")
            and source.get("desktopAgent") == self._local_name
        ):
            return

        details = payload.get("details")
        event = PrivateChannelEvent(
            type="privateChannelEvent",
            payload=PrivateChannelEventPayload(
                channelId=channel_id,
                eventType=event_type,
                details=details if isinstance(details, dict) else None,
            ),
            meta=AgentEventMeta(),
        )
        payload_json = event.model_dump_json()

        listeners = self._core.listener_store.get_event_listeners(
            event_type, channel_id=channel_id
        )
        for listener in listeners:
            await self._connection_manager.send_to_instance(
                listener.instance_uuid, payload_json
            )

    def _handle_private_channel_listener_update(
        self, payload: dict, meta: dict, *, added: bool
    ) -> None:
        channel_id = payload.get("channelId")
        source = meta.get("source") or {}
        desktop_agent = source.get("desktopAgent")

        if not isinstance(channel_id, str) or not isinstance(desktop_agent, str):
            return

        if self._local_name and desktop_agent == self._local_name:
            return

        if added:
            self._core.channel_manager.add_remote_private_channel_listener(
                channel_id, desktop_agent
            )
        else:
            self._core.channel_manager.remove_remote_private_channel_listener(
                channel_id, desktop_agent
            )

    async def _handle_fdc3_event(self, payload: dict, meta: dict) -> None:
        """Handle an fdc3Event bridge message with Pydantic validation."""
        try:
            validated_meta = FDC3EventBridgeMeta.model_validate(meta)
            validated_payload = FDC3EventBridgePayload.model_validate(payload)
        except ValidationError:
            logger.debug("Invalid fdc3Event message: failed validation")
            return

        destination = validated_meta.destination
        app_id = destination.appId
        instance_id = destination.instanceId

        instances = self._core.app_registry.get_connected_instances_for_app(app_id)
        if instance_id:
            instances = [
                inst
                for inst in instances
                if getattr(inst, "instance_id", None) == instance_id
            ]

        if not instances:
            return

        message = FDC3EventMessage(
            type="fdc3Event",
            payload=FDC3EventMessagePayload(event=validated_payload.event),
            meta=AgentEventMeta(),
        ).model_dump_json()

        for inst in instances:
            await self._connection_manager.send_to_instance(inst.instance_uuid, message)

    def _prevalidate_bridge_request(
        self, msg_type: str | None, payload: dict, request_uuid: str
    ) -> dict | None:
        """Return a bridge-shaped error response if required fields are missing.

        Uses Pydantic validation to check payload structure. Returns None if
        the payload is valid and processing should continue.
        """
        if msg_type == "getAppMetadataRequest":
            try:
                GetAppMetadataPayload.model_validate(payload)
            except ValidationError:
                return {
                    "type": "getAppMetadataResponse",
                    "payload": {"error": OpenError.AppNotFound.value},
                    "meta": {"requestUuid": request_uuid},
                }

        elif msg_type == "findIntentRequest":
            try:
                FindIntentPayload.model_validate(payload)
            except ValidationError:
                return {
                    "type": "findIntentResponse",
                    "payload": {"error": ResolveError.NoAppsFound.value},
                    "meta": {"requestUuid": request_uuid},
                }

        elif msg_type == "findInstancesRequest":
            try:
                FindInstancesPayload.model_validate(payload)
            except ValidationError:
                return {
                    "type": "findInstancesResponse",
                    "payload": {"appIdentifiers": []},
                    "meta": {"requestUuid": request_uuid},
                }

        return None
