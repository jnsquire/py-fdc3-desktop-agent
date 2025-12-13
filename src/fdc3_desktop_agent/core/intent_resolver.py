from typing import List, Optional
from .listener_store import ListenerStore
from .app_registry import AppRegistry
from ..api import AppIdentifier, IntentResolution

class IntentResolver:
    """Handles find/raise intents, app selection, and delivery to intent listeners."""

    def __init__(self, listener_store: ListenerStore, app_registry: AppRegistry):
        self.listener_store = listener_store
        self.app_registry = app_registry

    def find_intent_listeners(self, intent: str) -> List[str]:
        """Find instance_uuids that have listeners for the intent."""
        listeners = self.listener_store.get_intent_listeners_for_intent(intent)
        return [listener.instance_uuid for listener in listeners]

    def resolve_intent(self, intent: str, context: Optional[dict] = None, target: Optional[AppIdentifier] = None) -> Optional[IntentResolution]:
        """Resolve an intent to an app instance."""
        # For now, find any listener for the intent
        listeners = self.listener_store.get_intent_listeners_for_intent(intent)
        if not listeners:
            return None

        # Select first listener (simple policy)
        selected_listener = listeners[0]
        instance = self.app_registry.get_instance(selected_listener.instance_uuid)
        if not instance:
            return None

        # Create resolution
        source = AppIdentifier(appId=instance.app_id, instanceId=instance.instance_id)
        resolution = IntentResolution(source=source, intent=intent)
        return resolution

    def deliver_intent_event(self, intent: str, context: Optional[dict], originating_app: Optional[AppIdentifier]) -> List[str]:
        """Deliver intent event to listeners. Returns target instance_uuids."""
        listeners = self.listener_store.get_intent_listeners_for_intent(intent)
        return [listener.instance_uuid for listener in listeners]