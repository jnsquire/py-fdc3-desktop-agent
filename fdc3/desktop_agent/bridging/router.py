from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

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


class BridgeRequestRouter:
    """Handles requests received from the bridge and produces agent responses."""

    def __init__(self, *, storage, launcher, connection_manager, core_services, local_desktop_agent_name: str | None):
        self._storage = storage
        self._launcher = launcher
        self._connection_manager = connection_manager
        self._core = core_services
        self._local_name = local_desktop_agent_name

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

        if msg_type == "openRequest":
            return await self._respond(request_uuid, msg_type, await self._handle_open(payload))

        if msg_type == "getAppMetadataRequest":
            return await self._respond(request_uuid, msg_type, await self._handle_get_app_metadata(payload))

        if msg_type == "findInstancesRequest":
            return await self._respond(request_uuid, msg_type, await self._handle_find_instances(payload))

        if msg_type == "findIntentRequest":
            return await self._respond(request_uuid, msg_type, await self._handle_find_intent(payload))

        if msg_type == "findIntentsByContextRequest":
            return await self._respond(request_uuid, msg_type, await self._handle_find_intents_by_context(payload))

        if msg_type == "raiseIntentRequest":
            return await self._respond(request_uuid, msg_type, await self._handle_raise_intent(payload, meta))

        # Unknown request
        return await self._respond(request_uuid, msg_type or "unknown", {"error": "MalformedMessage"})

    async def _respond(self, request_uuid: str, request_type: str, payload: dict) -> dict:
        return {
            "type": _response_type_for(request_type),
            "payload": payload,
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
        # Broadcast to all local listeners/channel members.
        # No local source instance to exclude.
        targets = self._core.context_router.broadcast_context(context, source_instance_uuid="")
        from fdc3.models.dacp.dacp import BroadcastEvent, BroadcastEventPayload, AgentEventMeta

        for target_uuid in targets:
            event = BroadcastEvent(
                type="broadcastEvent",
                payload=BroadcastEventPayload(context=context),
                meta=AgentEventMeta(),
            )
            await self._connection_manager.send_to_instance(target_uuid, event.model_dump_json())

    async def _handle_open(self, payload: dict) -> dict:
        app = payload.get("app") or {}
        context = payload.get("context")
        app_id = app.get("appId")
        if not app_id:
            return {"error": OpenError.AppNotFound.value}

        app_metadata = await self._storage.apps.get_app_metadata(app_id)
        if not app_metadata:
            return {"error": OpenError.AppNotFound.value}

        launch_config = await self._storage.launch_configs.get_launch_config(app_id)
        if not launch_config:
            return {"error": OpenError.AppNotFound.value}

        launch_result = await self._launcher.launch_app(app_id, launch_config, context, app)
        if not launch_result.success:
            return {"error": OpenError.ErrorOnLaunch.value}

        return {"appIdentifier": {"appId": app_id, "instanceId": launch_result.instance_id, "desktopAgent": self._local_name}}

    async def _handle_get_app_metadata(self, payload: dict) -> dict:
        app = payload.get("app") or {}
        app_id = app.get("appId")
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
        app_id = app.get("appId")
        if not app_id:
            return {"appIdentifiers": []}

        instances = self._core.app_registry.get_connected_instances_for_app(app_id)
        return {
            "appIdentifiers": [
                {"appId": i.app_id, "instanceId": i.instance_id, "desktopAgent": self._local_name}
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
        targets = self._core.intent_resolver.deliver_intent_event(intent, context, meta.get("source"))
        from fdc3.models.dacp.dacp import IntentEvent, IntentEventPayload, AgentEventMeta

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
            await self._connection_manager.send_to_instance(target_uuid, event.model_dump_json())

        # Ensure returned resolution includes the local desktopAgent.
        try:
            source = resolution.source
            if isinstance(source, AppIdentifier) and self._local_name:
                source.desktopAgent = self._local_name
        except Exception:
            pass

        return {"intentResolution": resolution.model_dump()}
