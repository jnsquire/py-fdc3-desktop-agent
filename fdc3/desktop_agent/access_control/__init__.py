# Access control module

# Access control interfaces and implementations

from abc import ABC, abstractmethod
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class AccessRequest:
    """Represents an access request to be evaluated by a policy"""

    origin: Optional[str] = None
    user_agent: Optional[str] = None
    app_id: Optional[str] = None
    instance_id: Optional[str] = None
    # Add more fields as needed for future policies


@dataclass
class AccessDecision:
    """Result of an access control decision"""

    allowed: bool
    reason: Optional[str] = None


class AccessControlPolicy(ABC):
    """Interface for access control policies"""

    @abstractmethod
    def evaluate_access(self, request: AccessRequest) -> AccessDecision:
        """Evaluate whether access should be granted for the given request"""
        pass


class AllowlistAccessPolicy(AccessControlPolicy):
    """Access control policy based on an allowlist of origins"""

    def __init__(self, allowed_origins: List[str]):
        self.allowed_origins = allowed_origins

    def evaluate_access(self, request: AccessRequest) -> AccessDecision:
        """Evaluate access based on origin allowlist"""
        # Skip validation if "*" is in allowed origins (allow all),
        # even when no Origin header is present (useful for dev/test clients).
        if "*" in self.allowed_origins:
            return AccessDecision(allowed=True, reason="Wildcard allowlist")

        if not request.origin:
            return AccessDecision(allowed=False, reason="No origin provided")

        from urllib.parse import urlparse

        origin_domain = urlparse(request.origin).netloc

        # Check for empty allowlist
        if not self.allowed_origins:
            return AccessDecision(allowed=False, reason="Empty allowlist")

        # Check if origin matches any allowed pattern
        for allowed_origin in self.allowed_origins:
            if allowed_origin.startswith("*."):
                # Wildcard pattern - match subdomains (*.example.com matches app.example.com)
                suffix = allowed_origin[2:]  # Remove the *.
                if origin_domain == suffix or origin_domain.endswith("." + suffix):
                    return AccessDecision(
                        allowed=True, reason="Origin matches wildcard pattern"
                    )
            elif allowed_origin.endswith("*"):
                # Wildcard pattern - match prefix (example.com* matches example.com, example.com.au, etc.)
                prefix = allowed_origin[:-1]  # Remove the *
                if origin_domain.startswith(prefix):
                    return AccessDecision(
                        allowed=True, reason="Origin matches wildcard pattern"
                    )
            elif origin_domain == allowed_origin:
                return AccessDecision(allowed=True, reason="Origin in allowlist")

        return AccessDecision(allowed=False, reason="Origin not in allowlist")


class AccessControlManager:
    """Manages access control policies.

    Args:
        policy: Optional explicit policy to use.
        allowed_origins: Optional list of allowed origins. If provided and no
            explicit policy is given, creates an AllowlistAccessPolicy.
    """

    def __init__(
        self,
        policy: Optional[AccessControlPolicy] = None,
        *,
        allowed_origins: Optional[List[str]] = None,
    ):
        if policy is not None:
            self.policy = policy
        elif allowed_origins:
            self.policy = AllowlistAccessPolicy(allowed_origins)
        else:
            self.policy = None

    async def check_access(self, request: AccessRequest) -> AccessDecision:
        """Check access using the configured policy"""
        if self.policy is None:
            # Default to allow all if no policy is set
            return AccessDecision(
                allowed=True, reason="No access control policy configured"
            )

        return self.policy.evaluate_access(request)

    def set_policy(self, policy: AccessControlPolicy):
        """Set the access control policy"""
        self.policy = policy
