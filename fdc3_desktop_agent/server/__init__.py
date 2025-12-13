# FastAPI app, websocket handlers, GraphQL endpoint

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from strawberry.fastapi import GraphQLRouter
import asyncio
import json
import logging
import os
from typing import Dict, Set, Optional
from contextlib import asynccontextmanager

from ..api.graphql import schema, set_graphql_storage
from ..protocol.dacp.dacp import AgentEventMeta, AgentEvent, AgentEventPayload
from ..transport.wcp.wcp import WCP4ValidateAppIdentity
from ..core import core_services
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

logger = logging.getLogger(__name__)


# Server configuration
def get_allowed_origins():
    """Get allowed origins with localhost default"""
    env_origins = os.getenv("FDC3_ALLOWED_ORIGINS")
    if env_origins:
        return env_origins.split(",")
    # Default to allowing localhost connections (common development setup)
    return ["localhost", "127.0.0.1", "localhost:*", "127.0.0.1:*"]


SERVER_CONFIG = {
    "host": os.getenv("FDC3_HOST", "localhost"),
    "port": int(os.getenv("FDC3_PORT", "8000")),
    "db_path": os.getenv("FDC3_DB_PATH", "fdc3_agent.db"),
    "log_level": os.getenv("FDC3_LOG_LEVEL", "INFO"),
    "allowed_origins": get_allowed_origins(),
}


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Lifespan handler to initialize and teardown resources."""
    # Startup
    # Configure logging
    logging.basicConfig(level=getattr(logging, SERVER_CONFIG["log_level"]))

    # Initialize storage before any use
    await storage.initialize()
    logger.info(f"FDC3 Desktop Agent storage initialized at {SERVER_CONFIG['db_path']}")

    # Register the system app (after storage is ready)
    await storage.apps.add_app(system_app_metadata)
    logger.info(
        f"Server configured for {SERVER_CONFIG['host']}:{SERVER_CONFIG['port']}"
    )
    logger.info(f"Allowed origins: {', '.join(SERVER_CONFIG['allowed_origins'])}")

    # Log connection URIs for convenience
    host = SERVER_CONFIG["host"]
    port = SERVER_CONFIG["port"]
    logger.info(f"HTTP API available at: http://{host}:{port}")
    logger.info(f"GraphQL endpoint at: http://{host}:{port}/graphql")
    logger.info(f"WebSocket endpoint at: ws://{host}:{port}/ws")
    logger.info(f"Admin interface at: http://{host}:{port}/admin")

    # Initialize optional distributed adapter (etcd/consul/noop)
    try:
        adapter = get_adapter()
        await adapter.start()
        app.state.distributed_adapter = adapter

        async def _distributed_event_handler(ev):
            try:
                # ev may be a dict or JSON string depending on adapter
                if isinstance(ev, str):
                    payload = json.loads(ev)
                else:
                    payload = ev

                # Forward into local ChannelManager without re-publishing
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
                return

        # Subscribe (best-effort). Adapter.subscribe is async and returns a subscription id.
        try:

            def _sub_cb(ev: dict):
                asyncio.create_task(_distributed_event_handler(ev))
                return None

            sub_id = await adapter.subscribe("channel_events", _sub_cb)
            app.state.distributed_subscription_id = sub_id
        except Exception:
            app.state.distributed_subscription_id = None
    except Exception:
        app.state.distributed_adapter = None
        app.state.distributed_subscription_id = None

    try:
        yield
    finally:
        # Shutdown
        try:
            adapter = getattr(app.state, "distributed_adapter", None)
            sub_id = getattr(app.state, "distributed_subscription_id", None)
            if adapter and sub_id:
                try:
                    await adapter.unsubscribe(sub_id)
                except Exception:
                    pass
            if adapter:
                try:
                    await adapter.stop()
                except Exception:
                    pass
        except Exception:
            pass

        # Stop any launched subprocesses and close connection managers to avoid
        # lingering proactor pipe transports during interpreter shutdown.
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


app = FastAPI(
    title="FDC3 Desktop Agent",
    version="0.9.0",
    description="FDC3 Desktop Agent with WebSocket and DACP support",
    lifespan=_lifespan,
)

# Configure templates
templates = Jinja2Templates(directory="fdc3_desktop_agent/templates")

# Initialize storage and launcher
storage = SqliteStorage(SERVER_CONFIG["db_path"])
launcher = SubprocessLauncher()

# Register the desktop agent itself as a system app
system_app_metadata = AppMetadata(
    app_id="fdc3-desktop-agent",
    name="FDC3 Desktop Agent",
    version="0.1.0",
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


# Initialize access control with default allowlist policy
access_control = AccessControlManager()
if SERVER_CONFIG["allowed_origins"]:
    allowlist_policy = AllowlistAccessPolicy(SERVER_CONFIG["allowed_origins"])
    access_control.set_policy(allowlist_policy)

# Initialize WebSocket connection managers and handlers
# `WebSocketConnectionManager` imported from handlers manages app instance connections.
instance_connection_manager = WebSocketConnectionManager()


# Agent-client manager handles UI/agent client side connections and broadcasts.
class AgentClientConnectionManager:
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


agent_client_manager = AgentClientConnectionManager()

access_control_handler = AccessControlHandler(
    access_control, SERVER_CONFIG["allowed_origins"]
)
wcp_handler = WCPHandler(storage)
dacp_handler = DACPHandler(storage, launcher, instance_connection_manager)

# Initialize GraphQL with storage
set_graphql_storage(storage)

# Add GraphQL router
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


# Placeholder for WCP session management
wcp_sessions = {}


async def _validate_app_identity(
    wcp4: WCP4ValidateAppIdentity, session_id: str
) -> dict:
    """Validate WCP4 app identity request"""
    from urllib.parse import urlparse

    # Get the WCP1 identity info from session
    wcp1_identity = wcp_sessions[session_id].get("wcp1_identity")
    if not wcp1_identity:
        return {"valid": False, "error": "No WCP1 identity information found"}

    identity_url = wcp1_identity.get("identityUrl")
    actual_url = wcp1_identity.get("actualUrl")

    # Check if there's a pending instance with the requested instanceUuid
    instance_uuid = wcp4.payload.instanceUuid
    if instance_uuid:
        pending_instance = core_services.app_registry.get_instance(instance_uuid)
        if pending_instance and not pending_instance.connected:
            # Found pending instance - validate origins
            app_id = pending_instance.app_id

            # Check if origins are allowed for this app
            allowed_origins = await storage.origins.get_allowed_origins(app_id)
            if allowed_origins:
                # Validate identityUrl and actualUrl origins
                identity_origin = (
                    urlparse(identity_url).netloc if identity_url else None
                )
                actual_origin = urlparse(actual_url).netloc if actual_url else None

                if identity_origin and actual_origin:
                    # Both origins must be in allowed list
                    if (
                        identity_origin not in allowed_origins
                        or actual_origin not in allowed_origins
                    ):
                        return {
                            "valid": False,
                            "error": "Origin not allowed for this app",
                        }
                else:
                    return {"valid": False, "error": "Invalid identity or actual URL"}

            instance_id = wcp4.payload.instanceId or pending_instance.instance_id
            return {
                "valid": True,
                "identity": {
                    "appId": app_id,
                    "instanceId": instance_id,
                    "instanceUuid": instance_uuid,
                },
            }
        else:
            return {
                "valid": False,
                "error": "Instance UUID not found or already connected",
            }
    else:
        # No instance UUID provided - this shouldn't happen in normal flow
        return {"valid": False, "error": "No instance UUID provided"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for FDC3 WCP and DACP communication"""

    # Validate access using the access control handler
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
            await asyncio.sleep(30)  # Send heartbeat every 30 seconds
            if session_id and dacp_active:
                from ..protocol.dacp.dacp import HeartbeatEvent, AgentEventMeta

                heartbeat_event = HeartbeatEvent(meta=AgentEventMeta())
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
                # WCP phase - use WCP handler
                transition = await wcp_handler.handle_message(
                    message, session_id or "", wcp_sessions, websocket
                )
                if transition == "dacp":
                    dacp_active = True
                    # Start heartbeat task when entering DACP phase
                    heartbeat_task = asyncio.create_task(send_heartbeat())
            else:
                # DACP phase - use DACP handler
                await dacp_handler.handle_message(
                    message, session_id or "", wcp_sessions, websocket
                )

    except WebSocketDisconnect:
        if heartbeat_task:
            heartbeat_task.cancel()
        if session_id in wcp_sessions:
            identity = wcp_sessions[session_id]["identity"]
            instance_uuid = identity["instanceUuid"]
            # Clean up
            core_services.app_registry.unregister_instance(instance_uuid)
            core_services.listener_store.remove_listeners_for_instance(instance_uuid)
            core_services.channel_manager.leave_current_channel(instance_uuid)
            # Unregister agent-client WebSocket connection
            await agent_client_manager.disconnect(websocket, instance_uuid)
            del wcp_sessions[session_id]
        logger.info("WebSocket disconnected")
