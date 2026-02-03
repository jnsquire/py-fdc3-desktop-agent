from __future__ import annotations

from typing import Dict, List, Optional, Set

from fdc3.models.primitives import ListenerUuid


from dataclasses import dataclass


@dataclass(frozen=True)
class ContextListener:
    listener_uuid: ListenerUuid
    instance_uuid: str
    context_type: Optional[str] = None
    channel_id: Optional[str] = None


@dataclass(frozen=True)
class IntentListener:
    listener_uuid: ListenerUuid
    instance_uuid: str
    intent: str


@dataclass(frozen=True)
class EventListener:
    listener_uuid: ListenerUuid
    instance_uuid: str
    event_type: str | None
    channel_id: Optional[str] = None


class ListenerStore:
    """Manages context listeners and intent listeners.

    This class keeps track of registered listeners and provides helper methods
    to add, remove and query them. Listener objects are lightweight frozen
    dataclasses which makes them cheap to copy and safe to use as dict values.
    """

    def __init__(self):
        self.context_listeners: Dict[str, ContextListener] = {}
        self.intent_listeners: Dict[str, IntentListener] = {}
        self.event_listeners: Dict[str, EventListener] = {}
        self.listeners_by_instance: Dict[str, Set[str]] = {}

    def _register_instance(
        self, listener_uuid: ListenerUuid, instance_uuid: str
    ) -> str:
        """Record the listener under the instance and return the listener key."""
        key = listener_uuid.root
        self.listeners_by_instance.setdefault(instance_uuid, set()).add(key)
        return key

    def add_context_listener(
        self,
        listener_uuid: ListenerUuid,
        instance_uuid: str,
        context_type: Optional[str] = None,
        channel_id: Optional[str] = None,
    ) -> ContextListener:
        listener = ContextListener(
            listener_uuid, instance_uuid, context_type, channel_id
        )
        key = self._register_instance(listener_uuid, instance_uuid)
        self.context_listeners[key] = listener
        return listener

    def add_intent_listener(
        self, listener_uuid: ListenerUuid, instance_uuid: str, intent: str
    ) -> IntentListener:
        listener = IntentListener(listener_uuid, instance_uuid, intent)
        key = self._register_instance(listener_uuid, instance_uuid)
        self.intent_listeners[key] = listener
        return listener

    def add_event_listener(
        self,
        listener_uuid: ListenerUuid,
        instance_uuid: str,
        event_type: str | None,
        channel_id: Optional[str] = None,
    ) -> EventListener:
        listener = EventListener(listener_uuid, instance_uuid, event_type, channel_id)
        key = self._register_instance(listener_uuid, instance_uuid)
        self.event_listeners[key] = listener
        return listener

    def remove_listener(
        self, listener_uuid: str | ListenerUuid
    ) -> ContextListener | IntentListener | EventListener | None:
        """Remove and return a listener given its UUID (or ListenerUuid).

        Accepts either the listener root string or a ListenerUuid object for
        convenience. Returns the removed listener object or None if not found.
        """
        if isinstance(listener_uuid, ListenerUuid):
            key = listener_uuid.root
        else:
            key = listener_uuid

        listener: ContextListener | IntentListener | EventListener | None = None
        instance_uuid: str | None = None

        if key in self.context_listeners:
            listener = self.context_listeners.pop(key)
            instance_uuid = listener.instance_uuid
        elif key in self.intent_listeners:
            listener = self.intent_listeners.pop(key)
            instance_uuid = listener.instance_uuid
        elif key in self.event_listeners:
            listener = self.event_listeners.pop(key)
            instance_uuid = listener.instance_uuid
        else:
            return None

        if instance_uuid and instance_uuid in self.listeners_by_instance:
            self.listeners_by_instance[instance_uuid].discard(key)
            if not self.listeners_by_instance[instance_uuid]:
                del self.listeners_by_instance[instance_uuid]

        return listener

    def get_context_listeners(
        self,
        context_type: Optional[str] = None,
        *,
        channel_id: Optional[str] = None,
        include_global: bool = True,
    ) -> List[ContextListener]:
        listeners = list(self.context_listeners.values())
        if context_type is not None:
            listeners = [
                listener
                for listener in listeners
                if listener.context_type == context_type
                or listener.context_type is None
            ]

        if channel_id is None:
            return listeners

        filtered_listeners: List[ContextListener] = []
        for listener in listeners:
            if listener.channel_id == channel_id:
                filtered_listeners.append(listener)
            elif include_global and listener.channel_id is None:
                filtered_listeners.append(listener)
        return filtered_listeners

    def get_intent_listeners(self, intent: str) -> List[IntentListener]:
        return [
            listener
            for listener in self.intent_listeners.values()
            if listener.intent == intent
        ]

    def get_event_listeners(
        self,
        event_type: str,
        *,
        instance_uuid: Optional[str] = None,
        channel_id: Optional[str] = None,
    ) -> List[EventListener]:
        listeners = [
            listener
            for listener in self.event_listeners.values()
            if listener.event_type is None or listener.event_type == event_type
        ]

        if instance_uuid is not None:
            listeners = [
                listener
                for listener in listeners
                if listener.instance_uuid == instance_uuid
            ]

        if channel_id is not None:
            listeners = [
                listener for listener in listeners if listener.channel_id == channel_id
            ]

        return listeners

    def remove_listeners_for_instance(self, instance_uuid: str) -> None:
        listener_uuids = self.listeners_by_instance.get(instance_uuid)
        if not listener_uuids:
            return

        for listener_uuid in list(listener_uuids):
            self.remove_listener(listener_uuid)

    def get_context_listeners_for_type(
        self,
        context_type: Optional[str] = None,
        *,
        channel_id: Optional[str] = None,
        include_global: bool = True,
    ) -> List[ContextListener]:
        return self.get_context_listeners(
            context_type, channel_id=channel_id, include_global=include_global
        )

    def get_intent_listeners_for_intent(self, intent: str) -> List[IntentListener]:
        return self.get_intent_listeners(intent)
