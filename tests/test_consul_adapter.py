import asyncio
import json
from unittest.mock import MagicMock

import pytest

from fdc3.desktop_agent.distributed.consul_adapter import ConsulAdapter


class FakeResp:
    def __init__(self, status, body=None, headers=None):
        self.status = status
        self._body = body or []
        self.headers = headers or {}

    async def json(self):
        return self._body

    async def text(self):
        return json.dumps(self._body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass


class FakeSession:
    def __init__(self):

        # Use MagicMock (sync) so .get() returns an async context manager directly
        self._get = MagicMock()
        self._put = MagicMock()

    def get(self, *args, **kwargs):
        return self._get(*args, **kwargs)

    def put(self, *args, **kwargs):
        return self._put(*args, **kwargs)

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_deduplicate_keys_and_schedule_coroutine_callback(monkeypatch):
    # Monkeypatch the consul_adapter module to provide a fake aiohttp.ClientSession
    import fdc3.desktop_agent.distributed.consul_adapter as mod

    sess = FakeSession()
    monkeypatch.setattr(
        mod,
        "aiohttp",
        type("AioHttpStub", (), {"ClientSession": lambda self=None: sess}),
    )

    adapter = ConsulAdapter()
    await adapter.start()

    # prepare two responses with same key twice, then cancel
    body1 = [{"Key": "k1", "Value": json.dumps({"a": 1})}]
    body2 = [{"Key": "k1", "Value": json.dumps({"a": 2})}]

    # Sequence the responses
    sess._get.side_effect = [
        FakeResp(200, body=body1, headers={"X-Consul-Index": "1"}),
        FakeResp(200, body=body2, headers={"X-Consul-Index": "2"}),
    ]

    # callback that returns coroutine and records events
    events = []
    event = asyncio.Event()

    async def cb(data):
        events.append(data)
        event.set()

    sub_id = await adapter.subscribe("topic1", cb)

    # wait for at least one callback invocation
    await asyncio.wait_for(event.wait(), timeout=1.0)

    # give the watch loop a moment to process the second response
    await asyncio.sleep(0.01)

    # ensure only one event was emitted (deduplication)
    assert len(events) == 1
    assert events[0]["a"] == 1

    # unsubscribe and ensure task is cleaned up
    await adapter.unsubscribe(sub_id)


@pytest.mark.asyncio
async def test_stop_awaits_watch_tasks(monkeypatch):
    # Monkeypatch aiohttp for the module under test
    import fdc3.desktop_agent.distributed.consul_adapter as mod

    sess = FakeSession()
    monkeypatch.setattr(
        mod,
        "aiohttp",
        type("AioHttpStub", (), {"ClientSession": lambda self=None: sess}),
    )

    adapter = ConsulAdapter()

    # Create a long-running watch loop task that we will cancel
    async def never_get(*args, **kwargs):
        await asyncio.sleep(3600)

    sess._get.side_effect = [FakeResp(200, body=[])]  # will block on long wait inside adapter loop

    called = asyncio.Event()

    def cb(_):
        called.set()

    await adapter.start()
    sub_id = await adapter.subscribe("topic2", cb)

    # give the watch task a moment to start
    await asyncio.sleep(0)

    # stop should cancel and await the watch task without raising
    await adapter.stop()

    # after stop, task should be removed
    assert sub_id not in adapter._watch_tasks
