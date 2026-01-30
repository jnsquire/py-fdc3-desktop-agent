# Agent client WebSocket connection manager

from fastapi import WebSocket
import logging
from typing import Dict, Set, Optional

from fdc3.models.dacp.dacp import AgentEventMeta, AgentEvent, AgentEventPayload

logger = logging.getLogger(__name__)


class AgentClientConnectionManager:
    """Manages WebSocket connections for agent UI clients."""

    def __init__(self):
        self._connections: Dict[str, WebSocket] = {}
        self._active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket, instance_uuid: str):
        await websocket.accept()
        self._connections[instance_uuid] = websocket
        self._active_connections.add(websocket)
        logger.info(f"WebSocket connected for instance {instance_uuid}")
        await self.broadcast_agent_event("connected", instance_uuid)

    async def disconnect(
        self, websocket: WebSocket, instance_uuid: Optional[str] = None
    ):
        if instance_uuid and instance_uuid in self._connections:
            del self._connections[instance_uuid]
        self._active_connections.discard(websocket)
        logger.info(f"WebSocket disconnected for instance {instance_uuid}")
        if instance_uuid:
            await self.broadcast_agent_event("disconnected", instance_uuid)

    async def send_to_instance(self, instance_uuid: str, message: str):
        if instance_uuid in self._connections:
            try:
                await self._connections[instance_uuid].send_text(message)
                return True
            except Exception as e:
                logger.error(f"Failed to send message to instance {instance_uuid}: {e}")
                await self.disconnect(self._connections[instance_uuid], instance_uuid)
                return False
        return False

    async def broadcast_agent_event(self, event_type: str, instance_uuid: str):
        event = AgentEvent(
            type="agentEvent",
            payload=AgentEventPayload(eventType=event_type, instanceUuid=instance_uuid),
            meta=AgentEventMeta(),
        )
        event_json = event.model_dump_json()
        disconnected = []
        for ws in self._active_connections:
            try:
                await ws.send_text(event_json)
            except Exception as e:
                logger.error(f"Failed to send agent event to WebSocket: {e}")
                disconnected.append(ws)
        for ws in disconnected:
            self._active_connections.discard(ws)

    async def close_all(self):
        """Close all active agent-client WebSocket connections."""
        conns = list(self._active_connections)
        for ws in conns:
            try:
                await ws.close()
            except Exception:
                pass
        self._active_connections.clear()
        self._connections.clear()

    def get_active_connection_count(self) -> int:
        """Get count of active agent-client WebSocket connections."""
        return len(self._active_connections)
