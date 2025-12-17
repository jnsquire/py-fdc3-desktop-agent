import asyncio

from fdc3.client.events import EventEmitter


def test_event_emitter_calls_handlers_in_order():
    results = []

    async def h1(p):
        results.append(("h1", p))

    async def h2(p):
        results.append(("h2", p))

    emitter = EventEmitter()
    emitter.add(h1)
    emitter.add(h2)

    asyncio.run(emitter.emit({"x": 1}))

    assert results == [("h1", {"x": 1}), ("h2", {"x": 1})]


def test_event_emitter_remove_handler():
    results = []

    async def h(p):
        results.append(p)

    emitter = EventEmitter()
    emitter.add(h)
    emitter.remove(h)

    asyncio.run(emitter.emit(123))

    assert results == []


def test_emit_handles_exceptions():
    results = []

    async def bad(p):
        raise RuntimeError("boom")

    async def good(p):
        results.append(p)

    emitter = EventEmitter()
    emitter.add(bad)
    emitter.add(good)

    asyncio.run(emitter.emit("x"))

    assert results == ["x"]
