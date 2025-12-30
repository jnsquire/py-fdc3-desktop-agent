"""Consul-backed distributed log adapter (prototype).

This adapter uses Consul KV as a simple append log and long-polling to
watch for new keys. Requires `aiohttp` to be installed for async HTTP calls.

Note: This is a lightweight prototype and not optimized for heavy workloads.
"""

from __future__ import annotations

import asyncio
import threading
import json
import uuid
import logging
from typing import Any, Callable, Dict, Optional, Set

from .adapter import DistributedLogAdapter

try:
    import aiohttp  # type:ignore[unresolved-import]
except Exception:  # pragma: no cover - optional dependency
    aiohttp = None

logger = logging.getLogger(__name__)


class ConsulAdapter(DistributedLogAdapter):
    def __init__(
        self, host: str = "127.0.0.1", port: int = 8500, prefix: str = "fdc3/logs"
    ):
        if aiohttp is None:
            raise ImportError(
                "aiohttp is required for ConsulAdapter - install via 'pip install aiohttp'"
            )

        self.base = f"http://{host}:{port}/v1/kv/{prefix.rstrip('/')}"
        self._session: Optional[aiohttp.ClientSession] = None
        self._watch_tasks: Dict[str, asyncio.Task] = {}
        self._watch_tasks_lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._subscription_counter = 0

    async def start(self) -> None:
        if self._session is None:
            self._session = aiohttp.ClientSession()  # type: ignore[assignment]
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    async def stop(self) -> None:
        # Cancel and await pending watch tasks
        tasks = list(self._watch_tasks.values())
        for task in tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Error while waiting for Consul watch task to finish")
        self._watch_tasks.clear()
        if self._session:
            await self._session.close()

    async def publish(self, topic: str, message: Any) -> None:
        key = f"{self.base}/{topic}/{uuid.uuid4().hex}"
        val = json.dumps(message)
        assert self._session is not None, "ConsulAdapter not started"
        async with self._session.put(key, data=val) as resp:
            await resp.text()

    def _get_target_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """Get the target event loop for callback scheduling."""
        target_loop = self._loop
        if target_loop is None:
            try:
                target_loop = asyncio.get_running_loop()
            except RuntimeError:
                target_loop = None
        return target_loop

    def _invoke_callback(
        self,
        callback: Callable[[dict], None],
        data: dict,
        target_loop: Optional[asyncio.AbstractEventLoop],
    ) -> None:
        """Invoke callback, scheduling any returned coroutine on the target loop."""
        try:
            res = callback(data)
            if asyncio.iscoroutine(res):
                if target_loop is not None:
                    target_loop.create_task(res)
                else:
                    asyncio.create_task(res)
        except Exception:
            logger.exception("ConsulAdapter callback raised an exception")

    def _schedule_callback(
        self,
        callback: Callable[[dict], None],
        data: dict,
        target_loop: Optional[asyncio.AbstractEventLoop],
    ) -> None:
        """Schedule callback execution on the appropriate event loop."""

        def _invoke():
            self._invoke_callback(callback, data, target_loop)

        if target_loop is not None:
            try:
                target_loop.call_soon_threadsafe(_invoke)
            except Exception:
                logger.exception(
                    "Failed to schedule ConsulAdapter callback on loop, invoking directly"
                )
                _invoke()
        else:
            _invoke()

    def _parse_consul_item(self, item: dict) -> Optional[dict]:
        """Parse a Consul KV item and return the decoded data, or None if invalid."""
        try:
            value = item.get("Value")
            if value is None:
                return None
            # Consul KV returns base64-encoded values; aiohttp json decoder may decode already
            return json.loads(value) if isinstance(value, str) else value
        except Exception:
            return {"raw": item}

    async def _process_watch_response(
        self,
        body: list,
        callback: Callable[[dict], None],
        seen_keys: Set[str],
    ) -> None:
        """Process items from a Consul watch response."""
        target_loop = self._get_target_loop()

        for item in body:
            key = item.get("Key")
            if key in seen_keys:
                continue

            data = self._parse_consul_item(item)
            if data is None:
                continue

            try:
                self._schedule_callback(callback, data, target_loop)
                if key is not None:
                    seen_keys.add(key)
            except Exception:
                logger.exception("Error invoking callback for consul watch")

    async def _watch_loop(
        self,
        topic_prefix: str,
        callback: Callable[[dict], None],
    ) -> None:
        """Long-polling watch loop for Consul KV changes."""
        idx = None
        seen_keys: Set[str] = set()

        while True:
            params: Dict[str, str] = {"recurse": "true", "wait": "300s"}
            if idx is not None:
                params["index"] = str(idx)

            try:
                async with self._session.get(topic_prefix, params=params) as resp:  # type: ignore[union-attr]
                    if resp.status != 200:
                        logger.warning(
                            "Consul responded with status %s for prefix %s",
                            resp.status,
                            topic_prefix,
                        )
                        await asyncio.sleep(1)
                        continue

                    body = await resp.json()

                    # Update index from headers if present
                    hdr = resp.headers.get("X-Consul-Index")
                    if hdr:
                        try:
                            idx = int(hdr)
                        except Exception:
                            idx = hdr

                    await self._process_watch_response(body, callback, seen_keys)

            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Error in Consul watch loop, backing off briefly")
                await asyncio.sleep(1)

    async def subscribe(self, topic: str, callback: Callable[[dict], None]) -> str:
        assert self._session is not None, "ConsulAdapter not started"
        topic_prefix = f"{self.base}/{topic}/"
        sub_id = f"consul-sub-{self._subscription_counter}"
        self._subscription_counter += 1

        from ..tools import create_task_safe

        task = create_task_safe(self._watch_loop(topic_prefix, callback))
        with self._watch_tasks_lock:
            self._watch_tasks[sub_id] = task
        return sub_id

    async def unsubscribe(self, subscription_id: str) -> None:
        with self._watch_tasks_lock:
            task = self._watch_tasks.pop(subscription_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass  # Expected when cancelling the watch task
            except Exception:
                logger.exception(
                    "Error while waiting for unsubscribed Consul watch task to finish"
                )
