"""etcd-backed distributed log adapter (prototype).

Requires `etcd3aio` to be installed. This module implements a simple
append-only log using etcd keys under a prefix and uses etcd watch
to stream new entries to subscribers.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Callable, Dict

from .adapter import DistributedLogAdapter

try:
    import etcd3aio
except Exception:  # pragma: no cover - optional dependency
    etcd3aio = None


class EtcdAdapter(DistributedLogAdapter):
    def __init__(self, host: str = "127.0.0.1", port: int = 2379, prefix: str = "/fdc3/logs"):
        if etcd3aio is None:
            raise ImportError("etcd3aio is required for EtcdAdapter - install via 'pip install etcd3aio'")

        self.client = etcd3aio.client(host=host, port=port)
        self.prefix = prefix.rstrip("/")
        self._watch_tasks: Dict[str, asyncio.Task] = {}
        self._subscription_counter = 0

    async def start(self) -> None:
        # etcd3aio client establishes connections lazily
        return None

    async def stop(self) -> None:
        for task in list(self._watch_tasks.values()):
            task.cancel()
        self._watch_tasks.clear()
        # close client if supported
        close = getattr(self.client, "close", None)
        if callable(close):
            await close()

    async def publish(self, topic: str, message: Any) -> None:
        key = f"{self.prefix}/{topic}/{uuid.uuid4().hex}"
        value = json.dumps(message)
        await self.client.put(key, value)

    async def subscribe(self, topic: str, callback: Callable[[dict], None]) -> str:
        """Start a background watch for topic prefix and call callback for new entries."""
        prefix = f"{self.prefix}/{topic}/"

        def _on_event(event):
            # etcd3aio watch callback receives events; adapt to our simple payload
            try:
                val = event.events[0].value if hasattr(event, "events") and event.events else None
                if val is None:
                    return
                data = json.loads(val)
            except Exception:
                data = {"raw": getattr(event, "events", str(event))}
            try:
                callback(data)
            except Exception:
                # swallow exceptions from user callback
                return

        watch_id = f"etcd-sub-{self._subscription_counter}"
        self._subscription_counter += 1

        # etcd3aio exposes watch_prefix as coroutine that returns a watch_id and takes callback
        t = asyncio.create_task(self.client.watch_prefix(prefix, _on_event))
        self._watch_tasks[watch_id] = t
        return watch_id

    async def unsubscribe(self, subscription_id: str) -> None:
        task = self._watch_tasks.pop(subscription_id, None)
        if task:
            task.cancel()
