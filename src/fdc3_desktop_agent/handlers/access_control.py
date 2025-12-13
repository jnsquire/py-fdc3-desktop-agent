"""
Access control handler for WebSocket connections.
Handles origin validation and access control policy enforcement.
"""

import logging
from typing import List

from fastapi import WebSocket

from ..access_control import AccessControlManager, AccessRequest

logger = logging.getLogger(__name__)


class AccessControlHandler:
    """Handles WebSocket access control validation"""

    def __init__(
        self, access_control_manager: AccessControlManager, allowed_origins: List[str]
    ):
        self.access_control = access_control_manager
        self.allowed_origins = allowed_origins

    async def validate_connection(self, websocket: WebSocket) -> bool:
        """
        Validate WebSocket connection based on access control policy.

        Returns True if connection is allowed, False otherwise.
        Closes the WebSocket connection if access is denied.
        """
        origin = websocket.headers.get("origin")

        access_request = AccessRequest(
            origin=origin, user_agent=websocket.headers.get("user-agent")
        )

        access_decision = await self.access_control.check_access(access_request)

        if not access_decision.allowed:
            logger.warning(f"Rejected WebSocket connection: {access_decision.reason}")
            await websocket.close(code=1008)  # Policy violation
            return False

        return True
