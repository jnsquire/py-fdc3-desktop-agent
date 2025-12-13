from fastapi import WebSocket, WebSocketDisconnect
from ..transport.wcp.wcp import (
    WCP1Hello,
    WCP3Handshake,
    WCP3HandshakePayload,
    WCP4ValidateAppIdentity,
    WCP5ValidateAppIdentityResponse,
    WCP5ValidateAppIdentityResponsePayload,
)
from . import app
import json
import logging

logger = logging.getLogger(__name__)

# Placeholder for WCP session management
wcp_sessions = {}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = None
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            msg_type = message.get("type")

            if msg_type == "WCP1Hello":
                # Handle WCP1Hello
                wcp1 = WCP1Hello(**message)
                session_id = wcp1.meta.connectionAttemptUuid
                wcp_sessions[session_id] = {"identity": None, "state": "handshake"}

                # Optionally send WCP2LoadUrl if needed
                # For now, assume no load url

                # Send WCP3Handshake
                wcp3 = WCP3Handshake(
                    payload=WCP3HandshakePayload(
                        fdc3Version="2.0",  # placeholder
                        intentResolverUrl=None,
                        channelSelectorUrl=None,
                    ),
                    meta=wcp1.meta,
                )
                await websocket.send_text(wcp3.json())

            elif msg_type == "WCP4ValidateAppIdentity":
                # Handle WCP4
                wcp4 = WCP4ValidateAppIdentity(**message)
                # Validate and assign identity
                # Placeholder: assume valid
                app_id = "test_app"
                instance_id = wcp4.payload.instanceId or "instance1"
                instance_uuid = wcp4.payload.instanceUuid or "uuid1"

                wcp_sessions[session_id]["identity"] = {
                    "appId": app_id,
                    "instanceId": instance_id,
                    "instanceUuid": instance_uuid,
                }

                # Send WCP5Response
                wcp5 = WCP5ValidateAppIdentityResponse(
                    payload=WCP5ValidateAppIdentityResponsePayload(
                        appId=app_id,
                        instanceId=instance_id,
                        instanceUuid=instance_uuid,
                        implementationMetadata={},
                    ),
                    meta={
                        "requestUuid": message["meta"]["connectionAttemptUuid"],
                        "timestamp": "now",
                    },
                )
                await websocket.send_text(wcp5.json())

            elif msg_type == "WCP6Goodbye":
                # Handle disconnect
                if session_id in wcp_sessions:
                    del wcp_sessions[session_id]
                break

            else:
                # Handle DACP messages later
                pass

    except WebSocketDisconnect:
        if session_id in wcp_sessions:
            del wcp_sessions[session_id]
        logger.info("WebSocket disconnected")
