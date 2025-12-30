# FDC3 Desktop Agent Server
#
# This package provides the FastAPI application, WebSocket handlers, and
# GraphQL endpoint for the FDC3 Desktop Agent.
#
# The server is organized into the following submodules:
# - app_factory: FastAPI application factory (create_app)
# - connection_manager: Agent client WebSocket connection management
# - constants: System app metadata and other constants
# - lifespan: Application lifespan management
# - routes: HTTP route handlers
# - websocket: WebSocket endpoint handler

import asyncio  # Re-exported for test monkeypatching

from .app_factory import create_app
from .connection_manager import AgentClientConnectionManager
from .constants import SYSTEM_APP_METADATA

# Re-export items that tests may need to monkeypatch
from ..core import core_services
from ..distributed.factory import get_adapter
from ..bridging import BridgeClient
from ..handlers import (
    AccessControlHandler,
    WCPHandler,
    DACPHandler,
    WebSocketConnectionManager,
)

# Default app instance for backwards compatibility and standalone usage
app = create_app()

__all__ = [
    "create_app",
    "app",
    "AgentClientConnectionManager",
    "SYSTEM_APP_METADATA",
    # Re-exported for backwards compatibility
    "asyncio",
    "core_services",
    "get_adapter",
    "BridgeClient",
    "AccessControlHandler",
    "WCPHandler",
    "DACPHandler",
    "WebSocketConnectionManager",
]
