"""
Intent-related DACP handlers: findIntent, findIntentsByContext, raiseIntent,
raiseIntentForContext, intentResult, and external handler support.
"""

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any, Iterable, Mapping, cast

from fdc3.models.dacp.dacp import (
    AgentEventMeta,
    AgentResponse,
    ErrorResponsePayload,
    FindIntentRequest,
    FindIntentResponse,
    FindIntentResponsePayload,
    FindIntentsByContextRequest,
    FindIntentsByContextResponse,
    FindIntentsByContextResponsePayload,
    Fdc3Context,
    IntentEvent,
    IntentEventPayload,
    IntentResultRequest,
    IntentResultResponse,
    IntentResultResponsePayload,
    RaiseIntentRequest,
    RaiseIntentResponse,
    RaiseIntentResponsePayload,
    RaiseIntentForContextRequest,
    RaiseIntentForContextResponse,
    RaiseIntentForContextResponsePayload,
    RaiseIntentResultResponse,
)
from fdc3.models.dacp.external_models import (
    RegisterExternalHandlerRequest,
    RegisterExternalHandlerResponse,
    RegisterExternalHandlerResponsePayload,
    UnregisterExternalHandlerRequest,
    UnregisterExternalHandlerResponse,
    ExternalIntentResultRequest,
    ForwardedIntentMessage,
    ForwardedIntentPayload,
)
from fdc3.models.identifiers import (
    AppIdentifier,
    AppIntent,
    AppMetadata,
    IntentMetadata,
    IntentResolution as WireIntentResolution,
)
from ...api import BridgingError, IntentResolution, ResolveError
from ...types import IntentEntry, IntentEntryMapping, WcpSessions
from ..protocols import MessageSender
from .registry import dacp_handler, DACPError

if TYPE_CHECKING:
    from .base import DACPHandler
    from ...core import CoreServices
    from ...storage import Storage

logger = logging.getLogger(__name__)


class IntentHandlersMixin:
    """Mixin providing intent-related DACP handlers."""

    # These attributes are provided by DACPHandler
    storage: "Storage"
    _core: "CoreServices"
    connection_manager: Any
    bridge_client: Any
    system_intent_handler: Any

    # Methods from DACPHandler that we need - signatures must match exactly
    @staticmethod
    def _meta_from_request(
        request: Any, bridge_meta: dict[str, Any] | None = None
    ) -> Any:
        raise NotImplementedError

    async def _send_error(
        self: "DACPHandler",
        sender: MessageSender,
        response_type: str,
        error: str,
        request: Any,
        bridge_meta: dict[str, Any] | None = None,
    ) -> None:
        raise NotImplementedError

    async def _send_model(
        self: "DACPHandler", sender: MessageSender, model: Any
    ) -> None:
        raise NotImplementedError

    def _get_session_identity(
        self: "DACPHandler", session_id: str | None, wcp_sessions: WcpSessions | None
    ) -> Any:
        raise NotImplementedError

    def _get_instance_uuid(
        self: "DACPHandler", session_id: str, wcp_sessions: WcpSessions
    ) -> str:
        raise NotImplementedError

    @staticmethod
    def _log_bridge_error_details(bridge_resp: dict[str, Any]) -> None:
        raise NotImplementedError

    @staticmethod
    def _normalize_app_id(app_id: str | None) -> str | None:
        raise NotImplementedError

    async def _resolve_app_id_by_name(self: "DACPHandler", app_name: str) -> str | None:
        raise NotImplementedError

    # ─────────────────────────────────────────────────────────────────────
    # Static helper methods for intent/app metadata
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_storage_app_id(meta: object) -> str | None:
        return getattr(meta, "app_id", None) or getattr(meta, "appId", None)

    @staticmethod
    def _extract_storage_intents(meta: object | None) -> list[str]:
        if meta is None:
            return []
        intents = getattr(meta, "intents", None)
        if isinstance(intents, list):
            return [i for i in intents if isinstance(i, str)]
        if isinstance(intents, Iterable) and not isinstance(intents, (str, bytes)):
            return [i for i in intents if isinstance(i, str)]
        return []

    @staticmethod
    def _extract_storage_result_type(meta: object | None) -> str | None:
        return getattr(meta, "resultType", None) if meta is not None else None

    @staticmethod
    def _wire_app_metadata(app_id: str, meta: object | None) -> AppMetadata:
        return AppMetadata(
            appId=app_id,
            name=getattr(meta, "name", None) if meta is not None else None,
            version=getattr(meta, "version", None) if meta is not None else None,
            description=getattr(meta, "description", None)
            if meta is not None
            else None,
            icons=getattr(meta, "icons", None) if meta is not None else None,
            resultType=getattr(meta, "resultType", None) if meta is not None else None,
        )

    @staticmethod
    def _is_nothing_context(context: Fdc3Context | None) -> bool:
        return isinstance(context, dict) and context.get("type") == "fdc3.nothing"

    @staticmethod
    def _normalize_context(context: object | None) -> Fdc3Context | None:
        if context is None:
            return None
        if isinstance(context, dict):
            return cast(Fdc3Context, dict(context))
        return None

    @staticmethod
    def _context_as_dict(context: Fdc3Context | None) -> dict[str, Any] | None:
        if context is None:
            return None
        return cast(dict[str, Any], dict(context))

    @staticmethod
    def _matches_result_type(requested: str | None, app_result: str | None) -> bool:
        if not requested:
            return True
        if not app_result:
            return False

        req = requested.strip()
        app = app_result.strip()
        if req == app:
            return True

        # If a channel is requested, accept typed channel results too.
        if req == "channel" and app.startswith("channel<") and app.endswith(">"):
            return True

        # If a typed channel is requested, only accept matching typed channel.
        if req.startswith("channel<") and req.endswith(">"):
            return app == req

        return False

    @staticmethod
    def _extract_typed_channel_context(result_type: str | None) -> str | None:
        if not result_type:
            return None
        value = result_type.strip()
        if value.startswith("channel<") and value.endswith(">"):
            inner = value[len("channel<") : -1].strip()
            return inner or None
        return None

    async def _get_app_metadata_cached(
        self: "DACPHandler", app_id: str, cache: dict[str, object]
    ) -> object | None:
        if app_id in cache:
            return cache[app_id]
        try:
            meta = await self.storage.apps.get_app_metadata(app_id)
        except Exception:
            meta = None
        if meta is not None:
            cache[app_id] = meta
        return meta

    async def _collect_app_intents_by_context(
        self: "DACPHandler",
        context: Fdc3Context,
        result_type: str | None,
        *,
        enforce_context: bool = False,
    ) -> tuple[list[AppIntent], bool]:
        """Collect app intents that can handle a given context.

        Uses app directory intents and runtime listeners; filters by resultType
        when available. Context compatibility is applied when intent metadata
        provides compatible context types.
        """
        context_type: str | None = (
            context.get("type") if isinstance(context, dict) else None
        )
        intent_to_apps: dict[str, dict[str, list[str] | None]] = {}
        app_meta_by_id: dict[str, object] = {}
        has_context_constraints = False

        def _normalize_intent_entry(
            entry: IntentEntry,
        ) -> tuple[str, list[str] | None] | None:
            if isinstance(entry, str):
                return entry, None
            if isinstance(entry, IntentEntryMapping):
                entry_dict = entry.model_dump()
            elif isinstance(entry, Mapping):
                entry_dict = entry
            else:
                return None
            if isinstance(entry_dict, Mapping):
                name = (
                    entry_dict.get("name")
                    or entry_dict.get("intent")
                    or entry_dict.get("intentName")
                )
                if not isinstance(name, str) or not name:
                    return None
                contexts = entry_dict.get("contexts") or entry_dict.get("contextTypes")
                if isinstance(contexts, str):
                    contexts_list = [contexts]
                elif isinstance(contexts, list):
                    contexts_list = [c for c in contexts if isinstance(c, str)]
                else:
                    contexts_list = None
                return name, contexts_list
            return None

        # Directory intents
        try:
            listed: Iterable[object] = await self.storage.apps.list_apps()
        except Exception:
            listed = []
        if not isinstance(listed, list):
            listed = list(listed)

        for meta in listed or []:
            app_id = self._extract_storage_app_id(meta)
            if not app_id:
                continue
            intents = getattr(meta, "intents", None) or []
            intent_entries: list[IntentEntry] = (
                list(intents)
                if isinstance(intents, Iterable)
                and not isinstance(intents, (str, bytes))
                else []
            )
            app_meta_by_id[app_id] = meta
            for intent_entry in intent_entries:
                normalized = _normalize_intent_entry(intent_entry)
                if not normalized:
                    continue
                intent_name, ctx_types = normalized
                if ctx_types is not None:
                    has_context_constraints = True
                intent_to_apps.setdefault(intent_name, {})[app_id] = ctx_types

        # Runtime listeners
        try:
            listeners = getattr(self._core.listener_store, "intent_listeners", {})
        except Exception:
            listeners = {}
        for listener in (listeners or {}).values():
            intent = getattr(listener, "intent", None)
            instance_uuid = getattr(listener, "instance_uuid", None)
            if not intent or not instance_uuid:
                continue
            inst = self._core.app_registry.get_instance(instance_uuid)
            if inst is not None and getattr(inst, "app_id", None):
                intent_to_apps.setdefault(intent, {}).setdefault(inst.app_id, None)

        app_intents: list[AppIntent] = []
        for intent in sorted(intent_to_apps.keys()):
            apps: list[AppMetadata] = []
            for app_id, ctx_types in sorted(intent_to_apps[intent].items()):
                if (
                    enforce_context
                    and context_type
                    and ctx_types is not None
                    and context_type not in ctx_types
                ):
                    continue

                meta = await self._get_app_metadata_cached(app_id, app_meta_by_id)
                app_result_type = getattr(meta, "resultType", None) if meta else None
                typed_channel_context = self._extract_typed_channel_context(
                    app_result_type
                )
                if typed_channel_context:
                    has_context_constraints = True
                    if context_type and typed_channel_context != context_type:
                        continue

                if not self._matches_result_type(result_type, app_result_type):
                    continue

                apps.append(self._wire_app_metadata(app_id, meta))

            if apps:
                app_intents.append(
                    AppIntent(intent=IntentMetadata(name=intent), apps=apps)
                )

        return app_intents, has_context_constraints

    # ─────────────────────────────────────────────────────────────────────
    # Intent handlers
    # ─────────────────────────────────────────────────────────────────────

    @dacp_handler(FindIntentRequest, needs_session=False)
    async def _handle_find_intent(
        self: "DACPHandler", request: FindIntentRequest, *, sender: MessageSender
    ):
        """Handle findIntent request.

        This is a best-effort implementation based on the app directory (static
        metadata) and currently registered intent listeners (runtime).
        """
        try:
            payload = request.payload
            intent = payload.intent
            if not intent:
                await self._send_error(
                    sender, "findIntentResponse", DACPError.NO_APPS_FOUND, request
                )
                return
            app_ids: set[str] = set()
            app_meta_by_id: dict[str, object] = {}

            # From app directory
            try:
                listed = await self.storage.apps.list_apps()
            except Exception:
                listed = []

            for meta in listed or []:
                app_id = self._extract_storage_app_id(meta)
                intents = self._extract_storage_intents(meta)
                if app_id and intent in intents:
                    if self._matches_result_type(
                        payload.resultType,
                        self._extract_storage_result_type(meta),
                    ):
                        app_ids.add(app_id)
                        app_meta_by_id[app_id] = meta

            # From runtime listeners
            try:
                listeners = self._core.listener_store.get_intent_listeners_for_intent(
                    intent
                )
            except Exception:
                listeners = []

            for listener in listeners:
                instance_uuid = getattr(listener, "instance_uuid", None)
                if not instance_uuid:
                    continue
                inst = self._core.app_registry.get_instance(instance_uuid)
                if inst is not None and getattr(inst, "app_id", None):
                    app_ids.add(inst.app_id)

            target = payload.target
            if target is not None:
                target_app_id = self._normalize_app_id(target.appId)
                if not target_app_id:
                    await self._send_error(
                        sender,
                        "findIntentResponse",
                        DACPError.TARGET_APP_UNAVAILABLE,
                        request,
                    )
                    return
                target_instance_id = target.instanceId
                if target_instance_id:
                    instances = self._core.app_registry.get_instances_for_app(
                        target_app_id
                    )
                    if not any(
                        getattr(i, "instance_id", None) == target_instance_id
                        for i in instances
                    ):
                        await self._send_error(
                            sender,
                            "findIntentResponse",
                            DACPError.TARGET_INSTANCE_UNAVAILABLE,
                            request,
                        )
                        return

                if target_app_id not in app_ids:
                    # If app is known in directory, allow it; otherwise treat as unavailable.
                    try:
                        known = await self.storage.apps.get_app_metadata(target_app_id)
                    except Exception:
                        known = None
                    if not known:
                        await self._send_error(
                            sender,
                            "findIntentResponse",
                            DACPError.TARGET_APP_UNAVAILABLE,
                            request,
                        )
                        return
                    app_ids = {target_app_id}

            if not app_ids:
                await self._send_error(
                    sender, "findIntentResponse", DACPError.NO_APPS_FOUND, request
                )
                return

            apps: list[AppMetadata] = []
            for app_id in sorted(app_ids):
                meta = app_meta_by_id.get(app_id)
                if meta is None and payload.resultType:
                    meta = await self._get_app_metadata_cached(app_id, app_meta_by_id)

                if not self._matches_result_type(
                    payload.resultType,
                    self._extract_storage_result_type(meta),
                ):
                    continue
                apps.append(self._wire_app_metadata(app_id, meta))

            if not apps:
                logger.debug(
                    "findIntent no apps after filtering intent=%s resultType=%s",
                    intent,
                    payload.resultType,
                )
                await self._send_error(
                    sender, "findIntentResponse", DACPError.NO_APPS_FOUND, request
                )
                return

            logger.debug(
                "findIntent resolved %s apps for intent=%s resultType=%s",
                len(apps),
                intent,
                payload.resultType,
            )

            app_intent = AppIntent(intent=IntentMetadata(name=intent), apps=apps)
            response = FindIntentResponse(
                type="findIntentResponse",
                payload=FindIntentResponsePayload(appIntent=app_intent),
                meta=self._meta_from_request(request),
            )
            await self._send_model(sender, response)
        except Exception:
            logger.exception("Error handling findIntent")
            await self._send_error(
                sender, "findIntentResponse", DACPError.RESOLVER_UNAVAILABLE, request
            )

    @dacp_handler(FindIntentsByContextRequest, needs_session=False)
    async def _handle_find_intents_by_context(
        self: "DACPHandler",
        request: FindIntentsByContextRequest,
        *,
        sender: MessageSender,
    ):
        """Handle findIntentsByContext request.

        This agent does not yet maintain intent<->context type mappings.
        As a best-effort, return intents declared by the app directory and
        by currently registered intent listeners (ignoring compatibility).
        """
        try:
            context = request.payload.context
            if self._is_nothing_context(context):
                context = cast(Fdc3Context, {})

            app_intents, _ = await self._collect_app_intents_by_context(
                context,
                request.payload.resultType,
            )

            if not app_intents:
                await self._send_error(
                    sender,
                    "findIntentsByContextResponse",
                    DACPError.NO_APPS_FOUND,
                    request,
                )
                return

            response = FindIntentsByContextResponse(
                type="findIntentsByContextResponse",
                payload=FindIntentsByContextResponsePayload(appIntents=app_intents),
                meta=self._meta_from_request(request),
            )
            await self._send_model(sender, response)
        except Exception:
            logger.exception("Error handling findIntentsByContext")
            await self._send_error(
                sender,
                "findIntentsByContextResponse",
                DACPError.RESOLVER_UNAVAILABLE,
                request,
            )

    @dacp_handler(RaiseIntentRequest, needs_session=True)
    async def _handle_raise_intent(
        self: "DACPHandler",
        request: RaiseIntentRequest,
        sender: MessageSender,
        *,
        session_id: str | None = None,
        wcp_sessions: WcpSessions | None = None,
    ):
        """Handle raise intent request"""
        normalized_context = self._normalize_context(request.payload.context)
        context_payload = normalized_context or request.payload.context

        target = request.payload.target
        if isinstance(target, AppIdentifier):
            if not target.desktopAgent:
                normalized_target_id = self._normalize_app_id(target.appId)
                if normalized_target_id and normalized_target_id != target.appId:
                    target = AppIdentifier(
                        appId=normalized_target_id,
                        instanceId=target.instanceId,
                        desktopAgent=target.desktopAgent,
                    )
        elif isinstance(target, str):
            resolved = await self._resolve_app_id_by_name(target)
            normalized_target_id = self._normalize_app_id(resolved or target)
            if normalized_target_id:
                target = AppIdentifier(
                    appId=normalized_target_id, instanceId=None, desktopAgent=None
                )

        if target is not None and not isinstance(target, AppIdentifier):
            target = None

        if target is not None and target != request.payload.target:
            request.payload.target = target

        # Agent bridging: if a target is provided with a remote desktopAgent, forward.
        try:
            target_da = getattr(target, "desktopAgent", None) if target else None
            bridge = getattr(self, "bridge_client", None)
            if target_da and session_id:
                if bridge is None or not getattr(bridge, "is_connected", False):
                    await self._send_error(
                        sender,
                        "raiseIntentResponse",
                        BridgingError.NotConnectedToBridge.value,
                        request,
                    )
                    return
                if hasattr(
                    bridge, "has_connected_agent"
                ) and not bridge.has_connected_agent(target_da):
                    await self._send_error(
                        sender,
                        "raiseIntentResponse",
                        ResolveError.DesktopAgentNotFound.value,
                        request,
                    )
                    return
                source_identity: AppIdentifier
                if getattr(request.meta, "source", None) is not None:
                    src = request.meta.source
                    source_identity = (
                        src
                        if isinstance(src, AppIdentifier)
                        else AppIdentifier.model_validate(src)
                    )
                else:
                    identity = self._get_session_identity(session_id, wcp_sessions)
                    source_identity = AppIdentifier(
                        appId=identity.appId or "unknown",
                        instanceId=identity.instanceId,
                        desktopAgent=None,
                    )

                try:
                    bridge_resp = await bridge.send_agent_request(
                        request_type="raiseIntentRequest",
                        payload={
                            "intent": request.payload.intent,
                            "context": context_payload,
                            "app": target.model_dump() if target else None,
                        },
                        source=source_identity,
                        destination=target,
                    )
                except asyncio.TimeoutError:
                    await self._send_error(
                        sender,
                        "raiseIntentResponse",
                        BridgingError.ResponseToBridgeTimedOut.value,
                        request,
                    )
                    return
                except RuntimeError as exc:
                    if str(exc) == BridgingError.NotConnectedToBridge.value:
                        await self._send_error(
                            sender,
                            "raiseIntentResponse",
                            BridgingError.NotConnectedToBridge.value,
                            request,
                        )
                        return
                    if str(exc) == BridgingError.AgentDisconnected.value:
                        await self._send_error(
                            sender,
                            "raiseIntentResponse",
                            BridgingError.AgentDisconnected.value,
                            request,
                        )
                        return
                    raise

                self._log_bridge_error_details(bridge_resp)
                bridge_meta = bridge_resp.get("meta") or {}
                payload = bridge_resp.get("payload") or {}
                if payload.get("error"):
                    response = AgentResponse(
                        type="raiseIntentResponse",
                        payload=ErrorResponsePayload(error=str(payload.get("error"))),
                        meta=self._meta_from_request(request, bridge_meta),
                    )
                else:
                    intent_resolution_raw = payload.get("intentResolution")
                    intent_resolution = WireIntentResolution.model_validate(
                        intent_resolution_raw
                    )
                    response = RaiseIntentResponse(
                        type="raiseIntentResponse",
                        payload=RaiseIntentResponsePayload(
                            intentResolution=intent_resolution
                        ),
                        meta=self._meta_from_request(request, bridge_meta),
                    )
                await self._send_model(sender, response)
                return
        except Exception:
            # Fall back to local resolution.
            pass

        # Check if this is a system intent first
        if self.system_intent_handler.is_system_intent(request.payload.intent):
            response = await self.system_intent_handler.handle_system_intent(
                request.payload.intent,
                self._context_as_dict(normalized_context),
                target,
                sender,
                request.meta.requestUuid,
            )
            if response:
                await self._send_model(sender, response)
                return

        # Check if a plugin handles this intent
        plugin_result = await self._try_plugin_handler(request)
        if plugin_result is not None:
            await self._send_model(sender, plugin_result)
            return

        # Check if an external handler can handle this intent
        external_result = await self._try_external_handler(request, sender)
        if external_result is not None:
            # external_result is either an AgentResponse or RaiseIntentResponse
            await self._send_model(sender, external_result)
            return

        # Not a system intent or plugin, try normal resolution
        resolution: IntentResolution | None = self._core.intent_resolver.resolve_intent(
            request.payload.intent,
            self._context_as_dict(normalized_context),
            target,
        )

        if resolution:
            response = RaiseIntentResponse(
                type="raiseIntentResponse",
                payload=RaiseIntentResponsePayload(
                    intentResolution=resolution.model_dump()
                ),
                meta=self._meta_from_request(request),
            )
            await self._send_model(sender, response)

            # Send intent event to listeners, preferring the calculated resolution
            # to avoid races between resolution and listener changes.
            if hasattr(
                self._core.intent_resolver, "deliver_intent_event_with_resolution"
            ):
                targets = (
                    self._core.intent_resolver.deliver_intent_event_with_resolution(
                        request.payload.intent,
                        self._context_as_dict(normalized_context),
                        resolution,
                        request.meta.source,
                    )
                )
            else:
                targets = self._core.intent_resolver.deliver_intent_event(
                    request.payload.intent,
                    self._context_as_dict(normalized_context),
                    request.meta.source,
                )

            for target_uuid in targets:
                event = IntentEvent(
                    type="intentEvent",
                    payload=IntentEventPayload(
                        intent=request.payload.intent,
                        context=context_payload,
                        originatingApp=request.meta.source,
                    ),
                    meta=AgentEventMeta(),
                )
                await self.connection_manager.send_to_instance(
                    target_uuid, event.model_dump_json()
                )
        else:
            await self._send_error(
                sender, "raiseIntentResponse", DACPError.NO_APPS_FOUND, request
            )

    @dacp_handler(RaiseIntentForContextRequest, needs_session=False)
    async def _handle_raise_intent_for_context(
        self: "DACPHandler",
        request: RaiseIntentForContextRequest,
        *,
        sender: MessageSender,
    ):
        """Handle raise intent for context request"""
        try:
            context = request.payload.context
            if self._is_nothing_context(context):
                context = cast(Fdc3Context, {})

            normalized_context = self._normalize_context(context)
            context_payload = normalized_context or context

            app_intents, has_constraints = await self._collect_app_intents_by_context(
                context,
                request.payload.resultType,
                enforce_context=True,
            )
            target = request.payload.target
            if target is not None:
                target_app_id = self._normalize_app_id(target.appId)
                target_instance_id = target.instanceId
                if not target_app_id:
                    await self._send_error(
                        sender,
                        "raiseIntentForContextResponse",
                        DACPError.TARGET_APP_UNAVAILABLE,
                        request,
                    )
                    return

                if target_instance_id:
                    instances = self._core.app_registry.get_instances_for_app(
                        target_app_id
                    )
                    if not any(
                        getattr(inst, "instance_id", None) == target_instance_id
                        for inst in instances
                    ):
                        await self._send_error(
                            sender,
                            "raiseIntentForContextResponse",
                            DACPError.TARGET_INSTANCE_UNAVAILABLE,
                            request,
                        )
                        return

                if app_intents:
                    filtered: list[AppIntent] = []
                    for app_intent in app_intents:
                        if any(app.appId == target_app_id for app in app_intent.apps):
                            filtered.append(app_intent)
                    app_intents = filtered

                if not app_intents:
                    try:
                        known = await self.storage.apps.get_app_metadata(target_app_id)
                    except Exception:
                        known = None

                    await self._send_error(
                        sender,
                        "raiseIntentForContextResponse",
                        DACPError.TARGET_APP_UNAVAILABLE
                        if known is None
                        else DACPError.NO_APPS_FOUND,
                        request,
                    )
                    return

            if not app_intents:
                if has_constraints:
                    await self._send_error(
                        sender,
                        "raiseIntentForContextResponse",
                        DACPError.NO_APPS_FOUND,
                        request,
                    )
                    return

                # Fall back to runtime listeners to infer intent ambiguity
                try:
                    listeners = getattr(
                        self._core.listener_store, "intent_listeners", {}
                    )
                except Exception:
                    listeners = {}

                intents = {
                    getattr(listener, "intent", None)
                    for listener in (listeners or {}).values()
                }
                intents.discard(None)

                if not intents:
                    await self._send_error(
                        sender,
                        "raiseIntentForContextResponse",
                        DACPError.NO_APPS_FOUND,
                        request,
                    )
                    return

                if len(intents) != 1:
                    await self._send_error(
                        sender,
                        "raiseIntentForContextResponse",
                        DACPError.RESOLVER_UNAVAILABLE,
                        request,
                    )
                    return

                intent = next(iter(intents))
            else:
                if len(app_intents) != 1:
                    await self._send_error(
                        sender,
                        "raiseIntentForContextResponse",
                        DACPError.RESOLVER_UNAVAILABLE,
                        request,
                    )
                    return

                intent = app_intents[0].intent.name
            resolution: IntentResolution | None = (
                self._core.intent_resolver.resolve_intent(
                    intent,
                    self._context_as_dict(normalized_context),
                    request.payload.target,
                )
            )

            if not resolution:
                await self._send_error(
                    sender,
                    "raiseIntentForContextResponse",
                    DACPError.NO_APPS_FOUND,
                    request,
                )
                return

            intent_resolution = WireIntentResolution.model_validate(
                resolution.model_dump()
            )
            response = RaiseIntentForContextResponse(
                type="raiseIntentForContextResponse",
                payload=RaiseIntentForContextResponsePayload(
                    intentResolution=intent_resolution
                ),
                meta=self._meta_from_request(request),
            )
            await self._send_model(sender, response)

            # Send intent event to listeners (mirrors raiseIntent behavior), preferring
            # the calculated resolution to avoid races.
            if hasattr(
                self._core.intent_resolver, "deliver_intent_event_with_resolution"
            ):
                targets = (
                    self._core.intent_resolver.deliver_intent_event_with_resolution(
                        intent,
                        self._context_as_dict(normalized_context),
                        resolution,
                        request.meta.source,
                    )
                )
            else:
                targets = self._core.intent_resolver.deliver_intent_event(
                    intent,
                    self._context_as_dict(normalized_context),
                    request.meta.source,
                )
            for target_uuid in targets:
                event = IntentEvent(
                    type="intentEvent",
                    payload=IntentEventPayload(
                        intent=intent,
                        context=context_payload,
                        originatingApp=request.meta.source,
                    ),
                    meta=AgentEventMeta(),
                )
                await self.connection_manager.send_to_instance(
                    target_uuid, event.model_dump_json()
                )
        except Exception:
            logger.exception("Error handling raiseIntentForContext")
            await self._send_error(
                sender,
                "raiseIntentForContextResponse",
                DACPError.RESOLVER_UNAVAILABLE,
                request,
            )

    @dacp_handler(IntentResultRequest, needs_session=False)
    async def _handle_intent_result_request(
        self: "DACPHandler", request: IntentResultRequest, *, sender: MessageSender
    ):
        """Handle intent result request"""
        logger.debug(f"Received intent result: {request.payload.intentResult}")

        response = IntentResultResponse(
            type="intentResultResponse",
            payload=IntentResultResponsePayload(),
            meta=self._meta_from_request(request),
        )
        await self._send_model(sender, response)

    @dacp_handler(RaiseIntentResultResponse, needs_session=False)
    async def _handle_raise_intent_result_response(
        self: "DACPHandler",
        request: RaiseIntentResultResponse,
        *,
        sender: MessageSender,
    ):
        """Handle raise intent result response"""
        logger.debug(f"Intent result acknowledged: {request.meta.requestUuid}")

    # ─────────────────────────────────────────────────────────────────────
    # Plugin & external handler support
    # ─────────────────────────────────────────────────────────────────────

    async def _try_plugin_handler(
        self: "DACPHandler", request: RaiseIntentRequest
    ) -> AgentResponse | RaiseIntentResponse | None:
        """Try to handle intent via registered plugins.

        Args:
            request: The RaiseIntentRequest from the client.

        Returns:
            Response model if a plugin handled the intent, None otherwise.
        """
        plugin_registry = getattr(self._core, "plugin_registry", None)
        plugins = (
            plugin_registry.get_plugins_for_intent(request.payload.intent)
            if plugin_registry
            else []
        )

        for plugin in plugins:
            try:
                result = await plugin.handle_intent(
                    request.payload.intent,
                    self._context_as_dict(
                        self._normalize_context(request.payload.context)
                    ),
                    request.meta.source.model_dump() if request.meta.source else None,
                )

                if result.handled:
                    if result.error:
                        # Plugin handled but returned an error
                        return AgentResponse(
                            type="raiseIntentResponse",
                            payload=ErrorResponsePayload(error=result.error),
                            meta=self._meta_from_request(request),
                        )

                    # Plugin handled successfully
                    resolution = IntentResolution(
                        source=AppIdentifier(
                            appId=f"plugin:{plugin.name}",
                            instanceId=None,
                            desktopAgent=None,
                        ),
                        intent=request.payload.intent,
                    )
                    return RaiseIntentResponse(
                        type="raiseIntentResponse",
                        payload=RaiseIntentResponsePayload(
                            intentResolution=resolution.model_dump()
                        ),
                        meta=self._meta_from_request(request),
                    )

            except Exception as e:
                logger.error(
                    f"Plugin {plugin.name} raised exception handling "
                    f"{request.payload.intent}: {e}"
                )
                # Continue to next plugin

        return None

    # ─────────────────────────────────────────────────────────────────────
    # External handler registration
    # ─────────────────────────────────────────────────────────────────────

    @dacp_handler(RegisterExternalHandlerRequest, needs_session=True)
    async def _handle_register_external_handler(
        self: "DACPHandler",
        request: RegisterExternalHandlerRequest,
        *,
        session_id: str,
        wcp_sessions: WcpSessions,
        sender: MessageSender,
    ) -> None:
        """Handle external handler registration - message already validated by parser."""
        logger.debug(
            "_handle_register_external_handler called: session_id=%s wcp_sessions_keys=%s meta=%s",
            session_id,
            list(wcp_sessions.keys()),
            getattr(request, "meta", None),
        )

        try:
            instance_uuid = self._get_instance_uuid(session_id, wcp_sessions)
            handler_uuid = await self._core.register_external_handler(
                instance_uuid,
                request.payload.handler_id,
                request.payload.intents,
                request.payload.priority,
                request.payload.metadata,
            )

            # send success response
            response = RegisterExternalHandlerResponse(
                payload=RegisterExternalHandlerResponsePayload(
                    handler_uuid=handler_uuid
                ),
                meta=self._meta_from_request(request),
            )
            logger.debug(
                "Sending registerExternalHandlerResponse: handler_uuid=%s requestUuid=%s",
                handler_uuid,
                request.meta.requestUuid.root,
            )
            await sender.send_model(response)
        except Exception:
            logger.exception("Failed to register external handler")
            await self._send_error(
                sender,
                "registerExternalHandlerResponse",
                DACPError.INTERNAL_ERROR,
                request,
            )

    @dacp_handler(UnregisterExternalHandlerRequest, needs_session=True)
    async def _handle_unregister_external_handler(
        self: "DACPHandler",
        request: UnregisterExternalHandlerRequest,
        *,
        session_id: str,
        wcp_sessions: WcpSessions,
        sender: MessageSender,
    ):
        """Handle external handler unregistration - message already validated by parser."""
        try:
            await self._core.unregister_external_handler(request.payload.handler_uuid)

            # Send success response using Pydantic model
            response = UnregisterExternalHandlerResponse(
                meta=self._meta_from_request(request),
            )
            await sender.send_model(response)
        except Exception:
            logger.exception("Failed to unregister external handler")
            await self._send_error(
                sender,
                "unregisterExternalHandlerResponse",
                DACPError.INTERNAL_ERROR,
                request,
            )

    @dacp_handler(ExternalIntentResultRequest, needs_session=False)
    async def _handle_external_intent_result(
        self: "DACPHandler",
        request: ExternalIntentResultRequest,
        *,
        sender: MessageSender,
    ) -> None:
        """Handle intent result from external handler - message already validated by parser."""
        try:
            self._core.resolve_pending_intent(
                request.payload.request_uuid,
                result=request.payload.result,
                error=request.payload.error,
            )
        except Exception:
            logger.exception("Failed to handle external intent result")

    async def _try_external_handler(
        self: "DACPHandler", request: RaiseIntentRequest, sender: MessageSender
    ) -> RaiseIntentResponse | AgentResponse | None:
        """Try to handle intent via registered external handlers.

        Args:
            request: The validated RaiseIntentRequest from the client.
            sender: The message sender to respond on.

        Returns:
            Response model if an external handler processed the intent, None otherwise.
        """
        # Find registered external handlers for this intent (guard core stub)
        external_registry = getattr(self._core, "external_registry", None)
        if external_registry is None:
            return None
        handlers = external_registry.get_handlers_for_intent(request.payload.intent)
        if not handlers:
            return None

        # Choose first handler (highest priority)
        handler = handlers[0]

        # Build forwarded intent message using Pydantic model
        request_uuid = str(uuid.uuid4())
        forwarded = ForwardedIntentMessage(
            payload=ForwardedIntentPayload(
                request_uuid=request_uuid,
                intent=request.payload.intent,
                context=self._context_as_dict(
                    self._normalize_context(request.payload.context)
                )
                or {},
                source=request.meta.source,
            )
        )

        # Create pending future for response correlation
        fut = self._core.create_pending_intent(request_uuid)

        try:
            # Send forwarded intent message using Pydantic serialization
            await self.connection_manager.send_to_instance(
                handler.instance_uuid, forwarded.model_dump_json()
            )
        except Exception as e:
            logger.exception(
                f"Failed to forward intent to external handler {handler.handler_id}: {e}"
            )
            self._core.resolve_pending_intent(request_uuid, error=str(e))
            return None

        try:
            # Wait for result with a reasonable timeout
            result = await asyncio.wait_for(fut, timeout=30.0)
        except asyncio.TimeoutError:
            logger.debug(f"External handler {handler.handler_id} timed out")
            return None
        except Exception as e:
            logger.debug(f"External handler failed: {e}")
            return None

        if result is None:
            return None

        # Build response using the result
        resolution = IntentResolution(
            source=AppIdentifier(
                appId=f"external:{handler.handler_id}",
                instanceId=None,
                desktopAgent=None,
            ),
            intent=request.payload.intent,
        )
        return RaiseIntentResponse(
            type="raiseIntentResponse",
            payload=RaiseIntentResponsePayload(
                intentResolution=resolution.model_dump()
            ),
            meta=self._meta_from_request(request),
        )
