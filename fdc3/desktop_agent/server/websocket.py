"""WebSocket endpoint handler for the FDC3 Desktop Agent server.

This module implements the ASGI websocket loop used by the FastAPI app.

Incoming messages start as WCP during handshake. After the session is
validated, the connection transitions to DACP for the remainder of the
connection.

This is primarily an internal module; most embedding use-cases should
    use `create_app`.
"""

import asyncio
import json
import logging
from typing import Any, cast

from fastapi import WebSocket, WebSocketDisconnect

from fdc3.models.dacp.dacp import AgentEventMeta as HBMeta
from fdc3.models.dacp.dacp import HeartbeatEvent

from ..core import core_services
from ..handlers import AccessControlHandler, WCPHandler, DACPHandler
from ..handlers.protocols import MessageSender
from ..tools import cancel_task
from .connection_manager import AgentClientConnectionManager
from ..types import WcpSessions

logger = logging.getLogger(__name__)


async def _cleanup_instance(
    *,
    websocket: WebSocket,
    instance_uuid: str,
    dacp_handler: DACPHandler,
    agent_client_manager: AgentClientConnectionManager,
) -> None:
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


async def _register_instance_connection(
    *,
    session_id: str | None,
    wcp_sessions: WcpSessions,
    websocket: WebSocket,
    dacp_handler: DACPHandler,
) -> None:
    try:
        if session_id is None:
            logger.warning("DACP transition without session_id; skipping registration")
            return
        session = wcp_sessions.get(session_id)
        identity = session.identity if session else None
        instance_uuid = identity.instanceUuid if identity is not None else None
        if not instance_uuid:
            logger.warning(
                "DACP transition without instanceUuid; skipping registration"
            )
            return
        # Best-effort: not fatal if registration fails
        dacp_handler.connection_manager.add_connection(instance_uuid, websocket)
        logger.debug(f"Registered instance connection for {instance_uuid}")
    except Exception:
        logger.exception("Failed to register instance connection")


async def _receive_json_message(websocket: WebSocket) -> dict[str, Any] | None:
    data = await websocket.receive_text()
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        logger.warning("WebSocket received invalid JSON; closing connection")
        await websocket.close(code=1003)
        return None


def _maybe_set_session_id(
    session_id: str | None, message: dict[str, Any]
) -> str | None:
    if session_id is None and message.get("type") == "WCP1Hello":
        meta = message.get("meta")
        if isinstance(meta, dict):
            meta_dict = cast(dict[str, Any], meta)
            return meta_dict.get("connectionAttemptUuid")
    return session_id


class WebSocketSender(MessageSender):
    """Implementation of MessageSender for FastAPI's WebSocket."""

    def __init__(self, websocket: WebSocket):
        self._ws = websocket

    async def send_model(self, model) -> None:
        await self._ws.send_text(model.model_dump_json())


async def websocket_endpoint(
    websocket: WebSocket,
    access_control_handler: AccessControlHandler,
    wcp_handler: WCPHandler,
    dacp_handler: DACPHandler,
    wcp_sessions: WcpSessions,
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
    sender = WebSocketSender(websocket)
    session_id = None
    dacp_active = False
    heartbeat_task = None

    async def send_heartbeat() -> None:
        """Send periodic heartbeat events."""
        while True:
            await asyncio.sleep(30)
            if session_id and dacp_active:
                heartbeat_event = HeartbeatEvent(meta=HBMeta())
                try:
                    await sender.send_model(heartbeat_event)
                except Exception:
                    logger.exception("Failed to send heartbeat")
                    break

    async def _cleanup(reason: str) -> None:
        await cancel_task(heartbeat_task, label="heartbeat", logger_override=logger)
        if session_id is not None and session_id in wcp_sessions:
            session = wcp_sessions[session_id]
            identity = session.identity if session else None
            instance_uuid = identity.instanceUuid if identity is not None else None
            if instance_uuid:
                await _cleanup_instance(
                    websocket=websocket,
                    instance_uuid=instance_uuid,
                    dacp_handler=dacp_handler,
                    agent_client_manager=agent_client_manager,
                )

            del wcp_sessions[session_id]

        if reason == "invalid_json":
            logger.info("WebSocket closed due to invalid JSON payload")
        elif reason == "error":
            logger.info("WebSocket closed due to handler error")
        else:
            logger.info("WebSocket disconnected")

    disconnect_reason = "disconnect"

    try:
        while True:
            message = await _receive_json_message(websocket)
            if message is None:
                disconnect_reason = "invalid_json"
                break

            # Extract session_id from WCP1Hello if not yet set
            session_id = _maybe_set_session_id(session_id, message)

            if not dacp_active:
                transition = await wcp_handler.handle_message(
                    message, session_id or "", wcp_sessions, sender
                )
                if transition == "dacp":
                    dacp_active = True
                    heartbeat_task = asyncio.create_task(send_heartbeat())
                    # Register the instance websocket in the DACP connection manager so
                    # the handler can deliver messages to this instance via
                    # `WebSocketConnectionManager.send_to_instance`.
                    await _register_instance_connection(
                        session_id=session_id,
                        wcp_sessions=wcp_sessions,
                        websocket=websocket,
                        dacp_handler=dacp_handler,
                    )
            else:
                await dacp_handler.handle_message(
                    message, session_id or "", wcp_sessions, sender
                )

    except WebSocketDisconnect:
        disconnect_reason = "disconnect"
    except Exception:
        disconnect_reason = "error"
        logger.exception("WebSocket handler failed")
    finally:
        await _cleanup(disconnect_reason)
