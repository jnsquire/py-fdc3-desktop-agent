"""
WCP (Web Connection Protocol) message handler.
Handles the initial handshake and app identity validation phase.
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional

from fastapi import WebSocket

from ..transport.wcp.wcp import (
    WCP1Hello, WCP3Handshake, WCP3HandshakePayload,
    WCP4ValidateAppIdentity, WCP5ValidateAppIdentityResponse, WCP5ValidateAppIdentityResponsePayload,
    WCP5ValidateAppIdentityFailedResponse, WCP5ValidateAppIdentityFailedResponsePayload
)
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

    async def handle_message(self, message: Dict[str, Any], session_id: str,
                           wcp_sessions: Dict[str, Any], websocket: WebSocket) -> Optional[str]:
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

    async def _handle_wcp1_hello(self, message: Dict[str, Any], session_id: str,
                                wcp_sessions: Dict[str, Any], websocket: WebSocket):
        """Handle WCP1Hello message"""
        wcp1 = WCP1Hello(**message)

        wcp_sessions[session_id] = {
            "wcp1_identity": {
                "identityUrl": wcp1.payload.identityUrl,
                "actualUrl": wcp1.payload.actualUrl,
                "fdc3Version": wcp1.payload.fdc3Version
            },
            "identity": None,
            "state": "handshake"
        }

        # Send WCP3Handshake (skip WCP2 for now)
        wcp3 = WCP3Handshake(
            payload=WCP3HandshakePayload(
                fdc3Version="2.0",
                intentResolverUrl=None,
                channelSelectorUrl=None
            ),
            meta=wcp1.meta
        )
        await self._send_model(websocket, wcp3)

    async def _handle_wcp4_validate_app_identity(self, message: Dict[str, Any], session_id: str,
                                                wcp_sessions: Dict[str, Any], websocket: WebSocket) -> bool:
        """Handle WCP4ValidateAppIdentity message. Returns True if transitioning to DACP."""
        wcp4 = WCP4ValidateAppIdentity(**message)

        validation_result = await self._validate_app_identity(wcp4, session_id, wcp_sessions)

        if validation_result["valid"]:
            identity = validation_result["identity"]
            wcp_sessions[session_id]["identity"] = identity

            # Send success response
            wcp5 = WCP5ValidateAppIdentityResponse(
                payload=WCP5ValidateAppIdentityResponsePayload(
                    appId=identity["appId"],
                    instanceId=identity["instanceId"],
                    instanceUuid=identity["instanceUuid"],
                    implementationMetadata={}
                ),
                meta={"requestUuid": message["meta"]["connectionAttemptUuid"],
                      "timestamp": datetime.now().isoformat()}
            )
            await self._send_model(websocket, wcp5)

            # Register instance
            core_services.app_registry.register_instance(
                identity["appId"], identity["instanceId"], identity["instanceUuid"]
            )

            return True  # Transition to DACP
        else:
            # Send failure response
            wcp5_failed = WCP5ValidateAppIdentityFailedResponse(
                payload=WCP5ValidateAppIdentityFailedResponsePayload(
                    message=validation_result["error"]
                ),
                meta={"requestUuid": message["meta"]["connectionAttemptUuid"],
                      "timestamp": datetime.now().isoformat()}
            )
            await self._send_model(websocket, wcp5_failed)
            return False

    async def _handle_wcp6_goodbye(self, session_id: str, wcp_sessions: Dict[str, Any]):
        """Handle WCP6Goodbye message"""
        if session_id in wcp_sessions:
            del wcp_sessions[session_id]

    async def _validate_app_identity(self, wcp4: WCP4ValidateAppIdentity, session_id: str, wcp_sessions: Dict[str, Any]) -> Dict[str, Any]:
        """Validate WCP4 app identity request"""
        from urllib.parse import urlparse

        wcp1_identity = wcp_sessions[session_id].get("wcp1_identity")
        if not wcp1_identity:
            return {"valid": False, "error": "No WCP1 identity information found"}

        identity_url = wcp1_identity.get("identityUrl")
        actual_url = wcp1_identity.get("actualUrl")

        instance_uuid = wcp4.payload.instanceUuid
        if instance_uuid:
            pending_instance = core_services.app_registry.get_instance(instance_uuid)
            if pending_instance and not pending_instance.connected:
                app_id = pending_instance.app_id

                # Check allowed origins
                allowed_origins = await self.storage.origins.get_allowed_origins(app_id)
                if allowed_origins:
                    identity_origin = urlparse(identity_url).netloc if identity_url else None
                    actual_origin = urlparse(actual_url).netloc if actual_url else None

                    if identity_origin and actual_origin:
                        if identity_origin not in allowed_origins or actual_origin not in allowed_origins:
                            return {"valid": False, "error": "Origin not allowed for this app"}
                    else:
                        return {"valid": False, "error": "Invalid identity or actual URL"}

                instance_id = wcp4.payload.instanceId or pending_instance.instance_id
                return {
                    "valid": True,
                    "identity": {
                        "appId": app_id,
                        "instanceId": instance_id,
                        "instanceUuid": instance_uuid
                    }
                }
            else:
                return {"valid": False, "error": "Instance UUID not found or already connected"}
        else:
            return {"valid": False, "error": "No instance UUID provided"}