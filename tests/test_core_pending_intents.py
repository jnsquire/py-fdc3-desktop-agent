import pytest
from fdc3.desktop_agent.core import core_services


@pytest.mark.asyncio
async def test_create_and_resolve_pending_intent():
    req = "test-req-1"
    fut = core_services.create_pending_intent(req)
    assert not fut.done()

    # Resolve
    core_services.resolve_pending_intent(req, result={"ok": True})
    assert fut.done()
    assert fut.result() == {"ok": True}


@pytest.mark.asyncio
async def test_register_duplicate_warns(caplog):
    req = "dup-req"
    caplog.clear()
    fut1 = core_services.create_pending_intent(req)
    fut2 = core_services.create_pending_intent(req)
    assert fut1 is fut2
    assert any("already registered" in r.message for r in caplog.records)


def test_resolve_missing_warns(caplog):
    req = "no-such-req"
    caplog.clear()
    core_services.resolve_pending_intent(req, result={})
    assert any("no pending intent" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_resolve_already_done_warns(caplog):
    req = "done-req"
    fut = core_services.create_pending_intent(req)
    # Resolve the future first so it's done
    core_services.resolve_pending_intent(req, result={"ok": True})
    await fut  # Now safe to await - already resolved
    caplog.clear()
    # Try resolving again - should warn about no pending intent (since it was popped)
    core_services.resolve_pending_intent(req, result={"ok": True})
    assert any("no pending intent" in r.message for r in caplog.records)
