"""etcd-backed distributed log adapter (prototype).

This adapter prefers an HTTP gateway client (`etcd3gw`) and falls back
to the sync `etcd3` client. It implements a simple append-only log
using etcd keys under a prefix and uses etcd watch to stream new
entries to subscribers.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Callable, Dict, Optional

from .adapter import DistributedLogAdapter

try:
    # prefer etcd3gw (HTTP gateway client)
    from etcd3gw import client as _etcd3gw_client # pyright: ignore[reportMissingImports]

    _GW_ETCD = True
except Exception:
    _etcd3gw_client = None
    _GW_ETCD = False

try:
    import etcd3 as _etcd3  # pyright: ignore[reportMissingImports] # sync etcd client fallback
except Exception:  # pragma: no cover - optional dependency
    _etcd3 = None


class EtcdAdapter(DistributedLogAdapter):
    def __init__(
        self, host: str = "127.0.0.1", port: int = 2379, prefix: str = "/fdc3/logs"
    ):
        # Prefer etcd3gw (HTTP gateway) when available, otherwise try async or sync clients.
        if _GW_ETCD and _etcd3gw_client is not None:
            self._mode = "gw"
            # etcd3gw.client.client returns an Etcd3Client instance
            self.client = _etcd3gw_client.client(host=host, port=port)
        elif _etcd3 is not None:
            self._mode = "sync"
            self.client = _etcd3.client(host=host, port=port)
        else:
            raise ImportError(
                "One of etcd3gw or etcd3 is required for EtcdAdapter - install one via pip"
            )
        self.prefix = prefix.rstrip("/")
        # Values may be asyncio.Task, a cancel callable, or None (gateway iterator)
        self._watch_tasks: Dict[str, Optional[Any]] = {}
        self._subscription_counter = 0

    async def start(self) -> None:
        # No async client to initialize here; nothing to do for start.
        return None

    async def stop(self) -> None:
        # Cancel background watch tasks or call cancel functions as appropriate
        for task in list(self._watch_tasks.values()):
            try:
                if callable(task):
                    try:
                        task()
                    except Exception:
                        pass
                else:
                    try:
                        task.cancel()
                    except Exception:
                        pass
            except Exception:
                pass
        self._watch_tasks.clear()
        # close client if supported
        close = getattr(self.client, "close", None)
        if callable(close):
            # sync clients (including gateway) run blocking close operations
            await asyncio.to_thread(close)

    async def publish(self, topic: str, message: Any) -> None:
        key = f"{self.prefix}/{topic}/{uuid.uuid4().hex}"
        value = json.dumps(message)
        # Both gateway and sync clients perform blocking operations; run in thread
        await asyncio.to_thread(self.client.put, key, value)

    async def subscribe(self, topic: str, callback: Callable[[dict], None]) -> str:
        """Start a background watch for topic prefix and call callback for new entries."""
        prefix = f"{self.prefix}/{topic}/"

        def _on_event_sync(event):
            # sync etcd3 event adaptation
            try:
                val = None
                if hasattr(event, "events") and event.events:
                    try:
                        # etcd3 sync events may expose kv.value
                        ev = event.events[0]
                        val = getattr(ev, "kv", None)
                        if val is not None:
                            val = getattr(ev.kv, "value", None)
                    except Exception:
                        val = None
                if val is None and hasattr(event, "value"):
                    val = event.value
                if val is None:
                    return
                try:
                    data = json.loads(val)
                except Exception:
                    data = {"raw": str(val)}
            except Exception:
                data = {"raw": str(event)}
            try:
                # ensure callback runs on the asyncio event loop
                try:
                    loop = asyncio.get_running_loop()
                    loop.call_soon_threadsafe(callback, data)
                except RuntimeError:
                    # no running loop in this thread; schedule on default loop
                    asyncio.get_event_loop().call_soon_threadsafe(callback, data)
            except Exception:
                return

        watch_id = f"etcd-sub-{self._subscription_counter}"
        self._subscription_counter += 1

        if self._mode == "gw":
            # etcd3gw.watch_prefix returns (events_iterator, cancel) or similar
            def _blocking_watch_gw():
                try:
                    result = self.client.watch_prefix(prefix)
                    # result may be (events_iterator, cancel) or an iterator
                    events_iter = None
                    cancel = None
                    if isinstance(result, tuple) and len(result) >= 1:
                        events_iter = result[0]
                        if len(result) > 1:
                            cancel = result[1]
                    else:
                        events_iter = result

                    if cancel is not None:
                        # store cancel callable to allow unsubscribe
                        self._watch_tasks[watch_id] = cancel
                    else:
                        # otherwise store nothing yet and iterate
                        self._watch_tasks[watch_id] = None

                    if events_iter is not None:
                        for ev in events_iter:
                            _on_event_sync(ev)
                except Exception:
                    pass

            t = asyncio.create_task(asyncio.to_thread(_blocking_watch_gw))
            self._watch_tasks[watch_id] = t
            return watch_id
        else:
            # sync etcd3 client
            add_watch = getattr(self.client, "add_watch_prefix_callback", None)
            if callable(add_watch):
                try:
                    cancel = add_watch(prefix, _on_event_sync)
                    self._watch_tasks[watch_id] = cancel
                    return watch_id
                except Exception:
                    pass

            def _blocking_watch():
                try:
                    for ev in self.client.watch_prefix(prefix):
                        _on_event_sync(ev)
                except Exception:
                    pass

            t = asyncio.create_task(asyncio.to_thread(_blocking_watch))
            self._watch_tasks[watch_id] = t
            return watch_id

    async def unsubscribe(self, subscription_id: str) -> None:
        task = self._watch_tasks.pop(subscription_id, None)
        if not task:
            return
        try:
            if callable(task):
                try:
                    task()
                except Exception:
                    pass
            else:
                try:
                    task.cancel()
                except Exception:
                    pass
        except Exception:
            pass
