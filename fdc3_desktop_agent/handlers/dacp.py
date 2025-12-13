"""
DACP (Desktop Agent Communication Protocol) message handler.
Handles FDC3 operations like app launching, context broadcasting, and listener management.
"""

import logging
from typing import Dict, Any

from fastapi import WebSocket

from ..protocol.dacp.dacp import (
    AgentEventMeta,
    OpenRequest,
    AgentResponse,
    ErrorResponsePayload,
    AgentResponseMeta,
    OpenResponse,
    OpenResponsePayload,
    BroadcastRequest,
    BroadcastEvent,
    BroadcastEventPayload,
    AddContextListenerRequest,
    AddContextListenerResponse,
    AddContextListenerResponsePayload,
    AddIntentListenerRequest,
    AddIntentListenerResponse,
    AddIntentListenerResponsePayload,
    RaiseIntentRequest,
    RaiseIntentResponse,
    RaiseIntentResponsePayload,
    RaiseIntentForContextRequest,
    IntentEvent,
    IntentEventPayload,
    ContextListenerUnsubscribeRequest,
    ContextListenerUnsubscribeResponse,
    ContextListenerUnsubscribeResponsePayload,
    IntentListenerUnsubscribeRequest,
    IntentListenerUnsubscribeResponse,
    IntentListenerUnsubscribeResponsePayload,
    HeartbeatAcknowledgmentRequest,
    IntentResultRequest,
    IntentResultResponse,
    IntentResultResponsePayload,
    RaiseIntentResultResponse,
)
from ..core import core_services
from ..storage import Storage
from ..launcher.interfaces import ProcessLauncher
from .connection_manager import WebSocketConnectionManager
from .system_intent import SystemIntentHandler

logger = logging.getLogger(__name__)


class DACPHandler:
    """Handles DACP (Desktop Agent Communication Protocol) messages"""

    def __init__(
        self,
        storage: Storage,
        launcher: ProcessLauncher,
        connection_manager: WebSocketConnectionManager,
    ):
        self.storage = storage
        self.launcher = launcher
        self.connection_manager = connection_manager
        self.system_intent_handler = SystemIntentHandler()

    async def _send_model(self, websocket: WebSocket, model) -> None:
        """Helper method to send a Pydantic model as JSON over WebSocket"""
        try:
            await websocket.send_text(model.model_dump_json())
        except Exception as e:
            logger.error(f"Failed to send model {model.__class__.__name__}: {e}")

    async def handle_message(
        self,
        message: Dict[str, Any],
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ):
        """Handle DACP message"""
        msg_type = message.get("type")

        if msg_type == "open":
            await self._handle_open(message, websocket)
        elif msg_type == "broadcast":
            await self._handle_broadcast(message, session_id, wcp_sessions)
        elif msg_type == "addContextListener":
            await self._handle_add_context_listener(
                message, session_id, wcp_sessions, websocket
            )
        elif msg_type == "addIntentListener":
            await self._handle_add_intent_listener(
                message, session_id, wcp_sessions, websocket
            )
        elif msg_type == "intentListenerUnsubscribe":
            await self._handle_intent_listener_unsubscribe(message, websocket)
        elif msg_type == "raiseIntent":
            await self._handle_raise_intent(message, websocket)
        elif msg_type == "raiseIntentForContext":
            await self._handle_raise_intent_for_context(message, websocket)
        elif msg_type == "intentResultRequest":
            await self._handle_intent_result_request(message, websocket)
        elif msg_type == "raiseIntentResultResponse":
            await self._handle_raise_intent_result_response(message)
        elif msg_type == "contextListenerUnsubscribe":
            await self._handle_context_listener_unsubscribe(message, websocket)
        elif msg_type == "heartbeatAcknowledgmentRequest":
            await self._handle_heartbeat_acknowledgment(message)
        else:
            logger.warning(f"Unknown DACP message type: {msg_type}")

    async def _handle_open(self, message: Dict[str, Any], websocket: WebSocket):
        """Handle open request - launch the specified app"""
        try:
            request = OpenRequest(**message)
            app_id = request.payload.app.appId

            # Check if app exists in directory
            app_metadata = await self.storage.apps.get_app_metadata(app_id)
            if not app_metadata:
                response = AgentResponse(
                    type="openResponse",
                    payload=ErrorResponsePayload(error="AppNotFound"),
                    meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
                )
                await self._send_model(websocket, response)
                return

            # Check existing instances
            existing_instances = core_services.app_registry.get_instances_for_app(
                app_id
            )
            requested_instance_id = getattr(request.payload.app, "instanceId", None)

            if requested_instance_id:
                existing_instance = next(
                    (
                        inst
                        for inst in existing_instances
                        if inst.instance_id == requested_instance_id
                    ),
                    None,
                )
                if existing_instance:
                    response = OpenResponse(
                        type="openResponse",
                        payload=OpenResponsePayload(),
                        meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
                    )
                    await self._send_model(websocket, response)
                    return
            elif existing_instances:
                # Reuse existing instance
                response = OpenResponse(
                    type="openResponse",
                    payload=OpenResponsePayload(),
                    meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
                )
                await self._send_model(websocket, response)
                return

            # Get launch config
            launch_config = await self.storage.launch_configs.get_launch_config(app_id)
            if not launch_config:
                response = AgentResponse(
                    type="openResponse",
                    payload=ErrorResponsePayload(error="AppNotFound"),
                    meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
                )
                await self._send_model(websocket, response)
                return

            # Launch the app
            launch_result = await self.launcher.launch_app(
                app_id, launch_config, request.payload.context, request.payload.app
            )

            if launch_result.success:
                if not launch_result.instance_id or not launch_result.instance_uuid:
                    response = AgentResponse(
                        type="openResponse",
                        payload=ErrorResponsePayload(error="ErrorOnLaunch"),
                        meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
                    )
                    await self._send_model(websocket, response)
                    return

                # Register as pending
                core_services.app_registry.register_pending_instance(
                    app_id, launch_result.instance_id, launch_result.instance_uuid
                )

                # Wait for connection
                connected = (
                    await core_services.app_registry.wait_for_instance_connection(
                        launch_result.instance_uuid, timeout=15.0
                    )
                )

                if connected:
                    response = OpenResponse(
                        type="openResponse",
                        payload=OpenResponsePayload(),
                        meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
                    )
                else:
                    core_services.app_registry.unregister_instance(
                        launch_result.instance_uuid
                    )
                    response = AgentResponse(
                        type="openResponse",
                        payload=ErrorResponsePayload(error="AppTimeout"),
                        meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
                    )
            else:
                response = AgentResponse(
                    type="openResponse",
                    payload=ErrorResponsePayload(error="ErrorOnLaunch"),
                    meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
                )

            await self._send_model(websocket, response)

        except Exception as e:
            logger.error(f"Failed to open app: {e}")
            # Try to send error response if possible
            try:
                response = AgentResponse(
                    type="openResponse",
                    payload=ErrorResponsePayload(error="AppLaunchFailed"),
                    meta=AgentResponseMeta(
                        requestUuid=message.get("meta", {}).get("requestUuid")
                    ),
                )
                await self._send_model(websocket, response)
            except Exception:
                pass

    async def _handle_broadcast(
        self, message: Dict[str, Any], session_id: str, wcp_sessions: Dict[str, Any]
    ):
        """Handle broadcast request"""
        request = BroadcastRequest(**message)
        source_instance_uuid = wcp_sessions[session_id]["identity"]["instanceUuid"]

        targets = core_services.context_router.broadcast_context(
            request.payload.context, source_instance_uuid
        )

        # Send broadcast event to targets
        for target_uuid in targets:
            event = BroadcastEvent(
                type="broadcastEvent",
                payload=BroadcastEventPayload(context=request.payload.context),
                meta=AgentEventMeta(),
            )
            await self.connection_manager.send_to_instance(
                target_uuid, event.model_dump_json()
            )

    async def _handle_add_context_listener(
        self,
        message: Dict[str, Any],
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ):
        """Handle add context listener request"""
        request = AddContextListenerRequest(**message)
        source_instance_uuid = wcp_sessions[session_id]["identity"]["instanceUuid"]

        from ..api import ListenerUuid

        listener = core_services.listener_store.add_context_listener(
            ListenerUuid(), source_instance_uuid, request.payload.contextType
        )

        response = AddContextListenerResponse(
            type="addContextListenerResponse",
            payload=AddContextListenerResponsePayload(
                listenerUuid=listener.listener_uuid
            ),
            meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
        )
        await self._send_model(websocket, response)

    async def _handle_add_intent_listener(
        self,
        message: Dict[str, Any],
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ):
        """Handle add intent listener request"""
        request = AddIntentListenerRequest(**message)
        source_instance_uuid = wcp_sessions[session_id]["identity"]["instanceUuid"]

        from ..api import ListenerUuid

        listener = core_services.listener_store.add_intent_listener(
            ListenerUuid(), source_instance_uuid, request.payload.intent
        )

        response = AddIntentListenerResponse(
            type="addIntentListenerResponse",
            payload=AddIntentListenerResponsePayload(
                listenerUuid=listener.listener_uuid
            ),
            meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
        )
        await self._send_model(websocket, response)

    async def _handle_intent_listener_unsubscribe(
        self, message: Dict[str, Any], websocket: WebSocket
    ):
        """Handle intent listener unsubscribe"""
        request = IntentListenerUnsubscribeRequest(**message)
        core_services.listener_store.remove_listener(request.payload.listenerUuid.root)

        response = IntentListenerUnsubscribeResponse(
            type="intentListenerUnsubscribeResponse",
            payload=IntentListenerUnsubscribeResponsePayload(),
            meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
        )
        await self._send_model(websocket, response)

    async def _handle_raise_intent(self, message: Dict[str, Any], websocket: WebSocket):
        """Handle raise intent request"""
        request = RaiseIntentRequest(**message)

        # Check if this is a system intent first
        if self.system_intent_handler.is_system_intent(request.payload.intent):
            response = await self.system_intent_handler.handle_system_intent(
                request.payload.intent,
                request.payload.context,
                request.payload.target,
                websocket,
                request.meta.requestUuid,
            )
            if response:
                await self._send_model(websocket, response)
                return

        # Not a system intent or system intent handler failed, try normal resolution
        resolution = core_services.intent_resolver.resolve_intent(
            request.payload.intent, request.payload.context, request.payload.target
        )

        if resolution:
            response = RaiseIntentResponse(
                type="raiseIntentResponse",
                payload=RaiseIntentResponsePayload(
                    intentResolution=resolution.model_dump()
                ),
                meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
            )
            await self._send_model(websocket, response)

            # Send intent event to listeners
            targets = core_services.intent_resolver.deliver_intent_event(
                request.payload.intent, request.payload.context, request.meta.source
            )

            for target_uuid in targets:
                event = IntentEvent(
                    type="intentEvent",
                    payload=IntentEventPayload(
                        intent=request.payload.intent,
                        context=request.payload.context,
                        originatingApp=request.meta.source,
                    ),
                    meta=AgentEventMeta(),
                )
                await self.connection_manager.send_to_instance(
                    target_uuid, event.model_dump_json()
                )
        else:
            response = AgentResponse(
                type="raiseIntentResponse",
                payload=ErrorResponsePayload(error="NoAppsFound"),
                meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
            )
            await self._send_model(websocket, response)

    async def _handle_raise_intent_for_context(
        self, message: Dict[str, Any], websocket: WebSocket
    ):
        """Handle raise intent for context request"""
        request = RaiseIntentForContextRequest(**message)

        # Not implemented - return error
        response = AgentResponse(
            type="raiseIntentForContextResponse",
            payload=ErrorResponsePayload(error="NotImplemented"),
            meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
        )
        await self._send_model(websocket, response)

    async def _handle_intent_result_request(
        self, message: Dict[str, Any], websocket: WebSocket
    ):
        """Handle intent result request"""
        request = IntentResultRequest(**message)

        logger.debug(f"Received intent result: {request.payload.intentResult}")

        response = IntentResultResponse(
            type="intentResultResponse",
            payload=IntentResultResponsePayload(),
            meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
        )
        await self._send_model(websocket, response)

    async def _handle_raise_intent_result_response(self, message: Dict[str, Any]):
        """Handle raise intent result response"""
        request = RaiseIntentResultResponse(**message)
        logger.debug(f"Intent result acknowledged: {request.meta.requestUuid}")

    async def _handle_context_listener_unsubscribe(
        self, message: Dict[str, Any], websocket: WebSocket
    ):
        """Handle context listener unsubscribe"""
        request = ContextListenerUnsubscribeRequest(**message)
        core_services.listener_store.remove_listener(request.payload.listenerUuid.root)

        response = ContextListenerUnsubscribeResponse(
            type="contextListenerUnsubscribeResponse",
            payload=ContextListenerUnsubscribeResponsePayload(),
            meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
        )
        await self._send_model(websocket, response)

    async def _handle_heartbeat_acknowledgment(self, message: Dict[str, Any]):
        """Handle heartbeat acknowledgment"""
        request = HeartbeatAcknowledgmentRequest(**message)
        logger.debug(
            f"Received heartbeat acknowledgment for event {request.payload.heartbeatEventUuid}"
        )
