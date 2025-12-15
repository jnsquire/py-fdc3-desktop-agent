# DACP envelope tests

import uuid
from datetime import datetime
from fdc3.desktop_agent.protocol.dacp.dacp import (
    AgentResponseMeta,
    AgentEventMeta,
    OpenRequest,
    OpenResponse,
    BroadcastRequest,
    BroadcastEvent,
    AddContextListenerRequest,
    RaiseIntentRequest,
    AgentResponse,
    ErrorResponsePayload,
    BroadcastEventPayload,
)
from fdc3.desktop_agent.api import OpenError


class TestDACPEnvelopes:
    """Test DACP envelope parsing and correlation"""

    def test_request_envelope_parsing(self):
        """Test parsing of app request envelopes"""
        message = {
            "type": "open",
            "payload": {"app": {"appId": "test-app"}},
            "meta": {
                "requestUuid": "req-123",
                "timestamp": "2025-01-01T00:00:00Z",
                "source": {"appId": "source-app", "instanceId": "source-instance"},
            },
        }

        request = OpenRequest(**message)
        assert request.type == "open"
        assert request.payload.app.appId == "test-app"
        assert request.meta.requestUuid.root == "req-123"
        assert request.meta.source.appId == "source-app"

    def test_response_envelope_correlation(self):
        """Test that responses echo requestUuid and generate responseUuid"""
        request_uuid = str(uuid.uuid4())

        response = OpenResponse(
            type="openResponse",
            payload={},
            meta=AgentResponseMeta(
                requestUuid=request_uuid,
                responseUuid=str(uuid.uuid4()),
                timestamp=datetime.now().isoformat(),
            ),
        )

        assert response.meta.requestUuid.root == request_uuid
        assert response.meta.responseUuid.root != request_uuid  # Should be different
        assert isinstance(uuid.UUID(response.meta.responseUuid.root), uuid.UUID)

    def test_event_envelope_uuid_generation(self):
        """Test that events generate unique eventUuid"""
        event = BroadcastEvent(
            type="broadcastEvent",
            payload=BroadcastEventPayload(context={"type": "test"}),
            meta=AgentEventMeta(
                eventUuid=str(uuid.uuid4()), timestamp=datetime.now().isoformat()
            ),
        )

        assert isinstance(uuid.UUID(event.meta.eventUuid.root), uuid.UUID)

    def test_error_response_payload(self):
        """Test error response payloads use proper error enums"""
        error_response = AgentResponse(
            type="openResponse",
            payload=ErrorResponsePayload(error="AppNotFound"),
            meta=AgentResponseMeta(
                requestUuid="req-123",
                responseUuid=str(uuid.uuid4()),
                timestamp=datetime.now().isoformat(),
            ),
        )

        assert error_response.payload.error == "AppNotFound"
        # Verify it's a valid error from the enum
        assert "AppNotFound" in [e.value for e in OpenError]


class TestDACPSpecificMessages:
    """Test specific DACP message types"""

    def test_broadcast_request_parsing(self):
        """Test parsing of broadcast requests"""
        message = {
            "type": "broadcast",
            "payload": {
                "context": {"type": "fdc3.instrument", "id": {"ticker": "AAPL"}}
            },
            "meta": {
                "requestUuid": "req-123",
                "timestamp": "2025-01-01T00:00:00Z",
                "source": {"appId": "source-app", "instanceId": "source-instance"},
            },
        }

        request = BroadcastRequest(**message)
        assert request.type == "broadcast"
        assert request.payload.context["type"] == "fdc3.instrument"
        assert request.payload.context["id"]["ticker"] == "AAPL"

    def test_add_context_listener_request(self):
        """Test parsing of add context listener requests"""
        message = {
            "type": "addContextListener",
            "payload": {"contextType": "fdc3.instrument"},
            "meta": {"requestUuid": "req-123", "timestamp": "2025-01-01T00:00:00Z"},
        }

        request = AddContextListenerRequest(**message)
        assert request.type == "addContextListener"
        assert request.payload.contextType == "fdc3.instrument"

    def test_raise_intent_request(self):
        """Test parsing of raise intent requests"""
        message = {
            "type": "raiseIntent",
            "payload": {
                "intent": "ViewChart",
                "context": {"type": "fdc3.instrument", "id": {"ticker": "AAPL"}},
                "target": {"appId": "target-app"},
            },
            "meta": {
                "requestUuid": "req-123",
                "timestamp": "2025-01-01T00:00:00Z",
                "source": {"appId": "source-app", "instanceId": "source-instance"},
            },
        }

        request = RaiseIntentRequest(**message)
        assert request.type == "raiseIntent"
        assert request.payload.intent == "ViewChart"
        assert request.payload.context["type"] == "fdc3.instrument"
        assert request.payload.target.appId == "target-app"
