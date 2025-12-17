"""DACP models package (relocated).

This package exposes the Pydantic models previously hosted under
`fdc3.desktop_agent.protocol.dacp` and the external handler models.
Consumers should import from `fdc3.models.dacp`.
"""

from . import dacp as _dacp
from . import external_models as _external
# Legacy registry support removed; export only model symbols.

# Re-export commonly used models
BroadcastEvent = _dacp.BroadcastEvent
IntentEvent = _dacp.IntentEvent
AddContextListenerResponse = _dacp.AddContextListenerResponse
AddIntentListenerResponse = _dacp.AddIntentListenerResponse
ContextListenerUnsubscribeResponse = _dacp.ContextListenerUnsubscribeResponse
IntentListenerUnsubscribeResponse = _dacp.IntentListenerUnsubscribeResponse

# External handler models
ForwardedIntentMessage = _external.ForwardedIntentMessage
RegisterExternalHandlerResponse = _external.RegisterExternalHandlerResponse
UnregisterExternalHandlerResponse = _external.UnregisterExternalHandlerResponse

# Expose module aliases for advanced usage
_dacp = _dacp
_external = _external
