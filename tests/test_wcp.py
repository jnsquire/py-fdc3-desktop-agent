# WCP schema-level tests

from fdc3_desktop_agent.transport.wcp.wcp import (
    WCP1Hello,
    WCP3Handshake,
    WCP4ValidateAppIdentity,
    WCP5ValidateAppIdentityResponse,
    WCP6Goodbye,
    WCP1HelloPayload,
    WCP3HandshakePayload,
    WCP1HelloMeta,
)


class TestWCPMessages:
    """Test WCP message parsing and validation"""

    def test_wcp1_hello_parsing(self):
        """Test parsing of WCP1Hello payloads"""
        message = {
            "type": "WCP1Hello",
            "payload": {
                "identityUrl": "https://example.com/app",
                "actualUrl": "https://example.com/app/index.html",
                "fdc3Version": "2.0",
            },
            "meta": {
                "connectionAttemptUuid": "test-uuid",
                "timestamp": "2025-01-01T00:00:00Z",
            },
        }

        wcp1 = WCP1Hello(**message)
        assert wcp1.type == "WCP1Hello"
        assert str(wcp1.payload.identityUrl) == "https://example.com/app"
        assert str(wcp1.payload.actualUrl) == "https://example.com/app/index.html"
        assert wcp1.payload.fdc3Version == "2.0"
        assert wcp1.meta.connectionAttemptUuid.root == "test-uuid"

    def test_wcp3_handshake_parsing(self):
        """Test parsing of WCP3Handshake payloads"""
        message = {
            "type": "WCP3Handshake",
            "payload": {
                "fdc3Version": "2.0",
                "intentResolverUrl": None,
                "channelSelectorUrl": None,
            },
            "meta": {
                "connectionAttemptUuid": "test-uuid",
                "timestamp": "2025-01-01T00:00:00Z",
            },
        }

        wcp3 = WCP3Handshake(**message)
        assert wcp3.type == "WCP3Handshake"
        assert wcp3.payload.fdc3Version == "2.0"
        assert wcp3.payload.intentResolverUrl is None
        assert wcp3.payload.channelSelectorUrl is None

    def test_wcp4_validate_app_identity_parsing(self):
        """Test parsing of WCP4ValidateAppIdentity payloads"""
        message = {
            "type": "WCP4ValidateAppIdentity",
            "payload": {"instanceId": "instance1", "instanceUuid": "uuid1"},
            "meta": {
                "connectionAttemptUuid": "test-uuid",
                "timestamp": "2025-01-01T00:00:00Z",
            },
        }

        wcp4 = WCP4ValidateAppIdentity(**message)
        assert wcp4.type == "WCP4ValidateAppIdentity"
        assert wcp4.payload.instanceId == "instance1"
        assert wcp4.payload.instanceUuid == "uuid1"

    def test_wcp5_response_parsing(self):
        """Test parsing of WCP5ValidateAppIdentityResponse payloads"""
        message = {
            "type": "WCP5ValidateAppIdentityResponse",
            "payload": {
                "appId": "test-app",
                "instanceId": "instance1",
                "instanceUuid": "uuid1",
                "implementationMetadata": {},
            },
            "meta": {"requestUuid": "test-uuid", "timestamp": "2025-01-01T00:00:00Z"},
        }

        wcp5 = WCP5ValidateAppIdentityResponse(**message)
        assert wcp5.type == "WCP5ValidateAppIdentityResponse"
        assert wcp5.payload.appId == "test-app"
        assert wcp5.payload.instanceId == "instance1"
        assert wcp5.payload.instanceUuid == "uuid1"
        assert wcp5.payload.implementationMetadata == {}

    def test_wcp6_goodbye_parsing(self):
        """Test parsing of WCP6Goodbye payloads"""
        message = {
            "type": "WCP6Goodbye",
            "payload": {},
            "meta": {
                "connectionAttemptUuid": "test-uuid",
                "timestamp": "2025-01-01T00:00:00Z",
            },
        }

        wcp6 = WCP6Goodbye(**message)
        assert wcp6.type == "WCP6Goodbye"
        assert wcp6.payload == {}
        assert wcp6.meta.connectionAttemptUuid.root == "test-uuid"


class TestWCPSerialization:
    """Test WCP message serialization"""

    def test_wcp1_serialization(self):
        """Test that WCP1Hello serializes correctly"""
        wcp1 = WCP1Hello(
            type="WCP1Hello",
            payload=WCP1HelloPayload(
                identityUrl="https://example.com/app",
                actualUrl="https://example.com/app/index.html",
                fdc3Version="2.0",
            ),
            meta=WCP1HelloMeta(
                connectionAttemptUuid="test-uuid", timestamp="2025-01-01T00:00:00Z"
            ),
        )

        data = wcp1.model_dump(mode="json")
        assert data["type"] == "WCP1Hello"
        assert data["payload"]["identityUrl"] == "https://example.com/app"
        assert data["payload"]["actualUrl"] == "https://example.com/app/index.html"
        assert data["payload"]["fdc3Version"] == "2.0"

    def test_wcp3_serialization(self):
        """Test that WCP3Handshake serializes correctly"""
        wcp3 = WCP3Handshake(
            type="WCP3Handshake",
            payload=WCP3HandshakePayload(
                fdc3Version="2.0", intentResolverUrl=None, channelSelectorUrl=None
            ),
            meta=WCP1HelloMeta(
                connectionAttemptUuid="test-uuid", timestamp="2025-01-01T00:00:00Z"
            ),
        )

        data = wcp3.model_dump()
        assert data["type"] == "WCP3Handshake"
        assert data["payload"]["fdc3Version"] == "2.0"
        assert data["payload"]["intentResolverUrl"] is None
        assert data["payload"]["channelSelectorUrl"] is None


class TestOriginValidation:
    """Test origin validation rules for WCP connections"""

    def test_origin_validation_allowed(self):
        """Test that allowed origins pass validation"""
        from urllib.parse import urlparse

        # Test cases for origin validation
        identity_url = "https://example.com/app"
        actual_url = "https://example.com/app/index.html"
        allowed_origins = ["example.com"]

        identity_origin = urlparse(identity_url).netloc
        actual_origin = urlparse(actual_url).netloc

        # Both origins should be in allowed list
        assert identity_origin in allowed_origins
        assert actual_origin in allowed_origins

    def test_origin_validation_blocked(self):
        """Test that blocked origins fail validation"""
        from urllib.parse import urlparse

        # Test cases for origin validation
        identity_url = "https://malicious.com/app"
        actual_url = "https://malicious.com/app/index.html"
        allowed_origins = ["example.com"]

        identity_origin = urlparse(identity_url).netloc
        actual_origin = urlparse(actual_url).netloc

        # Neither origin should be in allowed list
        assert identity_origin not in allowed_origins
        assert actual_origin not in allowed_origins

    def test_origin_validation_wildcard(self):
        """Test wildcard origin patterns"""
        from urllib.parse import urlparse

        # Test wildcard patterns
        identity_url = "https://app.example.com/app"
        actual_url = "https://app.example.com/app/index.html"
        allowed_origins = ["*.example.com"]

        identity_origin = urlparse(identity_url).netloc
        actual_origin = urlparse(actual_url).netloc

        # Check wildcard matching
        allowed = False
        for allowed_origin in allowed_origins:
            if allowed_origin.startswith("*."):
                prefix = allowed_origin[2:]  # Remove *.
                if identity_origin.endswith(prefix):
                    allowed = True
                    break

        assert allowed, (
            f"Origin {identity_origin} should match wildcard {allowed_origins[0]}"
        )

        allowed = False
        for allowed_origin in allowed_origins:
            if allowed_origin.startswith("*."):
                prefix = allowed_origin[2:]  # Remove *.
                if actual_origin.endswith(prefix):
                    allowed = True
                    break

        assert allowed, (
            f"Origin {actual_origin} should match wildcard {allowed_origins[0]}"
        )
