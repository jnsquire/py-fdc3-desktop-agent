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

    def resolve_intent(
        self,
        intent: str,
        context: Optional[dict] = None,
        target: Optional[AppIdentifier] = None,
    ) -> Optional[IntentResolution]:
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

    def deliver_intent_event(
        self,
        intent: str,
        context: Optional[dict],
        originating_app: Optional[AppIdentifier],
    ) -> List[str]:
        """Deliver intent event to listeners. Returns target instance_uuids."""
        listeners = self.listener_store.get_intent_listeners_for_intent(intent)
        return [listener.instance_uuid for listener in listeners]

    def deliver_intent_event_with_resolution(
        self,
        intent: str,
        context: Optional[dict],
        resolution: Optional[IntentResolution],
        originating_app: Optional[AppIdentifier],
    ) -> List[str]:
        """Deliver an intent event preferring the provided resolution.

        This avoids races between resolution and listener changes by attempting
        to deliver the event specifically to the resolved instance (by
        matching AppIdentifier.instanceId -> instance_uuid). If the resolved
        instance is not available or does not have a listener for the intent,
        falls back to the normal listener-based delivery.
        """
        # If no resolution available, fall back to normal delivery
        if resolution is None:
            return self.deliver_intent_event(intent, context, originating_app)

        try:
            src = resolution.source
            if src and src.instanceId:
                # Find the instance record for the resolved app/instance id
                instances = self.app_registry.get_instances_for_app(src.appId)
                for inst in instances:
                    if inst.instance_id == src.instanceId:
                        # Verify that this instance has a listener for the intent
                        listeners = self.listener_store.get_intent_listeners_for_intent(
                            intent
                        )
                        if any(
                            listener.instance_uuid == inst.instance_uuid
                            for listener in listeners
                        ):
                            return [inst.instance_uuid]
        except Exception:
            # Be conservative on error and fall back to normal delivery
            pass

        # Fallback
        return self.deliver_intent_event(intent, context, originating_app)
