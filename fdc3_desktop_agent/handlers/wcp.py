"""
WCP (Web Connection Protocol) message handler.
Handles the initial handshake and app identity validation phase.
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional
import os
import sys
import platform

from fastapi import WebSocket

from ..transport.wcp.wcp import (
    WCP1Hello,
    WCP3Handshake,
    WCP3HandshakePayload,
    WCP4ValidateAppIdentity,
    WCP5ValidateAppIdentityResponse,
    WCP5ValidateAppIdentityResponsePayload,
    WCP5ValidateAppIdentityFailedResponse,
    WCP5ValidateAppIdentityFailedResponsePayload,
)
from pydantic import ValidationError
from ..core import core_services
from ..storage import Storage

logger = logging.getLogger(__name__)


class WCPHandler:
    """Handles WCP (Web Connection Protocol) messages"""

    def __init__(self, storage: Storage):
        self.storage = storage

    async def _send_model(self, websocket: WebSocket, model) -> None:
        """Helper method to send a Pydantic model as JSON over WebSocket"""
        try:
            await websocket.send_text(model.model_dump_json())
        except Exception as e:
            logger.error(f"Failed to send model {model.__class__.__name__}: {e}")

    async def handle_message(
        self,
        message: Dict[str, Any],
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ) -> Optional[str]:
        """
        Handle WCP message and return next phase if transition occurs.

        Returns:
            "dacp" if transitioning to DACP phase
            None if staying in WCP phase
        """
        msg_type = message.get("type")

        if msg_type == "WCP1Hello":
            await self._handle_wcp1_hello(message, session_id, wcp_sessions, websocket)

        elif msg_type == "WCP4ValidateAppIdentity":
            transition = await self._handle_wcp4_validate_app_identity(
                message, session_id, wcp_sessions, websocket
            )
            if transition:
                return "dacp"

        elif msg_type == "WCP6Goodbye":
            await self._handle_wcp6_goodbye(session_id, wcp_sessions)
            return "disconnect"

        return None

    async def _handle_wcp1_hello(
        self,
        message: Dict[str, Any],
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ):
        """Handle WCP1Hello message"""
        try:
            wcp1 = WCP1Hello(**message)
        except ValidationError as exc:
            logger.warning("Invalid WCP1Hello received: %s", exc)
            return

        wcp_sessions[session_id] = {
            "wcp1_identity": {
                "identityUrl": wcp1.payload.identityUrl,
                "actualUrl": wcp1.payload.actualUrl,
                "fdc3Version": wcp1.payload.fdc3Version,
            },
            "identity": None,
            "state": "handshake",
        }

        # Send WCP3Handshake (skip WCP2 for now)
        wcp3 = WCP3Handshake(
            payload=WCP3HandshakePayload(
                fdc3Version="2.0", intentResolverUrl=None, channelSelectorUrl=None
            ),
            meta=wcp1.meta,
        )
        await self._send_model(websocket, wcp3)

    async def _handle_wcp4_validate_app_identity(
        self,
        message: Dict[str, Any],
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ) -> bool:
        """Handle WCP4ValidateAppIdentity message. Returns True if transitioning to DACP."""
        try:
            wcp4 = WCP4ValidateAppIdentity(**message)
        except ValidationError as exc:
            logger.warning("Invalid WCP4ValidateAppIdentity received: %s", exc)
            # Attempt to notify client with a failure response if possible
            conn_attempt = None
            try:
                conn_attempt = message.get("meta", {}).get("connectionAttemptUuid")
            except Exception:
                conn_attempt = None
            failed = WCP5ValidateAppIdentityFailedResponse(
                payload=WCP5ValidateAppIdentityFailedResponsePayload(
                    message="Invalid WCP4ValidateAppIdentity payload"
                ),
                meta={
                    "requestUuid": conn_attempt,
                    "timestamp": datetime.now().isoformat(),
                },
            )
            try:
                await self._send_model(websocket, failed)
            except Exception:
                logger.debug("Failed to send validation error response")
            return False

        validation_result = await self._validate_app_identity(
            wcp4, session_id, wcp_sessions
        )

        if validation_result["valid"]:
            identity = validation_result["identity"]
            wcp_sessions[session_id]["identity"] = identity

            # Send success response
            # Populate implementationMetadata from storage if available (best-effort)
            impl_meta = {}
            try:
                app_id = identity.get("appId")
                if app_id and hasattr(self.storage, "apps"):
                    app_meta = await self.storage.apps.get_app_metadata(app_id)
                    if app_meta:
                        impl_meta = {
                            "appId": getattr(app_meta, "app_id", None),
                            "name": getattr(app_meta, "name", None),
                            "version": getattr(app_meta, "version", None),
                            "description": getattr(app_meta, "description", None),
                            "icons": getattr(app_meta, "icons", []),
                            "intents": getattr(app_meta, "intents", []),
                        }
            except Exception:
                impl_meta = {}

            # Add runtime launcher info (best-effort)
            try:
                agent_url = (
                    os.getenv("FDC3_DESKTOP_AGENT_URL")
                    or f"ws://{os.getenv('FDC3_HOST','localhost')}:{os.getenv('FDC3_PORT','8000')}/ws"
                )
                runtime_info = {
                    "launcher": {
                        "type": "subprocess",
                        "python": sys.executable,
                        "platform": platform.platform(),
                        "agentUrl": agent_url,
                    }
                }
            except Exception:
                runtime_info = {}

            # Merge runtime info into implementation metadata
            try:
                if impl_meta and isinstance(impl_meta, dict):
                    impl_meta.update(runtime_info)
                else:
                    impl_meta = runtime_info
            except Exception:
                pass

            connection_attempt = getattr(getattr(wcp4, "meta", None), "connectionAttemptUuid", None)
            wcp5 = WCP5ValidateAppIdentityResponse(
                payload=WCP5ValidateAppIdentityResponsePayload(
                    appId=identity["appId"],
                    instanceId=identity["instanceId"],
                    instanceUuid=identity["instanceUuid"],
                    implementationMetadata=impl_meta,
                ),
                meta={
                    "requestUuid": connection_attempt,
                    "timestamp": datetime.now().isoformat(),
                },
            )
            await self._send_model(websocket, wcp5)

            # Register instance
            core_services.app_registry.register_instance(
                identity["appId"], identity["instanceId"], identity["instanceUuid"]
            )

            return True  # Transition to DACP
        else:
            # Send failure response
            connection_attempt = getattr(getattr(wcp4, "meta", None), "connectionAttemptUuid", None)
            wcp5_failed = WCP5ValidateAppIdentityFailedResponse(
                payload=WCP5ValidateAppIdentityFailedResponsePayload(
                    message=validation_result["error"]
                ),
                meta={
                    "requestUuid": connection_attempt,
                    "timestamp": datetime.now().isoformat(),
                },
            )
            await self._send_model(websocket, wcp5_failed)
            return False

    async def _handle_wcp6_goodbye(self, session_id: str, wcp_sessions: Dict[str, Any]):
        """Handle WCP6Goodbye message"""
        if session_id in wcp_sessions:
            del wcp_sessions[session_id]

    async def _validate_app_identity(
        self,
        wcp4: WCP4ValidateAppIdentity,
        session_id: str,
        wcp_sessions: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Validate WCP4 app identity request.

        Supports two flows:
        1. Agent-launched apps: Have a pre-registered pending instance UUID
        2. Self-registering external handlers: Use appId pattern 'external-handler:*'
        """
        from urllib.parse import urlparse
        import uuid as uuid_mod

        wcp1_identity = wcp_sessions[session_id].get("wcp1_identity")
        if not wcp1_identity:
            return {"valid": False, "error": "No WCP1 identity information found"}

        identity_url = wcp1_identity.get("identityUrl")
        actual_url = wcp1_identity.get("actualUrl")

        instance_uuid = wcp4.payload.instanceUuid

        # Check for self-registering external handler pattern
        # External handlers can provide their own appId like "external-handler:my-handler"
        app_id = wcp4.payload.appId
        if app_id and app_id.startswith("external-handler:"):
            # Self-registration flow for external handlers
            # Generate a new instance UUID if not provided
            if not instance_uuid:
                instance_uuid = str(uuid_mod.uuid4())

            instance_id = wcp4.payload.instanceId or str(uuid_mod.uuid4())

            logger.info(f"External handler self-registering: {app_id}")
            return {
                "valid": True,
                "identity": {
                    "appId": app_id,
                    "instanceId": instance_id,
                    "instanceUuid": instance_uuid,
                },
            }

        # Standard flow: require pre-registered pending instance
        if instance_uuid:
            pending_instance = core_services.app_registry.get_instance(instance_uuid)
            if pending_instance and not pending_instance.connected:
                app_id = pending_instance.app_id

                # Check allowed origins
                allowed_origins = await self.storage.origins.get_allowed_origins(app_id)
                if allowed_origins:
                    identity_origin = (
                        urlparse(identity_url).netloc if identity_url else None
                    )
                    actual_origin = urlparse(actual_url).netloc if actual_url else None

                    if identity_origin and actual_origin:
                        if (
                            identity_origin not in allowed_origins
                            or actual_origin not in allowed_origins
                        ):
                            return {
                                "valid": False,
                                "error": "Origin not allowed for this app",
                            }
                    else:
                        return {
                            "valid": False,
                            "error": "Invalid identity or actual URL",
                        }

                instance_id = wcp4.payload.instanceId or pending_instance.instance_id
                return {
                    "valid": True,
                    "identity": {
                        "appId": app_id,
                        "instanceId": instance_id,
                        "instanceUuid": instance_uuid,
                    },
                }
            else:
                return {
                    "valid": False,
                    "error": "Instance UUID not found or already connected",
                }
        else:
            return {"valid": False, "error": "No instance UUID provided"}
