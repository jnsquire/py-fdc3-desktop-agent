"""Runtime utilities for the desktop agent.

This module contains small helpers used by the running agent.

Developer workflow entry points (e.g. `check-style`, `install-git-hooks`)
live in `fdc3.desktop_agent.devtools`.
"""

from __future__ import annotations

from typing import Any, Coroutine
import asyncio
import logging

logger = logging.getLogger(__name__)


# Backward-compatible re-exports (dev tooling was moved to devtools.py)
from .devtools import install_git_hooks, prepush, run_pytest  # noqa: E402,F401


def create_task_safe(
    coro: Coroutine[Any, Any, Any], *, name: str | None = None
) -> asyncio.Task[Any]:
    """Create an asyncio.Task and log uncaught exceptions.

    Use this helper for fire-and-forget background tasks so exceptions are
    surfaced to the logger instead of being silently dropped.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop; fallback to creating task on default loop
        loop = asyncio.get_event_loop()

    task = loop.create_task(coro)

    def _on_done(t: asyncio.Task[Any]) -> None:
        try:
            exc = t.exception()
            if exc is not None:
                logger.exception("Background task raised an exception", exc_info=exc)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Error retrieving task exception")

    task.add_done_callback(_on_done)
    return task


async def yield_once() -> None:
    """Yield control to the event loop exactly once.

    This is a sleep-free alternative to `await asyncio.sleep(0)` or
    `await asyncio.sleep(0.01)` when the intent is simply to allow pending
    callbacks/transports to finalize.
    """
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    loop.call_soon(fut.set_result, None)
    await fut
