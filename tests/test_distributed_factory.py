import sys
import types
from typing import cast
from unittest.mock import patch

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

    mod.EtcdAdapter = FakeEtcd  # pyright: ignore[reportAttributeAccessIssue]  # ty:ignore[unresolved-attribute]
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

    setattr(mod, "ConsulAdapter", FakeConsul)
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


@pytest.mark.asyncio
async def test_get_adapter_etcd_fallback_relative_import_success(monkeypatch):
    # Force the importlib candidate import to fail, then ensure the relative
    # import path succeeds by providing a module in sys.modules.
    mod_name = "fdc3.desktop_agent.distributed.etcd_adapter"
    mod = types.ModuleType(mod_name)

    class FakeEtcdRel(DistributedLogAdapter):
        async def start(self):
            return

        async def stop(self):
            return

        async def publish(self, topic: str, message) -> None:
            return

        async def subscribe(self, topic: str, callback):
            return "etcd-rel-sub"

        async def unsubscribe(self, subscription_id: str) -> None:
            return

    setattr(mod, "EtcdAdapter", FakeEtcdRel)
    sys.modules[mod_name] = mod

    monkeypatch.setenv("FDC3_DISTRIBUTED_ADAPTER", "etcd")
    try:
        with patch("importlib.import_module", side_effect=RuntimeError("boom")):
            adapter = factory.get_adapter()
            assert isinstance(adapter, FakeEtcdRel)
            assert await adapter.subscribe("t", lambda *_: None) == "etcd-rel-sub"
    finally:
        del sys.modules[mod_name]


def test_get_adapter_etcd_fallback_relative_import_failure_returns_noop(monkeypatch):
    # Force candidate import to fail and relative import to raise ImportError
    # by providing a module without EtcdAdapter.
    mod_name = "fdc3.desktop_agent.distributed.etcd_adapter"
    sys.modules[mod_name] = types.ModuleType(mod_name)

    monkeypatch.setenv("FDC3_DISTRIBUTED_ADAPTER", "etcd")
    try:
        with patch("importlib.import_module", side_effect=RuntimeError("boom")):
            adapter = factory.get_adapter()
            assert type(adapter).__name__ == "NoopAdapter"
    finally:
        del sys.modules[mod_name]


@pytest.mark.asyncio
async def test_get_adapter_consul_candidate_missing_attr_then_relative_import_success(
    monkeypatch,
):
    # Simulate importlib importing a module that lacks ConsulAdapter (getattr
    # fails), then ensure the relative import succeeds via sys.modules.
    mod_name = "fdc3.desktop_agent.distributed.consul_adapter"

    class FakeConsulRel(DistributedLogAdapter):
        async def start(self):
            return

        async def stop(self):
            return

        async def publish(self, topic: str, message) -> None:
            return

        async def subscribe(self, topic: str, callback):
            return "consul-rel-sub"

        async def unsubscribe(self, subscription_id: str) -> None:
            return

    # Module used by relative import has the adapter class
    rel_mod = types.ModuleType(mod_name)
    setattr(rel_mod, "ConsulAdapter", FakeConsulRel)
    sys.modules[mod_name] = rel_mod

    # Module returned by importlib.import_module is missing ConsulAdapter
    imported_mod = types.ModuleType(mod_name)

    monkeypatch.setenv("FDC3_DISTRIBUTED_ADAPTER", "consul")
    try:
        with patch("importlib.import_module", return_value=imported_mod):
            adapter = factory.get_adapter()
            assert isinstance(adapter, FakeConsulRel)
            assert await adapter.subscribe("t", lambda *_: None) == "consul-rel-sub"
    finally:
        del sys.modules[mod_name]


def test_get_adapter_consul_relative_import_failure_returns_noop(monkeypatch):
    # Make the candidate import succeed but not provide ConsulAdapter (getattr
    # fails), and force the relative import to fail by providing a module
    # without ConsulAdapter.
    mod_name = "fdc3.desktop_agent.distributed.consul_adapter"
    sys.modules[mod_name] = types.ModuleType(mod_name)
    imported_mod = types.ModuleType(mod_name)

    monkeypatch.setenv("FDC3_DISTRIBUTED_ADAPTER", "consul")
    try:
        with patch("importlib.import_module", return_value=imported_mod):
            adapter = factory.get_adapter()
            assert type(adapter).__name__ == "NoopAdapter"
    finally:
        del sys.modules[mod_name]


@pytest.mark.asyncio
async def test_distributed_log_adapter_abstract_methods_raise_not_implemented():
    from fdc3.desktop_agent.distributed.adapter import DistributedLogAdapter

    dummy = cast(DistributedLogAdapter, object())
    with pytest.raises(NotImplementedError):
        await DistributedLogAdapter.start(dummy)
    with pytest.raises(NotImplementedError):
        await DistributedLogAdapter.stop(dummy)
    with pytest.raises(NotImplementedError):
        await DistributedLogAdapter.publish(dummy, "t", {"a": 1})
    with pytest.raises(NotImplementedError):
        await DistributedLogAdapter.subscribe(dummy, "t", lambda *_: None)
    with pytest.raises(NotImplementedError):
        await DistributedLogAdapter.unsubscribe(dummy, "sub")
