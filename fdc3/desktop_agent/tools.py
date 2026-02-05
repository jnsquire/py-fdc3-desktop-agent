"""Runtime utilities for the desktop agent.

This module contains small helpers used by the running agent.

Developer workflow entry points (e.g. `check-style`, `install-git-hooks`)
live in `fdc3.desktop_agent.devtools`.
"""

from __future__ import annotations

from typing import Any, Coroutine, TypeVar
import asyncio
import logging

logger = logging.getLogger(__name__)

T = TypeVar("T")


# Backward-compatible re-exports (dev tooling was moved to devtools.py)
from .devtools import install_git_hooks, prepush, run_pytest  # noqa: E402,F401


def create_task_safe(
    coro: Coroutine[Any, Any, T], *, name: str | None = None
) -> asyncio.Task[T]:
    """Create an asyncio.Task and log uncaught exceptions.

    Use this helper for fire-and-forget background tasks so exceptions are
    surfaced to the logger instead of being silently dropped.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop; fallback to creating task on default loop
        loop = asyncio.get_event_loop()

    task = loop.create_task(coro, name=name)

    def _on_done(t: asyncio.Task[T]) -> None:
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


async def cancel_task(
    task: asyncio.Task[Any] | None,
    *,
    label: str | None = None,
    logger_override: logging.Logger | None = None,
    raise_on_error: bool = False,
) -> None:
    """Cancel a task and await its completion.

    This helper ignores CancelledError and logs unexpected exceptions.
    """
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        log = logger_override or logger
        if label:
            log.exception("Error waiting for %s task cancellation", label)
        else:
            log.exception("Error waiting for task cancellation")
        if raise_on_error:
            raise


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
