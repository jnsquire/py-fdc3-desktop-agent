"""Distributed log adapter interface.

Adapters implement a small async API used by the application to publish
and subscribe to cross-worker events.

Adapters should document required third-party dependencies and raise
informative ImportError when those dependencies are missing.
"""

from __future__ import annotations
from fdc3.desktop_agent.core.channel_types import ChannelEvent

from abc import ABC, abstractmethod
from typing import Callable


class DistributedLogAdapter(ABC):
    """Abstract interface for distributed log backends."""

    @abstractmethod
    async def start(self) -> None:
        """Start any background tasks or connections."""
        raise NotImplementedError()

    @abstractmethod
    async def stop(self) -> None:
        """Stop background tasks and close connections."""
        raise NotImplementedError()

    @abstractmethod
    async def publish(self, topic: str, message: ChannelEvent) -> None:
        """Publish a message to a topic/stream."""
        raise NotImplementedError()

    @abstractmethod
    async def subscribe(
        self, topic: str, callback: Callable[[ChannelEvent], None]
    ) -> str:
        """Subscribe to topic events.

        Returns a subscription id which can be used with `unsubscribe`.
        Callback is invoked with a dict event payload.
        """
        raise NotImplementedError()

    @abstractmethod
    async def unsubscribe(self, subscription_id: str) -> None:
        """Unsubscribe from a previously created subscription."""
        raise NotImplementedError()
