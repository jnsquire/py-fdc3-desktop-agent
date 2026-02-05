from __future__ import annotations

import asyncio
import inspect
import json
import logging
from datetime import datetime
from typing import Optional, Protocol

from fdc3.models.dacp.dacp import Fdc3Context

from ..distributed.adapter import DistributedLogAdapter
from ..tools import create_task_safe
from .channel_types import ChannelEvent, EventSubscription

logger = logging.getLogger(__name__)


class _ChannelEventManager(Protocol):
    event_subscriptions: dict[str, EventSubscription]
    distributed_adapter: Optional[DistributedLogAdapter]


def emit_event(
    manager: _ChannelEventManager,
    event_type: str,
    channel_id: str,
    instance_uuid: Optional[str] = None,
    context: Optional[Fdc3Context] = None,
    remote: bool = False,
) -> None:
    """Emit an event to all subscribers."""
    event_data: ChannelEvent = {
        "event_type": event_type,
        "channel_id": channel_id,
        "instance_uuid": instance_uuid,
        "context": json.dumps(context) if context else None,
        "timestamp": datetime.now().isoformat(),
    }

    for subscription in manager.event_subscriptions.values():
        channel_filter = subscription["channel_filter"]
        if channel_filter is None or channel_filter == channel_id:
            try:
                result = subscription["callback"](event_data)
                if inspect.isawaitable(result):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(result)
                    except RuntimeError:
                        # No running loop in this thread; try thread-safe scheduling
                        try:
                            asyncio.get_event_loop().call_soon_threadsafe(
                                asyncio.create_task, result
                            )
                        except Exception:
                            if inspect.iscoroutine(result):
                                result.close()
                            logger.exception(
                                "Failed to schedule async channel callback"
                            )
            except Exception:
                logger.exception("Error in channel event callback")

    # Publish to distributed adapter for cross-worker delivery unless this event
    # originated from the distributed bus (avoid loops).
    if not remote and manager.distributed_adapter is not None:
        try:
            coro = publish_event(manager, event_data)
            try:
                create_task_safe(coro)
            except Exception:
                coro.close()
                raise
        except Exception:
            # Best-effort: do not break local emission if publishing fails
            logger.exception("Failed to schedule distributed publish task")


async def publish_event(
    manager: _ChannelEventManager, event_data: ChannelEvent
) -> None:
    try:
        adapter = manager.distributed_adapter
        if adapter:
            await adapter.publish("channel_events", event_data)
    except Exception:
        # Swallow errors - publishing is best-effort
        return
