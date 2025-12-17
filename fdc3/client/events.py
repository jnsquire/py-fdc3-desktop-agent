"""Small async event emitter utility for client handlers.

Provides a single flexible `EventEmitter` which accepts async handlers
and invokes them in registration order. Handlers may accept a single
payload argument or arbitrary `*args`/`**kwargs`. Exceptions in one
handler do not prevent other handlers from running.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Awaitable, Callable, Generic, List, TypeVar, Union

logger = logging.getLogger(__name__)


# Payload type variable
T = TypeVar("T")


# Handler type: sync or async callable that accepts a single payload arg
Handler = Callable[[T], Union[Awaitable[Any], Any]]


class EventEmitter(Generic[T]):
    """Event emitter for handlers that may be async or sync.

    Handlers should accept a single payload argument of type `T`.
    They may be sync functions or async coroutines; awaitable results
    will be awaited.
    """

    def __init__(self) -> None:
        self._handlers: List[Handler] = []

    def add(self, handler: Handler) -> None:
        if handler not in self._handlers:
            self._handlers.append(handler)

    def remove(self, handler: Handler) -> None:
        try:
            self._handlers.remove(handler)
        except ValueError:
            pass

    async def emit(self, payload: T) -> None:
        for h in list(self._handlers):
            try:
                result = h(payload)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("Event handler raised an exception")

    def __len__(self) -> int:
        return len(self._handlers)
