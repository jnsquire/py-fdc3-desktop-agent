import pytest

from fdc3_desktop_agent.access_control import (
    AccessControlManager,
    AccessControlPolicy,
    AccessRequest,
    AccessDecision,
    AllowlistAccessPolicy,
)


class TestAccessRequest:
    def test_creation(self):
        request = AccessRequest(origin="https://example.com", user_agent="TestAgent")
        assert request.origin == "https://example.com"
        assert request.user_agent == "TestAgent"

    def test_creation_with_none_values(self):
        request = AccessRequest(origin=None, user_agent=None)
        assert request.origin is None
        assert request.user_agent is None


class TestAccessDecision:
    def test_creation_allowed(self):
        decision = AccessDecision(allowed=True, reason="OK")
        assert decision.allowed is True
        assert decision.reason == "OK"

    def test_creation_denied(self):
        decision = AccessDecision(allowed=False, reason="Blocked")
        assert decision.allowed is False
        assert decision.reason == "Blocked"


class TestAllowlistAccessPolicy:
    def test_allow_all_wildcard(self):
        policy = AllowlistAccessPolicy(["*"])
        
        # Should allow any origin
        request = AccessRequest(origin="https://example.com", user_agent="Test")
        decision = policy.evaluate_access(request)
        assert decision.allowed is True
        assert decision.reason == "Wildcard allowlist"

    def test_exact_match(self):
        policy = AllowlistAccessPolicy(["example.com"])
        
        # Should allow exact match
        request = AccessRequest(origin="https://example.com", user_agent="Test")
        decision = policy.evaluate_access(request)
        assert decision.allowed is True
        assert decision.reason == "Origin in allowlist"

    def test_wildcard_prefix_match(self):
        policy = AllowlistAccessPolicy(["*.example.com"])
        
        # Should allow subdomain
        request = AccessRequest(origin="https://app.example.com", user_agent="Test")
        decision = policy.evaluate_access(request)
        assert decision.allowed is True
        assert decision.reason == "Origin matches wildcard pattern"

    def test_wildcard_prefix_no_match(self):
        policy = AllowlistAccessPolicy(["*.example.com"])
        
        # Should deny different domain
        request = AccessRequest(origin="https://other.com", user_agent="Test")
        decision = policy.evaluate_access(request)
        assert decision.allowed is False
        assert decision.reason == "Origin not in allowlist"

    def test_no_origin(self):
        policy = AllowlistAccessPolicy(["example.com"])
        
        # Should deny if no origin provided
        request = AccessRequest(origin=None, user_agent="Test")
        decision = policy.evaluate_access(request)
        assert decision.allowed is False
        assert decision.reason == "No origin provided"

    def test_empty_allowlist(self):
        policy = AllowlistAccessPolicy([])
        
        # Should deny all
        request = AccessRequest(origin="https://example.com", user_agent="Test")
        decision = policy.evaluate_access(request)
        assert decision.allowed is False
        assert decision.reason == "Empty allowlist"


class TestAccessControlManager:
    def test_initialization(self):
        policy = AllowlistAccessPolicy(["example.com"])
        manager = AccessControlManager(policy)
        assert manager.policy == policy

    @pytest.mark.asyncio
    async def test_check_access_allowed(self):
        policy = AllowlistAccessPolicy(["example.com"])
        manager = AccessControlManager(policy)
        
        request = AccessRequest(origin="https://example.com", user_agent="Test")
        decision = await manager.check_access(request)
        
        assert decision.allowed is True
        assert decision.reason == "Origin in allowlist"

    @pytest.mark.asyncio
    async def test_check_access_denied(self):
        policy = AllowlistAccessPolicy(["example.com"])
        manager = AccessControlManager(policy)
        
        request = AccessRequest(origin="https://blocked.com", user_agent="Test")
        decision = await manager.check_access(request)
        
        assert decision.allowed is False
        assert decision.reason == "Origin not in allowlist"


class MockAccessPolicy(AccessControlPolicy):
    def __init__(self, decision: AccessDecision):
        self.decision = decision

    def evaluate_access(self, request: AccessRequest) -> AccessDecision:
        return self.decision


class TestAccessControlManagerWithMock:
    @pytest.mark.asyncio
    async def test_check_access_with_mock_policy(self):
        mock_decision = AccessDecision(allowed=True, reason="Mock allowed")
        policy = MockAccessPolicy(mock_decision)
        manager = AccessControlManager(policy)
        
        request = AccessRequest(origin="https://test.com", user_agent="Test")
        decision = await manager.check_access(request)
        
        assert decision.allowed is True
        assert decision.reason == "Mock allowed"