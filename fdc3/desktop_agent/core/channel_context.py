from __future__ import annotations
import threading

import copy
from typing import Optional, Protocol

from fdc3.models.dacp.dacp import Fdc3Context


class _ChannelContextManager(Protocol):
    LAST_CONTEXT_KEY: str
    channel_contexts: dict[str, dict[str, Fdc3Context]]
    _lock: threading.RLock


def set_channel_context(
    manager: _ChannelContextManager, channel_id: str, context: Fdc3Context
) -> None:
    if not context or not isinstance(context, dict):
        return

    context_type = context.get("type")
    if not context_type:
        return

    with manager._lock:
        stored = manager.channel_contexts.setdefault(channel_id, {})
        sanitized = copy.deepcopy(context)
        stored[context_type] = sanitized
        stored[manager.LAST_CONTEXT_KEY] = sanitized


def get_channel_context(
    manager: _ChannelContextManager,
    channel_id: str,
    context_type: Optional[str] = None,
) -> Optional[Fdc3Context]:
    with manager._lock:
        contexts = manager.channel_contexts.get(channel_id)
        if not contexts:
            return None

        if context_type is not None:
            return contexts.get(context_type)
        return contexts.get(manager.LAST_CONTEXT_KEY)


def clear_channel_context(manager: _ChannelContextManager, channel_id: str) -> None:
    with manager._lock:
        manager.channel_contexts.pop(channel_id, None)
