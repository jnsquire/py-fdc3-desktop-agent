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
        import importlib

        # Try new and legacy module paths so tests and external code that
        # reference the old package name continue to work during migration.
        candidates = [
            "fdc3.desktop_agent.distributed.etcd_adapter",
            "fdc3_desktop_agent.distributed.etcd_adapter",
        ]
        for mod_name in candidates:
            try:
                mod = importlib.import_module(mod_name)
                EtcdAdapter = getattr(mod, "EtcdAdapter")
                return EtcdAdapter()
            except Exception:
                continue
        # Last resort: relative import (within this package)
        try:
            from .etcd_adapter import EtcdAdapter

            return EtcdAdapter()
        except Exception:
            return NoopAdapter()
    if mode == "consul":
        import importlib

        candidates = [
            "fdc3.desktop_agent.distributed.consul_adapter",
            "fdc3_desktop_agent.distributed.consul_adapter",
        ]
        for mod_name in candidates:
            try:
                mod = importlib.import_module(mod_name)
                ConsulAdapter = getattr(mod, "ConsulAdapter")
                return ConsulAdapter()
            except Exception:
                continue
        try:
            from .consul_adapter import ConsulAdapter

            return ConsulAdapter()
        except Exception:
            return NoopAdapter()

    return NoopAdapter()
