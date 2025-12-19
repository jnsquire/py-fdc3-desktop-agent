import asyncio
from fdc3.desktop_agent.core import core_services

print("initial pending:", list(core_services._pending_intents.keys()))
# simulate test_register_duplicate_warns
fut1 = core_services.create_pending_intent("dup-req")
fut2 = core_services.create_pending_intent("dup-req")
print("after dup pending:", list(core_services._pending_intents.keys()))
# simulate test_create_and_resolve
futA = core_services.create_pending_intent("test-req-1")
print("before resolve pending:", list(core_services._pending_intents.keys()))
core_services.resolve_pending_intent("test-req-1", result={"ok": True})
print("after resolve pending:", list(core_services._pending_intents.keys()))
# simulate test_resolve_already_done_warns
futB = core_services.create_pending_intent("done-req")
print("created done-req pending:", list(core_services._pending_intents.keys()))
print("futB done?", futB.done())


async def waiter():
    try:
        print("waiting for futB...")
        res = await asyncio.wait_for(futB, timeout=1.0)
        print("futB result", res)
    except Exception as e:
        print("waiter exception", type(e), e)


asyncio.run(waiter())
print("final pending:", list(core_services._pending_intents.keys()))
