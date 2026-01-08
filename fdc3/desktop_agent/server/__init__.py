"""FDC3 Desktop Agent server package.

This package provides the FastAPI application plus the WebSocket entrypoint
that implements WCP/DACP messaging.

Most users will interact with:

- :func:`create_app` to embed the agent in another Python process.
- :data:`app` for the default application instance.

Submodules:
    - ``app_factory``: FastAPI application factory.
    - ``websocket``: WebSocket endpoint handler.
    - ``routes``: HTTP route handlers.
    - ``lifespan``: Application lifecycle management (startup/shutdown).
"""

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
