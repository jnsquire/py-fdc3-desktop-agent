"""Factory for selecting a distributed log adapter implementation.

Environment variable `FDC3_DISTRIBUTED_ADAPTER` controls the adapter:
- "etcd" -> tries to import `etcd_adapter.EtcdAdapter`
- "consul" -> tries to import `consul_adapter.ConsulAdapter`
- anything else or unset -> returns a Noop adapter (no-op)

This keeps optional dependencies optional and centralizes adapter selection.
"""

from __future__ import annotations

import os
from .adapter import DistributedLogAdapter


class NoopAdapter(DistributedLogAdapter):
    async def start(self) -> None:
        return

    async def stop(self) -> None:
        return

    async def publish(self, topic: str, message) -> None:
        return

    async def subscribe(self, topic: str, callback):
        return "noop"

    async def unsubscribe(self, subscription_id: str) -> None:
        return


def get_adapter() -> DistributedLogAdapter:
    mode = os.getenv("FDC3_DISTRIBUTED_ADAPTER", "noop").lower()
    if mode == "etcd":
        try:
            from .etcd_adapter import EtcdAdapter
            return EtcdAdapter()
        except Exception:
            return NoopAdapter()
    if mode == "consul":
        try:
            from .consul_adapter import ConsulAdapter
            return ConsulAdapter()
        except Exception:
            return NoopAdapter()

    return NoopAdapter()
