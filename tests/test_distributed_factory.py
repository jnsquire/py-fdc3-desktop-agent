import sys
import types

import pytest

from fdc3.desktop_agent.distributed import factory
from fdc3.desktop_agent.distributed.adapter import DistributedLogAdapter


@pytest.mark.asyncio
async def test_get_adapter_default_noop(monkeypatch):
    monkeypatch.delenv("FDC3_DISTRIBUTED_ADAPTER", raising=False)
    adapter = factory.get_adapter()
    assert isinstance(adapter, DistributedLogAdapter)
    # Noop adapter methods should be awaitable and not raise
    await adapter.start()
    await adapter.publish("topic", {"a": 1})
    sub = await adapter.subscribe("topic", lambda *_: None)
    assert sub == "noop"
    await adapter.unsubscribe("noop")
    await adapter.stop()


@pytest.mark.asyncio
async def test_get_adapter_etcd_success(monkeypatch):
    # Create a fake etcd_adapter module with EtcdAdapter
    mod_name = "fdc3.desktop_agent.distributed.etcd_adapter"
    mod = types.ModuleType(mod_name)

    class FakeEtcd(DistributedLogAdapter):
        async def start(self):
            return

        async def stop(self):
            return

        async def publish(self, topic: str, message) -> None:
            return

        async def subscribe(self, topic: str, callback):
            return "etcd-sub"

        async def unsubscribe(self, subscription_id: str) -> None:
            return

    mod.EtcdAdapter = FakeEtcd  # pyright: ignore[reportAttributeAccessIssue]
    sys.modules[mod_name] = mod

    monkeypatch.setenv("FDC3_DISTRIBUTED_ADAPTER", "etcd")
    adapter = factory.get_adapter()
    assert isinstance(adapter, FakeEtcd)
    # cleanup
    del sys.modules[mod_name]


@pytest.mark.asyncio
async def test_get_adapter_consul_success(monkeypatch):
    # Create a fake consul_adapter module with ConsulAdapter
    mod_name = "fdc3.desktop_agent.distributed.consul_adapter"
    mod = types.ModuleType(mod_name)

    class FakeConsul(DistributedLogAdapter):
        async def start(self):
            return

        async def stop(self):
            return

        async def publish(self, topic: str, message) -> None:
            return

        async def subscribe(self, topic: str, callback):
            return "consul-sub"

        async def unsubscribe(self, subscription_id: str) -> None:
            return

    mod.ConsulAdapter = FakeConsul  # pyright: ignore[reportAttributeAccessIssue]
    sys.modules[mod_name] = mod

    monkeypatch.setenv("FDC3_DISTRIBUTED_ADAPTER", "consul")
    adapter = factory.get_adapter()
    assert isinstance(adapter, FakeConsul)
    # cleanup
    del sys.modules[mod_name]


def test_get_adapter_unknown_env(monkeypatch):
    monkeypatch.setenv("FDC3_DISTRIBUTED_ADAPTER", "unknown-value")
    adapter = factory.get_adapter()
    # should be the noop adapter
    assert type(adapter).__name__ == "NoopAdapter"
