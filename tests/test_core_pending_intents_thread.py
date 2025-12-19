import asyncio
import threading

import pytest
from fdc3.desktop_agent.core import core_services


@pytest.mark.asyncio
async def test_resolve_from_other_thread_sets_future():
    req = "thread-req"
    fut = core_services.create_pending_intent(req)

    # Resolve from another thread
    def resolver():
        core_services.resolve_pending_intent(req, result={"ok": "from-thread"})

    t = threading.Thread(target=resolver)
    t.start()
    t.join()

    # Await the future in the event loop
    res = await asyncio.wait_for(fut, timeout=1.0)
    assert res == {"ok": "from-thread"}
