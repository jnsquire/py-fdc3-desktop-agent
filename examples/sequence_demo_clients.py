"""Example/demo: simulate multiple clients sending channel events.

This script calls the GraphQL `emitChannelEvent` mutation (dev helper)
added to the server to emit synthetic events that will be visible in the
`/channel-sequence` page's live Mermaid diagram.

Usage:
    python examples/sequence_demo_clients.py --host localhost --port 8000

"""

import asyncio
import uuid
import argparse
import random

from fdc3.client.client import FDC3Client


MUTATION = """
mutation EmitEvent($channelId: String!, $eventType: String!, $instanceUuid: String, $context: String) {
  emitChannelEvent(channelId: $channelId, eventType: $eventType, instanceUuid: $instanceUuid, context: $context)
}
"""


async def send_broadcast(client: FDC3Client, channel: str, instance: str, context: dict | None):
    # Include channel id and instance info inside the context so the
    # sequence diagram can show which channel/instance produced the broadcast.
    # DACP broadcast requires a `type` field on the context
    ctx = {"type": "fdc3.demo", "channelId": channel, "instanceUuid": instance}
    if context:
        ctx.update(context)
    await client.broadcast(ctx)


async def client_worker(agent_url: str, channel: str, name: str, messages: int, delay: float):
    async with FDC3Client(agent_url, handler_id=name) as client:
        # wait for WCP handshake to complete
        await client.wait_for_handshake()

        # Emit a 'joined' event (dev helper mutation) so the sequence UI
        # receives a proper 'joined' event type.
        await client.emit_channel_event("joined", channel, instance_uuid=name, context={"info": f"{name} joined"})

        for i in range(messages):
            await asyncio.sleep(delay + random.random() * delay)
            ctx = {"from": name, "msg": f"hello {i} from {name}"}
            await send_broadcast(client, channel, name, ctx)

        # Emit a 'left' event
        await asyncio.sleep(0.1)
        await client.emit_channel_event("left", channel, instance_uuid=name, context={"info": f"{name} left"})


async def main(args):
    agent_ws = f"ws://{args.host}:{args.port}/ws"
    tasks = []
    for n in range(args.clients):
        name = f"user-{n + 1}-{str(uuid.uuid4())[:6]}"
        tasks.append(
            asyncio.create_task(
                client_worker(agent_ws, args.channel, name, args.messages, args.delay)
            )
        )
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", default=8000, type=int)
    p.add_argument("--channel", default="user:demo")
    p.add_argument("--clients", default=3, type=int)
    p.add_argument("--messages", default=5, type=int)
    p.add_argument("--delay", default=0.5, type=float)
    args = p.parse_args()

    asyncio.run(main(args))
