"""Registry for external process intent handlers."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class ExternalHandler:
    handler_uuid: str
    instance_uuid: str
    handler_id: str
    intents: List[str]
    priority: int = 0
    metadata: Optional[Dict[str, Any]] = None


class ExternalHandlerRegistry:
    """Manage external handlers registered by separate processes.

    Handlers are indexed by handler_uuid and by intent name for quick lookup.
    """

    def __init__(self):
        self._handlers: Dict[str, ExternalHandler] = {}
        self._intent_map: Dict[str, List[ExternalHandler]] = {}

    def register(
        self,
        instance_uuid: str,
        handler_id: str,
        intents: List[str],
        priority: int = 0,
        metadata: Optional[Dict] = None,
    ) -> str:
        handler_uuid = str(uuid.uuid4())
        handler = ExternalHandler(
            handler_uuid=handler_uuid,
            instance_uuid=instance_uuid,
            handler_id=handler_id,
            intents=list(intents),
            priority=priority,
            metadata=metadata,
        )
        self._handlers[handler_uuid] = handler

        for intent in handler.intents:
            self._intent_map.setdefault(intent, []).append(handler)
            # sort by priority desc
            self._intent_map[intent].sort(key=lambda h: h.priority, reverse=True)

        logger.info(
            f"Registered external handler {handler_id} ({handler_uuid}) for intents: {handler.intents}"
        )
        return handler_uuid

    def unregister(self, handler_uuid: str) -> None:
        handler = self._handlers.pop(handler_uuid, None)
        if not handler:
            logger.debug(f"Attempted to unregister unknown handler {handler_uuid}")
            return

        for intent in handler.intents:
            if intent in self._intent_map:
                self._intent_map[intent] = [
                    h
                    for h in self._intent_map[intent]
                    if h.handler_uuid != handler_uuid
                ]
                if not self._intent_map[intent]:
                    del self._intent_map[intent]

        logger.info(
            f"Unregistered external handler {handler.handler_id} ({handler_uuid})"
        )

    def get_handlers_for_intent(self, intent: str) -> List[ExternalHandler]:
        return list(self._intent_map.get(intent, []))

    def unregister_by_instance(self, instance_uuid: str) -> None:
        # Remove all handlers associated with a disconnected instance
        to_remove = [
            h.handler_uuid
            for h in self._handlers.values()
            if h.instance_uuid == instance_uuid
        ]
        for hu in to_remove:
            self.unregister(hu)

    def list_handlers(self) -> List[ExternalHandler]:
        return list(self._handlers.values())
