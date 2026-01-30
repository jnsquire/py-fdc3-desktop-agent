"""
App-related DACP handlers: getInfo, getAppMetadata, findInstances, open.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from fdc3.models.dacp.dacp import (
    GetInfoRequest,
    GetInfoResponse,
    GetInfoResponsePayload,
    GetAppMetadataRequest,
    GetAppMetadataResponse,
    GetAppMetadataResponsePayload,
    FindInstancesRequest,
    FindInstancesResponse,
    FindInstancesResponsePayload,
    OpenRequest,
    OpenResponse,
    OpenResponsePayload,
    AgentResponse,
    ErrorResponsePayload,
)
from fdc3.models.identifiers import (
    AppIdentifier,
    ImplementationMetadata,
    AppMetadata,
)
from ...api import BridgingError, OpenError
from ...types import WcpSessions
from ...version import __version__
from ..protocols import MessageSender
from .registry import dacp_handler, DACPError

if TYPE_CHECKING:
    from .base import DACPHandler, BridgeClientProtocol
    from ...core import CoreServices
    from ...storage import Storage
    from ...launcher.interfaces import ProcessLauncher

logger = logging.getLogger(__name__)


class AppHandlersMixin:
    """Mixin providing app-related DACP handlers."""

    # These attributes are provided by DACPHandler
    storage: "Storage"
    launcher: "ProcessLauncher"
    bridge_client: "BridgeClientProtocol | None"
    _core: "CoreServices"

    @dacp_handler(GetInfoRequest, needs_session=True)
    async def _handle_get_info(
        self: "DACPHandler",
        request: GetInfoRequest,
        *,
        session_id: str,
        wcp_sessions: WcpSessions,
        sender: MessageSender,
    ) -> None:
        identity = self._get_session_identity(session_id, wcp_sessions)
        app_id = identity.appId or "unknown"
        instance_id = identity.instanceId

        # Best-effort: enrich app metadata from storage if available.
        name = None
        version = None
        description = None
        icons = None
        if app_id and app_id != "unknown":
            try:
                meta = await self.storage.apps.get_app_metadata(app_id)
            except Exception:
                logger.debug(
                    "getInfo: failed to load app metadata from storage", exc_info=True
                )
                meta = None

            if meta is not None:
                name = getattr(meta, "name", None)
                version = getattr(meta, "version", None)
                description = getattr(meta, "description", None)
                icons = getattr(meta, "icons", None)

        impl = ImplementationMetadata(
            fdc3Version="2.2",
            provider="py-fdc3-desktop-agent",
            providerVersion=__version__,
            optionalFeatures={
                # We do not currently expose originating app metadata on
                # context/intent delivery payloads.
                "OriginatingAppMetadata": False,
                "UserChannelMembershipAPIs": True,
                # Bridging is optional and only available when configured.
                "DesktopAgentBridging": self.bridge_client is not None,
            },
            appMetadata=AppMetadata(
                appId=app_id,
                instanceId=instance_id,
                name=name,
                version=version,
                description=description,
                icons=icons,
            ),
        )

        response = GetInfoResponse(
            type="getInfoResponse",
            payload=GetInfoResponsePayload(implementationMetadata=impl),
            meta=self._meta_from_request(request),
        )
        await self._send_model(sender, response)

    @dacp_handler(GetAppMetadataRequest, needs_session=False)
    async def _handle_get_app_metadata(
        self: "DACPHandler", request: GetAppMetadataRequest, *, sender: MessageSender
    ) -> None:
        app_id = self._normalize_app_id(request.payload.app.appId)
        if not app_id:
            await self._send_error(
                sender, "getAppMetadataResponse", DACPError.APP_NOT_FOUND, request
            )
            return

        try:
            meta = await self.storage.apps.get_app_metadata(app_id)
        except Exception:
            logger.debug(
                "getAppMetadata: failed to load app metadata from storage",
                exc_info=True,
            )
            meta = None

        if not meta:
            await self._send_error(
                sender, "getAppMetadataResponse", DACPError.APP_NOT_FOUND, request
            )
            return

        resolved_app_id = self._extract_storage_app_id(meta) or app_id
        app_meta = self._wire_app_metadata(resolved_app_id, meta)

        response = GetAppMetadataResponse(
            type="getAppMetadataResponse",
            payload=GetAppMetadataResponsePayload(appMetadata=app_meta),
            meta=self._meta_from_request(request),
        )
        await self._send_model(sender, response)

    @dacp_handler(FindInstancesRequest, needs_session=False)
    async def _handle_find_instances(
        self: "DACPHandler", request: FindInstancesRequest, *, sender: MessageSender
    ):
        """Handle findInstances request.

        Returns the list of currently known runtime instances for the given appId.
        """
        try:
            payload = request.payload
            app_id = (
                self._normalize_app_id(payload.app.appId)
                if payload.app is not None
                else None
            )
            requested_instance_id = (
                payload.app.instanceId if payload.app is not None else None
            )
            if not app_id:
                # If no appId provided, return empty list (bridge expects empty payload)
                response = FindInstancesResponse(
                    type="findInstancesResponse",
                    payload=FindInstancesResponsePayload(instances=[]),
                    meta=self._meta_from_request(request),
                )
                await self._send_model(sender, response)
                return

            instances = self._core.app_registry.get_instances_for_app(app_id)

            result: list[AppIdentifier] = []
            for inst in instances:
                inst_id = getattr(inst, "instance_id", None)
                if requested_instance_id and inst_id != requested_instance_id:
                    continue
                if inst_id is None:
                    continue
                result.append(
                    AppIdentifier(appId=app_id, instanceId=inst_id, desktopAgent=None)
                )

            response = FindInstancesResponse(
                type="findInstancesResponse",
                payload=FindInstancesResponsePayload(instances=result),
                meta=self._meta_from_request(request),
            )
            await self._send_model(sender, response)
        except Exception:
            logger.exception("Error handling findInstances")
            await self._send_error(
                sender,
                "findInstancesResponse",
                DACPError.RESOLVER_UNAVAILABLE,
                request,
            )

    @dacp_handler(OpenRequest, needs_session=True)
    async def _handle_open(
        self: "DACPHandler",
        request: OpenRequest,
        sender: MessageSender,
        *,
        session_id: str | None = None,
        wcp_sessions: WcpSessions | None = None,
    ):
        """Handle open request - launch the specified app"""
        try:
            normalized_context = self._normalize_context(request.payload.context)

            app_value = request.payload.app
            app_identity: AppIdentifier | None = None
            if isinstance(app_value, AppIdentifier):
                if app_value.desktopAgent:
                    app_identity = app_value
                else:
                    normalized_app_id = self._normalize_app_id(app_value.appId)
                    if normalized_app_id:
                        app_identity = AppIdentifier(
                            appId=normalized_app_id,
                            instanceId=app_value.instanceId,
                            desktopAgent=app_value.desktopAgent,
                        )
            elif isinstance(app_value, str):
                normalized_app_id = self._normalize_app_id(app_value)
                resolved = None
                if normalized_app_id:
                    try:
                        meta = await self.storage.apps.get_app_metadata(
                            normalized_app_id
                        )
                    except Exception:
                        meta = None
                    if meta is not None:
                        resolved = normalized_app_id
                if not resolved:
                    resolved = await self._resolve_app_id_by_name(app_value)
                if not resolved:
                    await self._send_error(
                        sender, "openResponse", DACPError.APP_NOT_FOUND, request
                    )
                    return
                app_identity = AppIdentifier(
                    appId=resolved, instanceId=None, desktopAgent=None
                )

            if app_identity is None:
                await self._send_error(
                    sender, "openResponse", DACPError.APP_NOT_FOUND, request
                )
                return

            # If the request targets a remote Desktop Agent (Agent Bridging), forward it.
            target_da = getattr(app_identity, "desktopAgent", None)
            if target_da and session_id:
                bridge = getattr(self, "bridge_client", None)
                if bridge is None or not getattr(bridge, "is_connected", False):
                    await self._send_error(
                        sender,
                        "openResponse",
                        BridgingError.NotConnectedToBridge.value,
                        request,
                    )
                    return
                if hasattr(
                    bridge, "has_connected_agent"
                ) and not bridge.has_connected_agent(target_da):
                    await self._send_error(
                        sender,
                        "openResponse",
                        OpenError.DesktopAgentNotFound.value,
                        request,
                    )
                    return

                identity = self._get_session_identity(session_id, wcp_sessions)
                source_identity = AppIdentifier(
                    appId=identity.appId or "unknown",
                    instanceId=identity.instanceId,
                    desktopAgent=None,
                )

                bridge_payload = {
                    "app": app_identity.model_dump(),
                    "context": normalized_context,
                }
                try:
                    bridge_resp = await bridge.send_agent_request(
                        request_type="openRequest",
                        payload=bridge_payload,
                        source=source_identity,
                        destination=app_identity,
                    )
                except asyncio.TimeoutError:
                    await self._send_error(
                        sender,
                        "openResponse",
                        BridgingError.ResponseToBridgeTimedOut.value,
                        request,
                    )
                    return
                except RuntimeError as exc:
                    if str(exc) == BridgingError.NotConnectedToBridge.value:
                        await self._send_error(
                            sender,
                            "openResponse",
                            BridgingError.NotConnectedToBridge.value,
                            request,
                        )
                        return
                    if str(exc) == BridgingError.AgentDisconnected.value:
                        await self._send_error(
                            sender,
                            "openResponse",
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
                        type="openResponse",
                        payload=ErrorResponsePayload(error=str(payload.get("error"))),
                        meta=self._meta_from_request(request, bridge_meta),
                    )
                else:
                    response = OpenResponse(
                        type="openResponse",
                        payload=OpenResponsePayload(
                            appIdentifier=payload.get("appIdentifier")
                        ),
                        meta=self._meta_from_request(request, bridge_meta),
                    )
                await self._send_model(sender, response)
                return

            app_id = app_identity.appId

            # Check if app exists in directory
            app_metadata = await self.storage.apps.get_app_metadata(app_id)
            if not app_metadata:
                await self._send_error(
                    sender, "openResponse", DACPError.APP_NOT_FOUND, request
                )
                return

            # Check existing instances
            try:
                raw_instances = self._core.app_registry.get_instances_for_app(app_id)
                try:
                    existing_instances = (
                        list(raw_instances) if raw_instances is not None else []
                    )
                except Exception:
                    existing_instances = []
            except Exception:
                existing_instances = []
            requested_instance_id = getattr(request.payload.app, "instanceId", None)

            if requested_instance_id:
                existing_instance = next(
                    (
                        inst
                        for inst in existing_instances
                        if inst.instance_id == requested_instance_id
                    ),
                    None,
                )
                if existing_instance:
                    response = OpenResponse(
                        type="openResponse",
                        payload=OpenResponsePayload(
                            appIdentifier=AppIdentifier(
                                appId=app_id, instanceId=existing_instance.instance_id
                            )
                        ),
                        meta=self._meta_from_request(request),
                    )
                    await self._send_model(sender, response)
                    return
            elif existing_instances:
                # Reuse existing instance
                inst = existing_instances[0]
                response = OpenResponse(
                    type="openResponse",
                    payload=OpenResponsePayload(
                        appIdentifier=AppIdentifier(
                            appId=app_id, instanceId=inst.instance_id
                        )
                    ),
                    meta=self._meta_from_request(request),
                )
                await self._send_model(sender, response)
                return

            # Get launch config
            launch_config = await self.storage.launch_configs.get_launch_config(app_id)
            if not launch_config:
                await self._send_error(
                    sender, "openResponse", DACPError.APP_NOT_FOUND, request
                )
                return

            # Launch the app
            launch_result = await self.launcher.launch_app(
                app_id, launch_config, normalized_context, app_identity
            )

            if launch_result.success:
                if not launch_result.instance_id or not launch_result.instance_uuid:
                    await self._send_error(
                        sender, "openResponse", DACPError.ERROR_ON_LAUNCH, request
                    )
                    return

                # Register as pending
                self._core.app_registry.register_pending_instance(
                    app_id, launch_result.instance_id, launch_result.instance_uuid
                )

                # Wait for connection
                connected = await self._core.app_registry.wait_for_instance_connection(
                    launch_result.instance_uuid, timeout=15.0
                )

                if connected:
                    response = OpenResponse(
                        type="openResponse",
                        payload=OpenResponsePayload(
                            appIdentifier=AppIdentifier(
                                appId=app_id, instanceId=launch_result.instance_id
                            )
                        ),
                        meta=self._meta_from_request(request),
                    )
                    await self._send_model(sender, response)
                else:
                    self._core.app_registry.unregister_instance(
                        launch_result.instance_uuid
                    )
                    await self._send_error(
                        sender, "openResponse", DACPError.APP_TIMEOUT, request
                    )
            else:
                await self._send_error(
                    sender, "openResponse", DACPError.ERROR_ON_LAUNCH, request
                )

        except Exception as e:
            logger.error(f"Failed to open app: {e}")
            # Try to send error response if possible
            try:
                await self._send_error(
                    sender, "openResponse", DACPError.ERROR_ON_LAUNCH, request
                )
            except Exception:
                pass
