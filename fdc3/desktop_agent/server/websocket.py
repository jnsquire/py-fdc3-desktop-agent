"""WebSocket endpoint handler for the FDC3 Desktop Agent server.

This module implements the ASGI websocket loop used by the FastAPI app.

Incoming messages start as WCP during handshake. After the session is
validated, the connection transitions to DACP for the remainder of the
connection.

This is primarily an internal module; most embedding use-cases should
use :func:`fdc3.desktop_agent.server.create_app`.
"""

import asyncio
import json
import logging
from typing import Dict

from fastapi import WebSocket, WebSocketDisconnect

from ..core import core_services
from ..handlers import AccessControlHandler, WCPHandler, DACPHandler
from .connection_manager import AgentClientConnectionManager

logger = logging.getLogger(__name__)


async def websocket_endpoint(
    websocket: WebSocket,
    access_control_handler: AccessControlHandler,
    wcp_handler: WCPHandler,
    dacp_handler: DACPHandler,
    wcp_sessions: Dict[str, dict],
    agent_client_manager: AgentClientConnectionManager,
):
    """WebSocket endpoint for FDC3 WCP and DACP communication.

    The handler:

    - validates the websocket origin/headers via the access-control layer;
    - performs the WCP handshake;
    - transitions to DACP message handling;
    - performs best-effort cleanup on disconnect (registry/listeners/channel).

    Args:
        websocket: The WebSocket connection
        access_control_handler: Handler for access control validation
        wcp_handler: Handler for WCP messages
        dacp_handler: Handler for DACP messages
        wcp_sessions: Dictionary of WCP session state
        agent_client_manager: Manager for agent client connections
    """
    access_granted = await access_control_handler.validate_connection(
        websocket, websocket.headers
    )
    if not access_granted:
        return

    await websocket.accept()
    session_id = None
    dacp_active = False
    heartbeat_task = None

    async def send_heartbeat():
        """Send periodic heartbeat events"""
        while True:
            await asyncio.sleep(30)
            if session_id and dacp_active:
                from fdc3.models.dacp.dacp import (
                    HeartbeatEvent,
                    AgentEventMeta as HBMeta,
                )

                heartbeat_event = HeartbeatEvent(meta=HBMeta())
                try:
                    await websocket.send_text(heartbeat_event.model_dump_json())
                except Exception as e:
                    logger.error(f"Failed to send heartbeat: {e}")
                    break

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            # Extract session_id from WCP1Hello if not yet set
            if session_id is None and message.get("type") == "WCP1Hello":
                session_id = (message.get("meta") or {}).get("connectionAttemptUuid")

            if not dacp_active:
                transition = await wcp_handler.handle_message(
                    message, session_id or "", wcp_sessions, websocket
                )
                if transition == "dacp":
                    dacp_active = True
                    heartbeat_task = asyncio.create_task(send_heartbeat())
                    # Register the instance websocket in the DACP connection manager so
                    # the handler can deliver messages to this instance via
                    # `WebSocketConnectionManager.send_to_instance`.
                    try:
                        identity = wcp_sessions[session_id]["identity"]
                        instance_uuid = identity["instanceUuid"]
                        # Best-effort: not fatal if registration fails
                        dacp_handler.connection_manager.add_connection(
                            instance_uuid, websocket
                        )
                        logger.debug(
                            f"Registered instance connection for {instance_uuid}"
                        )
                    except Exception:
                        logger.exception("Failed to register instance connection")
            else:
                await dacp_handler.handle_message(
                    message, session_id or "", wcp_sessions, websocket
                )

    except WebSocketDisconnect:
        if heartbeat_task:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
        if session_id in wcp_sessions:
            identity = wcp_sessions[session_id]["identity"]
            instance_uuid = identity["instanceUuid"]
            core_services.app_registry.unregister_instance(instance_uuid)
            core_services.listener_store.remove_listeners_for_instance(instance_uuid)
            core_services.channel_manager.leave_current_channel(instance_uuid)

            # Remove registered instance connection so future sends don't attempt
            # to deliver to a stale websocket.
            try:
                dacp_handler.connection_manager.remove_connection(instance_uuid)
            except Exception:
                logger.exception("Failed to remove instance connection")

            await agent_client_manager.disconnect(websocket, instance_uuid)
            del wcp_sessions[session_id]
        logger.info("WebSocket disconnected")
