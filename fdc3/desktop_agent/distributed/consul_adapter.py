"""Consul-backed distributed log adapter (prototype).

This adapter uses Consul KV as a simple append log and long-polling to
watch for new keys. Requires `aiohttp` to be installed for async HTTP calls.

Note: This is a lightweight prototype and not optimized for heavy workloads.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Callable, Dict, Optional

from .adapter import DistributedLogAdapter

try:
    import aiohttp
except Exception:  # pragma: no cover - optional dependency
    aiohttp = None


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
        self._subscription_counter = 0

    async def start(self) -> None:
        if self._session is None:
            self._session = aiohttp.ClientSession()

    async def stop(self) -> None:
        for task in list(self._watch_tasks.values()):
            task.cancel()
        self._watch_tasks.clear()
        if self._session:
            await self._session.close()

    async def publish(self, topic: str, message: Any) -> None:
        key = f"{self.base}/{topic}/{uuid.uuid4().hex}"
        val = json.dumps(message)
        assert self._session is not None, "ConsulAdapter not started"
        async with self._session.put(key, data=val) as resp:
            await resp.text()

    async def subscribe(self, topic: str, callback: Callable[[dict], None]) -> str:
        assert self._session is not None, "ConsulAdapter not started"
        topic_prefix = f"{self.base}/{topic}/"
        sub_id = f"consul-sub-{self._subscription_counter}"
        self._subscription_counter += 1

        async def _watch_loop():
            # Simple blocking query using index parameter
            idx = None
            while True:
                params = {"recurse": "true", "wait": "300s"}
                if idx is not None:
                    params["index"] = str(idx)
                try:
                    async with self._session.get(topic_prefix, params=params) as resp:
                        if resp.status == 200:
                            body = await resp.json()
                            # Update index from headers if present
                            hdr = resp.headers.get("X-Consul-Index")
                            if hdr:
                                idx = hdr
                            for item in body:
                                try:
                                    value = item.get("Value")
                                    if value is None:
                                        continue
                                    # Consul KV returns base64-encoded values; aiohttp json decoder may decode already
                                    data = (
                                        json.loads(value)
                                        if isinstance(value, str)
                                        else value
                                    )
                                except Exception:
                                    data = {"raw": item}
                                try:
                                    callback(data)
                                except Exception:
                                    pass
                        else:
                            await asyncio.sleep(1)
                except asyncio.CancelledError:
                    return
                except Exception:
                    await asyncio.sleep(1)

        task = asyncio.create_task(_watch_loop())
        self._watch_tasks[sub_id] = task
        return sub_id

    async def unsubscribe(self, subscription_id: str) -> None:
        task = self._watch_tasks.pop(subscription_id, None)
        if task:
            task.cancel()
