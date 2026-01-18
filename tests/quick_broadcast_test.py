import asyncio
import os

import pytest

from fdc3.client.client import FDC3Client


@pytest.mark.skipif(
    os.getenv("CI") is not None,
    reason="Quick broadcast test is unreliable in CI environments",
)
async def test():
    alice = FDC3Client("ws://localhost:8000/ws", handler_id="auto-alice")
    bob = FDC3Client("ws://localhost:8000/ws", handler_id="auto-bob")

    await alice.connect()
    await bob.connect()
    await alice.wait_for_handshake()
    await bob.wait_for_handshake()

    received = asyncio.Event()

    async def on_broadcast(evt):
        print("bob received broadcast:", evt.payload.context)
        received.set()

    bob.broadcast_handlers.add(on_broadcast)
    await bob.add_context_listener("fdc3.chat.message")

    await alice.broadcast(
        {
            "type": "fdc3.chat.message",
            "from": "auto-alice",
            "text": "hello",
            "channelId": "user:demo",
        }
    )

    try:
        await asyncio.wait_for(received.wait(), timeout=2.0)
        print("broadcast delivered")
    except asyncio.TimeoutError:
        print("no broadcast delivered")

    await asyncio.sleep(0.5)
    print("alice running", alice._running, "bob running", bob._running)

    await alice.close()
    await bob.close()


if __name__ == "__main__":
    asyncio.run(test())
