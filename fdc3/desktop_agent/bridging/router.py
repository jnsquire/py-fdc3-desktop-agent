from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel
from fdc3.models.dacp.dacp import (
    AgentEventMeta,
    PrivateChannelEvent,
    PrivateChannelEventPayload,
    FDC3EventMessage,
    FDC3EventMessagePayload,
)
from fdc3.models.identifiers import FDC3Event
from ..handlers.protocols import MessageSender

logger = logging.getLogger(__name__)


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

    async def handle(self, msg: dict) -> Optional[dict]:
        msg_type = msg.get("type")
        payload = msg.get("payload") or {}
        meta = msg.get("meta") or {}
        request_uuid = meta.get("requestUuid")
        if not request_uuid:
            return None

        # Keep bridge-specific handling if not in DACP registry
        if msg_type == "privateChannelEvent":
            await self._handle_private_channel_event(payload, meta)
            return None

        if msg_type == "privateChannelEventListenerAdded":
            self._handle_private_channel_listener_update(payload, meta, added=True)
            return None

        if msg_type == "privateChannelEventListenerRemoved":
            self._handle_private_channel_listener_update(payload, meta, added=False)
            return None

        if msg_type == "fdc3Event":
            await self._handle_fdc3_event(payload, meta)
            return None

        # Try DACP handler
        sender = BridgeSender()

        # Bridge uses "Request" suffix, DACP internally uses simplified names.
        dacp_msg = msg
        if msg_type and msg_type.endswith("Request"):
            simplified_type = msg_type[: -len("Request")]
            # Map bridge request types to DACP internal names
            if simplified_type in [
                "open",
                "broadcast",
                "getAppMetadata",
                "findInstances",
                "findIntent",
                "findIntentsByContext",
                "raiseIntent",
            ]:
                dacp_msg = msg.copy()
                dacp_msg["type"] = simplified_type

        await self._dacp_handler.handle_message(dacp_msg, "", {}, sender)

        if sender.response:
            resp_dict = sender.response.model_dump(exclude_none=True)
            # Ensure type matches what bridge expects ("Request" -> "Response")
            if msg_type and msg_type.endswith("Request"):
                expected_type = msg_type[: -len("Request")] + "Response"
                if resp_dict.get("type") != expected_type:
                    resp_dict["type"] = expected_type

            # Special case mappings for bridge compatibility
            r_payload = resp_dict.get("payload") or {}

            # openResponse: ensure desktopAgent is set in appIdentifier
            if resp_dict.get("type") == "openResponse":
                app_id = r_payload.get("appIdentifier")
                if (
                    app_id
                    and isinstance(app_id, dict)
                    and not app_id.get("desktopAgent")
                ):
                    app_id["desktopAgent"] = self._local_name

            # findInstancesResponse: DACP uses 'instances', Bridge expects 'appIdentifiers'
            if resp_dict.get("type") == "findInstancesResponse":
                if "instances" in r_payload and "appIdentifiers" not in r_payload:
                    r_payload["appIdentifiers"] = r_payload.pop("instances")
                # Also ensure desktopAgent is set
                for ai in r_payload.get("appIdentifiers") or []:
                    if isinstance(ai, dict) and not ai.get("desktopAgent"):
                        ai["desktopAgent"] = self._local_name

            # getAppMetadataResponse: ensure desktopAgent is set
            if resp_dict.get("type") == "getAppMetadataResponse":
                m = r_payload.get("appMetadata")
                if m and isinstance(m, dict) and not m.get("desktopAgent"):
                    m["desktopAgent"] = self._local_name

            # raiseIntentResponse: ensure desktopAgent is set in source
            if resp_dict.get("type") == "raiseIntentResponse":
                res = r_payload.get("intentResolution")
                if res and isinstance(res, dict):
                    source = res.get("source")
                    if (
                        source
                        and isinstance(source, dict)
                        and not source.get("desktopAgent")
                    ):
                        source["desktopAgent"] = self._local_name

            # findIntentResponse: each app needs desktopAgent
            if resp_dict.get("type") == "findIntentResponse":
                app_intent = r_payload.get("appIntent")
                if app_intent and isinstance(app_intent, dict):
                    for a in app_intent.get("apps") or []:
                        if isinstance(a, dict) and not a.get("desktopAgent"):
                            a["desktopAgent"] = self._local_name

            return resp_dict

        return None

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
        destination = meta.get("destination") or {}
        app_id = destination.get("appId")
        instance_id = destination.get("instanceId")
        if not app_id:
            return

        event = payload.get("event")
        if not isinstance(event, dict):
            return

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
            payload=FDC3EventMessagePayload(event=FDC3Event.model_validate(event)),
            meta=AgentEventMeta(),
        ).model_dump_json()

        for inst in instances:
            await self._connection_manager.send_to_instance(inst.instance_uuid, message)
