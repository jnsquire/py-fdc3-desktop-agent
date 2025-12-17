from __future__ import annotations

from typing import Dict, List, Optional, Set

from fdc3.models.primitives import ListenerUuid


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
    """Manages context listeners and intent listeners."""

    def __init__(self):
        self.context_listeners: Dict[str, ContextListener] = {}
        self.intent_listeners: Dict[str, IntentListener] = {}
        self.listeners_by_instance: Dict[str, Set[str]] = {}

    def add_context_listener(
        self,
        listener_uuid: ListenerUuid,
        instance_uuid: str,
        context_type: Optional[str] = None,
    ) -> ContextListener:
        listener = ContextListener(listener_uuid, instance_uuid, context_type)
        self.context_listeners[listener_uuid.root] = listener
        self.listeners_by_instance.setdefault(instance_uuid, set()).add(
            listener_uuid.root
        )
        return listener

    def add_intent_listener(
        self, listener_uuid: ListenerUuid, instance_uuid: str, intent: str
    ) -> IntentListener:
        listener = IntentListener(listener_uuid, instance_uuid, intent)
        self.intent_listeners[listener_uuid.root] = listener
        self.listeners_by_instance.setdefault(instance_uuid, set()).add(
            listener_uuid.root
        )
        return listener

    def remove_listener(self, listener_uuid: str) -> None:
        if listener_uuid in self.context_listeners:
            instance_uuid = self.context_listeners[listener_uuid].instance_uuid
            del self.context_listeners[listener_uuid]
        elif listener_uuid in self.intent_listeners:
            instance_uuid = self.intent_listeners[listener_uuid].instance_uuid
            del self.intent_listeners[listener_uuid]
        else:
            return

        if instance_uuid in self.listeners_by_instance:
            self.listeners_by_instance[instance_uuid].discard(listener_uuid)
            if not self.listeners_by_instance[instance_uuid]:
                del self.listeners_by_instance[instance_uuid]

    def get_context_listeners(
        self, context_type: Optional[str] = None
    ) -> List[ContextListener]:
        listeners = list(self.context_listeners.values())
        if context_type is None:
            return listeners
        return [
            listener
            for listener in listeners
            if listener.context_type == context_type or listener.context_type is None
        ]

    def get_intent_listeners(self, intent: str) -> List[IntentListener]:
        return [
            listener
            for listener in self.intent_listeners.values()
            if listener.intent == intent
        ]

    def remove_listeners_for_instance(self, instance_uuid: str) -> None:
        listener_uuids = self.listeners_by_instance.get(instance_uuid)
        if not listener_uuids:
            return

        for listener_uuid in list(listener_uuids):
            self.remove_listener(listener_uuid)

    def get_context_listeners_for_type(
        self, context_type: Optional[str] = None
    ) -> List[ContextListener]:
        return self.get_context_listeners(context_type)

    def get_intent_listeners_for_intent(self, intent: str) -> List[IntentListener]:
        return self.get_intent_listeners(intent)
