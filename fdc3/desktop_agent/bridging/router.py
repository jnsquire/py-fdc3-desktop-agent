from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fdc3.models.dacp.dacp import (
    IntentEvent,
    IntentEventPayload,
    AgentEventMeta,
    BroadcastEvent,
    BroadcastEventPayload,
    PrivateChannelEvent,
    PrivateChannelEventPayload,
    FDC3EventMessage,
    FDC3EventMessagePayload,
)
from fdc3.models.identifiers import FDC3Event
from fdc3.models.identifiers import AppIdentifier
from fdc3.desktop_agent.api import OpenError, ResolveError

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_uuid() -> str:
    return str(uuid.uuid4())


def _response_type_for(request_type: str) -> str:
    # Spec convention: functionNameRequest -> functionNameResponse
    if request_type.endswith("Request"):
        return request_type[: -len("Request")] + "Response"
    return request_type + "Response"


def _normalize_app_id(app_id: str | None) -> str | None:
    if not app_id:
        return None
    if "@" in app_id:
        base, _ = app_id.split("@", 1)
        return base or app_id
    return app_id


class BridgeRequestRouter:
    """Handles requests received from the bridge and produces agent responses."""

    def __init__(
        self,
        *,
        storage,
        launcher,
        connection_manager,
        core_services,
        local_desktop_agent_name: str | None,
    ):
        self._storage = storage
        self._launcher = launcher
        self._connection_manager = connection_manager
        self._core = core_services
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

        # Fire-and-forget
        if msg_type == "broadcastRequest":
            await self._handle_broadcast(payload)
            return None

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

        response_payload: dict | None = None

        if msg_type == "openRequest":
            response_payload = await self._handle_open(payload)
        elif msg_type == "getAppMetadataRequest":
            response_payload = await self._handle_get_app_metadata(payload)
        elif msg_type == "findInstancesRequest":
            response_payload = await self._handle_find_instances(payload)
        elif msg_type == "findIntentRequest":
            response_payload = await self._handle_find_intent(payload)
        elif msg_type == "findIntentsByContextRequest":
            response_payload = await self._handle_find_intents_by_context(payload)
        elif msg_type == "raiseIntentRequest":
            response_payload = await self._handle_raise_intent(payload, meta)

        if response_payload is None:
            response_payload = {"error": "MalformedMessage"}

        request_type = msg_type or "unknown"
        return {
            "type": _response_type_for(request_type),
            "payload": response_payload,
            "meta": {
                "requestUuid": request_uuid,
                "responseUuid": _make_uuid(),
                "timestamp": _utc_now_iso(),
            },
        }

    async def _handle_broadcast(self, payload: dict) -> None:
        context = payload.get("context")
        if not isinstance(context, dict) or not context.get("type"):
            return
        channel_id = payload.get("channelId")
        # Broadcast to all local listeners/channel members.
        # No local source instance to exclude.
        targets = self._core.context_router.broadcast_context(
            context,
            source_instance_uuid="",
            channel_id=channel_id if isinstance(channel_id, str) else None,
        )
        for target_uuid in targets:
            event = BroadcastEvent(
                type="broadcastEvent",
                payload=BroadcastEventPayload(context=context),
                meta=AgentEventMeta(),
            )
            await self._connection_manager.send_to_instance(
                target_uuid, event.model_dump_json()
            )

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

    async def _handle_open(self, payload: dict) -> dict:
        app = payload.get("app") or {}
        context = payload.get("context")
        app_id = _normalize_app_id(app.get("appId"))
        if not app_id:
            return {"error": OpenError.AppNotFound.value}

        app_metadata = await self._storage.apps.get_app_metadata(app_id)
        if not app_metadata:
            return {"error": OpenError.AppNotFound.value}

        launch_config = await self._storage.launch_configs.get_launch_config(app_id)
        if not launch_config:
            return {"error": OpenError.AppNotFound.value}

        app_payload = dict(app)
        app_payload["appId"] = app_id
        launch_result = await self._launcher.launch_app(
            app_id, launch_config, context, app_payload
        )
        if not launch_result.success:
            return {"error": OpenError.ErrorOnLaunch.value}

        if not launch_result.instance_id or not launch_result.instance_uuid:
            return {"error": OpenError.ErrorOnLaunch.value}

        # Register pending instance and wait for connection (min 15s)
        self._core.app_registry.register_pending_instance(
            app_id, launch_result.instance_id, launch_result.instance_uuid
        )

        connected = await self._core.app_registry.wait_for_instance_connection(
            launch_result.instance_uuid, timeout=15.0
        )

        if not connected:
            self._core.app_registry.unregister_instance(launch_result.instance_uuid)
            return {"error": OpenError.AppTimeout.value}

        return {
            "appIdentifier": {
                "appId": app_id,
                "instanceId": launch_result.instance_id,
                "desktopAgent": self._local_name,
            }
        }

    async def _handle_get_app_metadata(self, payload: dict) -> dict:
        app = payload.get("app") or {}
        app_id = _normalize_app_id(app.get("appId"))
        if not app_id:
            return {"error": OpenError.AppNotFound.value}

        meta = await self._storage.apps.get_app_metadata(app_id)
        if not meta:
            return {"error": OpenError.AppNotFound.value}

        return {
            "appMetadata": {
                "appId": meta.app_id,
                "name": meta.name,
                "version": meta.version,
                "description": meta.description,
                "icons": meta.icons,
                "desktopAgent": self._local_name,
            }
        }

    async def _handle_find_instances(self, payload: dict) -> dict:
        app = payload.get("app") or {}
        app_id = _normalize_app_id(app.get("appId"))
        if not app_id:
            return {"appIdentifiers": []}

        instances = self._core.app_registry.get_connected_instances_for_app(app_id)
        return {
            "appIdentifiers": [
                {
                    "appId": i.app_id,
                    "instanceId": i.instance_id,
                    "desktopAgent": self._local_name,
                }
                for i in instances
            ]
        }

    async def _handle_find_intent(self, payload: dict) -> dict:
        intent = payload.get("intent")
        if not intent:
            return {"error": ResolveError.NoAppsFound.value}

        apps = await self._storage.apps.list_apps()
        matching = [a for a in apps if intent in (a.intents or [])]

        if not matching:
            return {"error": ResolveError.NoAppsFound.value}

        return {
            "appIntent": {
                "intent": {"name": intent},
                "apps": [
                    {
                        "appId": a.app_id,
                        "name": a.name,
                        "version": a.version,
                        "description": a.description,
                        "icons": a.icons,
                        "desktopAgent": self._local_name,
                    }
                    for a in matching
                ],
            }
        }

    async def _handle_find_intents_by_context(self, payload: dict) -> dict:
        # This implementation does not yet track intent->contextType mappings.
        # Return empty rather than misleading matches.
        return {"appIntents": []}

    async def _handle_raise_intent(self, payload: dict, meta: dict) -> dict:
        intent = payload.get("intent")
        context = payload.get("context")
        if not intent:
            return {"error": ResolveError.NoAppsFound.value}

        # Resolve to a local listener (simple policy)
        resolution = self._core.intent_resolver.resolve_intent(intent, context, None)
        if resolution is None:
            return {"error": ResolveError.NoAppsFound.value}

        # Deliver intent event to the resolved instance.
        targets = self._core.intent_resolver.deliver_intent_event(
            intent, context, meta.get("source")
        )

        for target_uuid in targets:
            event = IntentEvent(
                type="intentEvent",
                payload=IntentEventPayload(
                    intent=intent,
                    context=context,
                    originatingApp=meta.get("source"),
                ),
                meta=AgentEventMeta(),
            )
            await self._connection_manager.send_to_instance(
                target_uuid, event.model_dump_json()
            )

        # Ensure returned resolution includes the local desktopAgent.
        source = getattr(resolution, "source", None)
        if isinstance(source, AppIdentifier) and self._local_name:
            source.desktopAgent = self._local_name

        return {"intentResolution": resolution.model_dump()}
