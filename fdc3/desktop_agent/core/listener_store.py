from typing import Dict, List, Set, Optional
from ..api import ListenerUuid


class ContextListener:
    def __init__(
        self,
        listener_uuid: ListenerUuid,
        instance_uuid: str,
        context_type: Optional[str] = None,
    ):
        self.listener_uuid = listener_uuid
        self.instance_uuid = instance_uuid
        self.context_type = context_type


class IntentListener:
    def __init__(self, listener_uuid: ListenerUuid, instance_uuid: str, intent: str):
        self.listener_uuid = listener_uuid
        self.instance_uuid = instance_uuid
        self.intent = intent


class ListenerStore:
    """Manages context listeners, intent listeners, and event listeners."""

    def __init__(self):
        self.context_listeners: Dict[str, ContextListener] = {}
        self.intent_listeners: Dict[str, IntentListener] = {}
        self.listeners_by_instance: Dict[
            str, Set[str]
        ] = {}  # instance_uuid -> set of listener_uuids

    def add_context_listener(
        self,
        listener_uuid: ListenerUuid,
        instance_uuid: str,
        context_type: Optional[str] = None,
    ) -> ContextListener:
        listener = ContextListener(listener_uuid, instance_uuid, context_type)
        self.context_listeners[listener_uuid.root] = listener
        if instance_uuid not in self.listeners_by_instance:
            self.listeners_by_instance[instance_uuid] = set()
        self.listeners_by_instance[instance_uuid].add(listener_uuid.root)
        return listener

    def add_intent_listener(
        self, listener_uuid: ListenerUuid, instance_uuid: str, intent: str
    ) -> IntentListener:
        listener = IntentListener(listener_uuid, instance_uuid, intent)
        self.intent_listeners[listener_uuid.root] = listener
        if instance_uuid not in self.listeners_by_instance:
            self.listeners_by_instance[instance_uuid] = set()
        self.listeners_by_instance[instance_uuid].add(listener_uuid.root)
        return listener

    def remove_listener(self, listener_uuid: str):
        if listener_uuid in self.context_listeners:
            instance_uuid = self.context_listeners[listener_uuid].instance_uuid
            del self.context_listeners[listener_uuid]
            if instance_uuid in self.listeners_by_instance:
                self.listeners_by_instance[instance_uuid].discard(listener_uuid)
        elif listener_uuid in self.intent_listeners:
            instance_uuid = self.intent_listeners[listener_uuid].instance_uuid
            del self.intent_listeners[listener_uuid]
            if instance_uuid in self.listeners_by_instance:
                self.listeners_by_instance[instance_uuid].discard(listener_uuid)

    def get_context_listeners(
        self, context_type: Optional[str] = None
    ) -> List[ContextListener]:
        """Get all context listeners, optionally filtered by context type."""
        listeners = list(self.context_listeners.values())
        if context_type is not None:
            listeners = [
                listener
                for listener in listeners
                if listener.context_type == context_type
                or listener.context_type is None
            ]
        return listeners

    def get_intent_listeners(self, intent: str) -> List[IntentListener]:
        """Get all intent listeners for a specific intent."""
        return [
            listener
            for listener in self.intent_listeners.values()
            if listener.intent == intent
        ]

    def remove_listeners_for_instance(self, instance_uuid: str):
        """Remove all listeners for a specific instance."""
        if instance_uuid in self.listeners_by_instance:
            listener_uuids = self.listeners_by_instance[instance_uuid].copy()
            for listener_uuid in listener_uuids:
                self.remove_listener(listener_uuid)
            del self.listeners_by_instance[instance_uuid]

    def get_context_listeners_for_type(
        self, context_type: Optional[str] = None
    ) -> List[ContextListener]:
        if context_type:
            return [
                listener
                for listener in self.context_listeners.values()
                if listener.context_type == context_type
                or listener.context_type is None
            ]
        return list(self.context_listeners.values())

    def get_intent_listeners_for_intent(self, intent: str) -> List[IntentListener]:
        return [
            listener
            for listener in self.intent_listeners.values()
            if listener.intent == intent
        ]
