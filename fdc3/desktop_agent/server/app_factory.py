# FastAPI application factory for the FDC3 Desktop Agent server

import logging
from contextlib import asynccontextmanager
from typing import Dict, Optional

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from strawberry.fastapi import GraphQLRouter

from ..api.graphql import schema, set_graphql_storage
from ..config import DesktopAgentConfig
from ..storage import SqliteStorage
from ..launcher import SubprocessLauncher
from ..access_control import AccessControlManager, AllowlistAccessPolicy
from ..handlers import (
    AccessControlHandler,
    WCPHandler,
    DACPHandler,
    WebSocketConnectionManager,
)
from ..version import __version__
from .connection_manager import AgentClientConnectionManager
from .lifespan import create_lifespan
from .routes import router as routes_router
from .websocket import websocket_endpoint

logger = logging.getLogger(__name__)


def create_app(config: Optional[DesktopAgentConfig] = None) -> FastAPI:
    """Create and configure the FDC3 Desktop Agent FastAPI application.

    This factory function allows embedding the agent in another Python project
    with full control over configuration.

    Args:
        config: Optional configuration. If None, uses environment variables
                and defaults.

    Returns:
        A configured FastAPI application ready to be run with uvicorn or
        mounted into a larger ASGI application.

    Example:
        # Standalone usage
        app = create_app()

        # With custom config
        config = DesktopAgentConfig(host="0.0.0.0", port=9000, db_path=":memory:")
        app = create_app(config)

        # Mount in larger app
        main_app = FastAPI()
        main_app.mount("/fdc3", create_app())
    """
    if config is None:
        config = DesktopAgentConfig()

    # Create or use provided components
    storage = config.storage or SqliteStorage(config.db_path)
    launcher = config.launcher or SubprocessLauncher(
        agent_url=config.computed_agent_url
    )
    # Use the global singleton core_services so handlers, GraphQL, plugins,
    # and any background components (e.g. bridging) share the same state.

    # Access control
    access_control = AccessControlManager()
    if config.allowed_origins:
        allowlist_policy = AllowlistAccessPolicy(config.allowed_origins)
        access_control.set_policy(allowlist_policy)

    # Connection managers
    instance_connection_manager = WebSocketConnectionManager()
    agent_client_manager = AgentClientConnectionManager()

    # Handlers
    access_control_handler = AccessControlHandler(
        access_control, config.allowed_origins
    )
    wcp_handler = WCPHandler(storage)
    # bridge client is created in lifespan (needs event loop); injected into handler.
    dacp_handler = DACPHandler(storage, launcher, instance_connection_manager)

    # WCP session state
    wcp_sessions: Dict[str, dict] = {}

    # Create the base lifespan from the lifespan module
    base_lifespan = create_lifespan(
        config=config,
        storage=storage,
        launcher=launcher,
        agent_client_manager=agent_client_manager,
        instance_connection_manager=instance_connection_manager,
        dacp_handler=dacp_handler,
    )

    # Wrap to also store wcp_sessions in app state
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with base_lifespan(app):
            # Store wcp_sessions in app state for websocket handler
            app.state.wcp_sessions = wcp_sessions
            yield

    # Create FastAPI app
    app = FastAPI(
        title="FDC3 Desktop Agent",
        version=__version__,
        description="FDC3 Desktop Agent with WebSocket and DACP support",
        lifespan=lifespan,
    )

    # UI pages (static HTML)
    # Mount the templates directory as static files and keep the historical
    # friendly URLs (/admin, /diagnostics, etc.) as redirects.
    app.mount(
        "/ui",
        StaticFiles(directory=str(config.templates_dir), html=False),
        name="ui",
    )

    # Initialize GraphQL with storage
    set_graphql_storage(storage)
    graphql_app = GraphQLRouter(schema)
    app.include_router(graphql_app, prefix="/graphql")

    # Include HTTP routes
    app.include_router(routes_router)

    # WebSocket endpoint
    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        await websocket_endpoint(
            websocket=websocket,
            access_control_handler=access_control_handler,
            wcp_handler=wcp_handler,
            dacp_handler=dacp_handler,
            wcp_sessions=wcp_sessions,
            agent_client_manager=agent_client_manager,
        )

    return app
