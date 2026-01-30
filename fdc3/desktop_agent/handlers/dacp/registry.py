"""
Handler registry and decorator for DACP messages.
"""


def dacp_handler(request_type: type, *, needs_session: bool) -> callable:
    """Decorator to register a DACP message handler.

    Args:
        request_type: The request class type handled by this method.
        needs_session: Whether the handler requires session_id and wcp_sessions.
    """

    def decorator(func):
        setattr(func, "_dacp_handler_info", (request_type, needs_session))
        return func

    return decorator


class DACPError:
    """Standardized DACP error codes."""

    APP_NOT_FOUND = "AppNotFound"
    APP_TIMEOUT = "AppTimeout"
    ERROR_ON_LAUNCH = "ErrorOnLaunch"
    INTERNAL_ERROR = "InternalError"
    NO_APPS_FOUND = "NoAppsFound"
    NO_CHANNEL_FOUND = "NoChannelFound"
    CHANNEL_CREATION_FAILED = "CreationFailed"
    CHANNEL_ACCESS_DENIED = "AccessDenied"
    RESOLVER_UNAVAILABLE = "ResolverUnavailable"
    TARGET_APP_UNAVAILABLE = "TargetAppUnavailable"
    TARGET_INSTANCE_UNAVAILABLE = "TargetInstanceUnavailable"
