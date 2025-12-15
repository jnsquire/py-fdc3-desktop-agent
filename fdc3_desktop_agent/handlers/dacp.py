"""
DACP (Desktop Agent Communication Protocol) message handler.
Handles FDC3 operations like app launching, context broadcasting, and listener management.
"""

import logging
import uuid
import asyncio
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
from ..protocol.dacp.message_parser import parse_message, MessageParseError
from ..protocol.dacp.external_models import (
    RegisterExternalHandlerRequest,
    RegisterExternalHandlerResponse,
    RegisterExternalHandlerResponsePayload,
    RegisterExternalHandlerResponseMeta,
    UnregisterExternalHandlerRequest,
    UnregisterExternalHandlerResponse,
    ExternalIntentResultRequest,
    ForwardedIntentMessage,
    ForwardedIntentPayload,
)
from ..storage import Storage
from ..launcher.interfaces import ProcessLauncher
from ..api import IntentResolution, AppIdentifier
from ..api import RequestUuid
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
        """Handle DACP message with centralized Pydantic validation."""
        msg_type = message.get("type")

        # Parse and validate message using Pydantic
        try:
            parsed = parse_message(message)
        except MessageParseError as e:
            logger.warning(f"Failed to parse DACP message: {e}")
            # Send error response if we can determine the response type
            response_type = f"{msg_type}Response" if msg_type else "errorResponse"
            err = AgentResponse(
                type=response_type,
                payload=ErrorResponsePayload(error=str(e)),
                meta=AgentResponseMeta(
                    requestUuid=(
                        RequestUuid(e.request_uuid) if e.request_uuid else RequestUuid()
                    )
                ),
            )
            await self._send_model(websocket, err)
            return

        # Dispatch to typed handlers based on parsed model type
        if isinstance(parsed, OpenRequest):
            await self._handle_open(parsed, websocket)
        elif isinstance(parsed, BroadcastRequest):
            await self._handle_broadcast(parsed, session_id, wcp_sessions)
        elif isinstance(parsed, AddContextListenerRequest):
            await self._handle_add_context_listener(
                parsed, session_id, wcp_sessions, websocket
            )
        elif isinstance(parsed, AddIntentListenerRequest):
            await self._handle_add_intent_listener(
                parsed, session_id, wcp_sessions, websocket
            )
        elif isinstance(parsed, IntentListenerUnsubscribeRequest):
            await self._handle_intent_listener_unsubscribe(parsed, websocket)
        elif isinstance(parsed, RegisterExternalHandlerRequest):
            await self._handle_register_external_handler(
                parsed, session_id, wcp_sessions, websocket
            )
        elif isinstance(parsed, UnregisterExternalHandlerRequest):
            await self._handle_unregister_external_handler(
                parsed, session_id, wcp_sessions, websocket
            )
        elif isinstance(parsed, ExternalIntentResultRequest):
            await self._handle_external_intent_result(parsed)
        elif isinstance(parsed, RaiseIntentRequest):
            await self._handle_raise_intent(parsed, websocket)
        elif isinstance(parsed, RaiseIntentForContextRequest):
            await self._handle_raise_intent_for_context(parsed, websocket)
        elif isinstance(parsed, IntentResultRequest):
            await self._handle_intent_result_request(parsed, websocket)
        elif isinstance(parsed, RaiseIntentResultResponse):
            await self._handle_raise_intent_result_response(parsed)
        elif isinstance(parsed, ContextListenerUnsubscribeRequest):
            await self._handle_context_listener_unsubscribe(parsed, websocket)
        elif isinstance(parsed, HeartbeatAcknowledgmentRequest):
            await self._handle_heartbeat_acknowledgment(parsed)
        else:
            logger.warning(f"Unknown DACP message type: {msg_type}")

    async def _handle_open(self, request: OpenRequest, websocket: WebSocket):
        """Handle open request - launch the specified app"""
        try:
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
                    meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
                )
                await self._send_model(websocket, response)
            except Exception:
                pass

    async def _handle_broadcast(
        self, request: BroadcastRequest, session_id: str, wcp_sessions: Dict[str, Any]
    ):
        """Handle broadcast request"""
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
        request: AddContextListenerRequest,
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ):
        """Handle add context listener request"""
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
        request: AddIntentListenerRequest,
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ):
        """Handle add intent listener request"""
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
        self, request: IntentListenerUnsubscribeRequest, websocket: WebSocket
    ):
        """Handle intent listener unsubscribe"""
        core_services.listener_store.remove_listener(request.payload.listenerUuid.root)

        response = IntentListenerUnsubscribeResponse(
            type="intentListenerUnsubscribeResponse",
            payload=IntentListenerUnsubscribeResponsePayload(),
            meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
        )
        await self._send_model(websocket, response)

    async def _handle_raise_intent(
        self, request: RaiseIntentRequest, websocket: WebSocket
    ):
        """Handle raise intent request"""
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

        # Check if a plugin handles this intent
        plugin_result = await self._try_plugin_handler(request)
        if plugin_result is not None:
            await self._send_model(websocket, plugin_result)
            return

        # Check if an external handler can handle this intent
        external_result = await self._try_external_handler(request, websocket)
        if external_result is not None:
            # external_result is either an AgentResponse or RaiseIntentResponse
            await self._send_model(websocket, external_result)
            return

        # Not a system intent or plugin, try normal resolution
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
        self, request: RaiseIntentForContextRequest, websocket: WebSocket
    ):
        """Handle raise intent for context request"""
        # Not implemented - return error
        response = AgentResponse(
            type="raiseIntentForContextResponse",
            payload=ErrorResponsePayload(error="NotImplemented"),
            meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
        )
        await self._send_model(websocket, response)

    async def _handle_intent_result_request(
        self, request: IntentResultRequest, websocket: WebSocket
    ):
        """Handle intent result request"""
        logger.debug(f"Received intent result: {request.payload.intentResult}")

        response = IntentResultResponse(
            type="intentResultResponse",
            payload=IntentResultResponsePayload(),
            meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
        )
        await self._send_model(websocket, response)

    async def _handle_raise_intent_result_response(
        self, request: RaiseIntentResultResponse
    ):
        """Handle raise intent result response"""
        logger.debug(f"Intent result acknowledged: {request.meta.requestUuid}")

    async def _handle_context_listener_unsubscribe(
        self, request: ContextListenerUnsubscribeRequest, websocket: WebSocket
    ):
        """Handle context listener unsubscribe"""
        core_services.listener_store.remove_listener(request.payload.listenerUuid.root)

        response = ContextListenerUnsubscribeResponse(
            type="contextListenerUnsubscribeResponse",
            payload=ContextListenerUnsubscribeResponsePayload(),
            meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
        )
        await self._send_model(websocket, response)

    async def _handle_heartbeat_acknowledgment(
        self, request: HeartbeatAcknowledgmentRequest
    ):
        """Handle heartbeat acknowledgment"""
        logger.debug(
            f"Received heartbeat acknowledgment for event {request.payload.heartbeatEventUuid}"
        )

    async def _try_plugin_handler(
        self, request: RaiseIntentRequest
    ) -> AgentResponse | RaiseIntentResponse | None:
        """Try to handle intent via registered plugins.

        Args:
            request: The RaiseIntentRequest from the client.

        Returns:
            Response model if a plugin handled the intent, None otherwise.
        """
        plugins = core_services.plugin_registry.get_plugins_for_intent(
            request.payload.intent
        )

        for plugin in plugins:
            try:
                result = await plugin.handle_intent(
                    request.payload.intent,
                    request.payload.context,
                    request.meta.source.model_dump() if request.meta.source else None,
                )

                if result.handled:
                    if result.error:
                        # Plugin handled but returned an error
                        return AgentResponse(
                            type="raiseIntentResponse",
                            payload=ErrorResponsePayload(error=result.error),
                            meta=AgentResponseMeta(
                                requestUuid=request.meta.requestUuid
                            ),
                        )

                    # Plugin handled successfully
                    resolution = IntentResolution(
                        source=AppIdentifier(
                            appId=f"plugin:{plugin.name}",
                            instanceId=None,
                            desktopAgent=None,
                        ),
                        intent=request.payload.intent,
                    )
                    return RaiseIntentResponse(
                        type="raiseIntentResponse",
                        payload=RaiseIntentResponsePayload(
                            intentResolution=resolution.model_dump()
                        ),
                        meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
                    )

            except Exception as e:
                logger.error(
                    f"Plugin {plugin.name} raised exception handling "
                    f"{request.payload.intent}: {e}"
                )
                # Continue to next plugin

        return None

    async def _handle_register_external_handler(
        self,
        request: RegisterExternalHandlerRequest,
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ) -> None:
        """Handle external handler registration - message already validated by parser."""
        try:
            instance_uuid = wcp_sessions[session_id]["identity"]["instanceUuid"]
            handler_uuid = await core_services.register_external_handler(
                instance_uuid,
                request.payload.handler_id,
                request.payload.intents,
                request.payload.priority,
                request.payload.metadata,
            )

            # send success response
            response = RegisterExternalHandlerResponse(
                payload=RegisterExternalHandlerResponsePayload(
                    handler_uuid=handler_uuid
                ),
                meta=RegisterExternalHandlerResponseMeta(
                    requestUuid=str(request.meta.requestUuid)
                ),
            )
            await websocket.send_text(response.model_dump_json())
        except Exception:
            logger.exception("Failed to register external handler")
            err = AgentResponse(
                type="registerExternalHandlerResponse",
                payload=ErrorResponsePayload(error="InternalError"),
                meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
            )
            await self._send_model(websocket, err)

    async def _handle_unregister_external_handler(
        self,
        request: UnregisterExternalHandlerRequest,
        session_id: str,
        wcp_sessions: Dict[str, Any],
        websocket: WebSocket,
    ):
        """Handle external handler unregistration - message already validated by parser."""
        try:
            await core_services.unregister_external_handler(
                request.payload.handler_uuid
            )

            # Send success response using Pydantic model
            response = UnregisterExternalHandlerResponse(
                meta=RegisterExternalHandlerResponseMeta(
                    requestUuid=str(request.meta.requestUuid)
                ),
            )
            await websocket.send_text(response.model_dump_json())
        except Exception:
            logger.exception("Failed to unregister external handler")
            err = AgentResponse(
                type="unregisterExternalHandlerResponse",
                payload=ErrorResponsePayload(error="InternalError"),
                meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
            )
            await self._send_model(websocket, err)

    async def _handle_external_intent_result(
        self, request: ExternalIntentResultRequest
    ) -> None:
        """Handle intent result from external handler - message already validated by parser."""
        try:
            core_services.resolve_pending_intent(
                request.payload.request_uuid,
                result=request.payload.result,
                error=request.payload.error,
            )
        except Exception:
            logger.exception("Failed to handle external intent result")

    async def _try_external_handler(
        self, request: RaiseIntentRequest, websocket: WebSocket
    ) -> RaiseIntentResponse | AgentResponse | None:
        """Try to handle intent via registered external handlers.

        Args:
            request: The validated RaiseIntentRequest from the client.
            websocket: The WebSocket connection to respond on.

        Returns:
            Response model if an external handler processed the intent, None otherwise.
        """
        # Find registered external handlers for this intent
        handlers = core_services.external_registry.get_handlers_for_intent(
            request.payload.intent
        )
        if not handlers:
            return None

        # Choose first handler (highest priority)
        handler = handlers[0]

        # Build forwarded intent message using Pydantic model
        request_uuid = str(uuid.uuid4())
        forwarded = ForwardedIntentMessage(
            payload=ForwardedIntentPayload(
                request_uuid=request_uuid,
                intent=request.payload.intent,
                context=request.payload.context or {},
                source=request.meta.source.model_dump() if request.meta.source else {},
            )
        )

        # Create pending future for response correlation
        fut = core_services.create_pending_intent(request_uuid)

        try:
            # Send forwarded intent message using Pydantic serialization
            await self.connection_manager.send_to_instance(
                handler.instance_uuid, forwarded.model_dump_json()
            )
        except Exception as e:
            logger.exception(
                f"Failed to forward intent to external handler {handler.handler_id}: {e}"
            )
            core_services.resolve_pending_intent(request_uuid, error=str(e))
            return None

        try:
            # Wait for result with a reasonable timeout
            result = await asyncio.wait_for(fut, timeout=30.0)
        except asyncio.TimeoutError:
            logger.debug(f"External handler {handler.handler_id} timed out")
            return None
        except Exception as e:
            logger.debug(f"External handler failed: {e}")
            return None

        if result is None:
            return None

        # Build response using the result
        resolution = IntentResolution(
            source=AppIdentifier(
                appId=f"external:{handler.handler_id}",
                instanceId=None,
                desktopAgent=None,
            ),
            intent=request.payload.intent,
        )
        return RaiseIntentResponse(
            type="raiseIntentResponse",
            payload=RaiseIntentResponsePayload(
                intentResolution=resolution.model_dump()
            ),
            meta=AgentResponseMeta(requestUuid=request.meta.requestUuid),
        )
