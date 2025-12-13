# FastAPI app, websocket handlers, GraphQL endpoint

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from strawberry.fastapi import GraphQLRouter
import asyncio
import json
import logging
from typing import Dict, Set, Optional
from contextlib import asynccontextmanager

from ..api.graphql import schema, set_graphql_storage
from ..protocol.dacp.dacp import AgentEventMeta, AgentEvent, AgentEventPayload
from ..core import CoreServices
from ..distributed.factory import get_adapter
from ..storage import SqliteStorage
from ..storage.interfaces import AppMetadata
from ..launcher import SubprocessLauncher
from ..access_control import AccessControlManager, AllowlistAccessPolicy
from ..handlers import (
    AccessControlHandler,
    WCPHandler,
    DACPHandler,
    WebSocketConnectionManager,
)
from ..config import DesktopAgentConfig
from ..version import __version__

logger = logging.getLogger(__name__)


# System app metadata (constant)
_SYSTEM_APP_METADATA = AppMetadata(
    app_id="fdc3-desktop-agent",
    name="FDC3 Desktop Agent",
    version=__version__,
    description="Built-in system app for FDC3 Desktop Agent functionality",
    intents=[
        # App Directory Management
        "fdc3.openAppDirectory",
        "fdc3.manageApps",
        "fdc3.installApp",
        "fdc3.uninstallApp",
        # System Configuration
        "fdc3.systemSettings",
        "fdc3.configureChannels",
        "fdc3.systemDiagnostics",
        # Channel Management
        "fdc3.createChannel",
        "fdc3.deleteChannel",
        "fdc3.manageChannel",
        # Built-in System Apps
        "fdc3.resolveIntent",
        # System Browser/File Manager
        "fdc3.openUrl",
        "fdc3.openFile",
        "fdc3.systemSearch",
        # System Notifications
        "fdc3.showNotification",
        "fdc3.systemAlert",
    ],
)


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
    core_services = CoreServices()

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
    dacp_handler = DACPHandler(storage, launcher, instance_connection_manager)

    # WCP session state
    wcp_sessions: Dict[str, dict] = {}

    # Templates (use absolute path for ASGI mounting compatibility)
    templates = Jinja2Templates(directory=str(config.templates_dir))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Lifespan handler to initialize and teardown resources."""
        # Startup
        logging.basicConfig(level=getattr(logging, config.log_level))

        await storage.initialize()
        logger.info(f"FDC3 Desktop Agent storage initialized at {config.db_path}")

        await storage.apps.add_app(_SYSTEM_APP_METADATA)
        logger.info(f"Server configured for {config.host}:{config.port}")
        logger.info(f"Allowed origins: {', '.join(config.allowed_origins)}")

        logger.info(f"HTTP API available at: http://{config.host}:{config.port}")
        logger.info(f"GraphQL endpoint at: http://{config.host}:{config.port}/graphql")
        logger.info(f"WebSocket endpoint at: {config.computed_agent_url}")
        logger.info(f"Admin interface at: http://{config.host}:{config.port}/admin")

        # Initialize distributed adapter
        adapter = config.distributed_adapter
        sub_id = None
        if adapter is None:
            try:
                adapter = get_adapter()
            except Exception:
                adapter = None

        if adapter:
            try:
                await adapter.start()
                app.state.distributed_adapter = adapter

                async def _distributed_event_handler(ev):
                    try:
                        if isinstance(ev, str):
                            payload = json.loads(ev)
                        else:
                            payload = ev
                        core_services.channel_manager._emit_event(
                            payload.get("event_type"),
                            payload.get("channel_id"),
                            payload.get("instance_uuid"),
                            (
                                json.loads(payload.get("context"))
                                if payload.get("context")
                                else None
                            ),
                            remote=True,
                        )
                    except Exception:
                        pass

                def _sub_cb(ev: dict):
                    asyncio.create_task(_distributed_event_handler(ev))

                sub_id = await adapter.subscribe("channel_events", _sub_cb)
                app.state.distributed_subscription_id = sub_id
            except Exception:
                app.state.distributed_adapter = None
                app.state.distributed_subscription_id = None
        else:
            app.state.distributed_adapter = None
            app.state.distributed_subscription_id = None

        # Store references for route handlers
        app.state.storage = storage
        app.state.launcher = launcher
        app.state.core_services = core_services
        app.state.wcp_sessions = wcp_sessions

        try:
            yield
        finally:
            # Shutdown
            adapter = getattr(app.state, "distributed_adapter", None)
            sub_id = getattr(app.state, "distributed_subscription_id", None)
            if adapter:
                if sub_id:
                    try:
                        await adapter.unsubscribe(sub_id)
                    except Exception:
                        pass
                try:
                    await adapter.stop()
                except Exception:
                    pass

            try:
                await launcher.stop()
            except Exception:
                pass

            try:
                await agent_client_manager.close_all()
            except Exception:
                pass

            try:
                await instance_connection_manager.close_all()
            except Exception:
                pass

            await storage.close()
            logger.info("FDC3 Desktop Agent storage closed")

    # Create FastAPI app
    app = FastAPI(
        title="FDC3 Desktop Agent",
        version=__version__,
        description="FDC3 Desktop Agent with WebSocket and DACP support",
        lifespan=lifespan,
    )

    # Initialize GraphQL with storage
    set_graphql_storage(storage)
    graphql_app = GraphQLRouter(schema)
    app.include_router(graphql_app, prefix="/graphql")

    # Admin routes
    @app.get("/admin", response_class=HTMLResponse)
    async def admin_page(request: Request):
        """Admin page for managing launch configurations"""
        return templates.TemplateResponse("admin.html", {"request": request})

    @app.get("/app-directory", response_class=HTMLResponse)
    async def app_directory_page(request: Request):
        """App directory management interface"""
        return templates.TemplateResponse("app_directory.html", {"request": request})

    @app.get("/system-settings", response_class=HTMLResponse)
    async def system_settings_page(request: Request):
        """System configuration panel"""
        return templates.TemplateResponse("system_settings.html", {"request": request})

    @app.get("/diagnostics", response_class=HTMLResponse)
    async def diagnostics_page(request: Request):
        """System diagnostics and health checks"""
        return templates.TemplateResponse("diagnostics.html", {"request": request})

    @app.get("/channel-monitor", response_class=HTMLResponse)
    async def channel_monitor_page(request: Request):
        """Channel monitor UI for subscribing to channel events"""
        return templates.TemplateResponse("channel_monitor.html", {"request": request})

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for FDC3 WCP and DACP communication"""
        access_granted = await access_control_handler.validate_connection(websocket)
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
                    from ..protocol.dacp.dacp import (
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

                if not dacp_active:
                    transition = await wcp_handler.handle_message(
                        message, session_id or "", wcp_sessions, websocket
                    )
                    if transition == "dacp":
                        dacp_active = True
                        heartbeat_task = asyncio.create_task(send_heartbeat())
                else:
                    await dacp_handler.handle_message(
                        message, session_id or "", wcp_sessions, websocket
                    )

        except WebSocketDisconnect:
            if heartbeat_task:
                heartbeat_task.cancel()
            if session_id in wcp_sessions:
                identity = wcp_sessions[session_id]["identity"]
                instance_uuid = identity["instanceUuid"]
                core_services.app_registry.unregister_instance(instance_uuid)
                core_services.listener_store.remove_listeners_for_instance(
                    instance_uuid
                )
                core_services.channel_manager.leave_current_channel(instance_uuid)
                await agent_client_manager.disconnect(websocket, instance_uuid)
                del wcp_sessions[session_id]
            logger.info("WebSocket disconnected")

    return app


# Default app instance for backwards compatibility and standalone usage
app = create_app()
