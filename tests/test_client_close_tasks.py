import asyncio
from typing import cast

from fdc3.client.client import FDC3Client
from websockets.asyncio.client import ClientConnection


class FakeWS:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


async def test_close_awaits_cancelled_tasks():
    client = FDC3Client("ws://example", "h")

    async def sleeper():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            # Ensure cancellation flows through
            raise

    client._recv_task = asyncio.create_task(sleeper())
    client._ping_task = asyncio.create_task(sleeper())
    client._ws = cast(ClientConnection, FakeWS())
    client._running = True

    await client.close()

    assert client._recv_task is None
    assert client._ping_task is None
    assert client._ws is None
