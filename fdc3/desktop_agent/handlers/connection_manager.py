"""
WebSocket connection manager for handling instance connections.
"""

import logging
from typing import Dict
from fastapi import WebSocket
from ..core import core_services

logger = logging.getLogger(__name__)


class WebSocketConnectionManager:
    """Manages WebSocket connections for app instances"""

    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}  # instance_uuid -> websocket

    def add_connection(self, instance_uuid: str, websocket: WebSocket):
        """Add a WebSocket connection for an instance"""
        self.connections[instance_uuid] = websocket
        logger.info(f"Added connection for instance {instance_uuid}")

    def remove_connection(self, instance_uuid: str):
        """Remove a WebSocket connection for an instance"""
        if instance_uuid in self.connections:
            del self.connections[instance_uuid]
            logger.info(f"Removed connection for instance {instance_uuid}")
            try:
                # Unregister any external handlers registered by this instance
                core_services.external_registry.unregister_by_instance(instance_uuid)
            except Exception:
                logger.exception(
                    f"Failed to unregister handlers for instance {instance_uuid}"
                )

    async def send_to_instance(self, instance_uuid: str, message: str):
        """Send a message to a specific instance"""
        if instance_uuid in self.connections:
            try:
                await self.connections[instance_uuid].send_text(message)
            except Exception as e:
                logger.error(f"Failed to send message to instance {instance_uuid}: {e}")
                # Remove broken connection
                self.remove_connection(instance_uuid)
        else:
            logger.warning(
                f"No connection found for instance {instance_uuid}; current connections={list(self.connections.keys())}"
            )

    def get_connected_instances(self):
        """Get list of connected instance UUIDs"""
        return list(self.connections.keys())

    def get_connection_count(self) -> int:
        """Get count of connected instances."""
        return len(self.connections)

    async def close_all(self):
        """Close all active WebSocket connections."""
        conns = list(self.connections.items())
        for instance_uuid, ws in conns:
            try:
                await ws.close()
            except Exception:
                pass
        # Unregister handlers for all instances
        try:
            for instance_uuid, _ in conns:
                core_services.external_registry.unregister_by_instance(instance_uuid)
        except Exception:
            logger.exception("Failed to unregister handlers during close_all")

        self.connections.clear()
