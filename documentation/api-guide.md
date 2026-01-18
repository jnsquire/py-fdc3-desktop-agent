# API Guide

This page is a narrative companion to the generated API reference. It focuses on the common ways to run or integrate the agent and how to write an external intent handler client.

## Embed the agent in Python

The agent is a FastAPI application. If you want to mount it into a larger ASGI app (or run it programmatically), use the application factory.

```python
from fastapi import FastAPI

from fdc3.desktop_agent.config import DesktopAgentConfig
from fdc3.desktop_agent.server import create_app

config = DesktopAgentConfig(
    host="0.0.0.0",
    port=8000,
    db_path=":memory:",
)

fdc3_app = create_app(config)

app = FastAPI()
app.mount("/fdc3", fdc3_app)
```

Notes:

- If you omit `DesktopAgentConfig`, defaults are read from environment variables.
- The agent websocket endpoint is at `/ws` (so in the example above, `/fdc3/ws`).

## Run the agent in development

The repository includes a convenient dev command (also used by VS Code tasks):

```bash
python -m uvicorn fdc3.desktop_agent.server:app --reload --host 0.0.0.0 --port 8000
```

## Write an external intent handler

External handlers connect to the agent’s WebSocket endpoint and register the intents they can service.

```python
import asyncio

from fdc3.client.client import FDC3Client


async def main() -> None:
    async with FDC3Client("ws://localhost:8000/ws", handler_id="my-handler") as client:
        await client.register_handler("my-handler", intents=["ViewChart"], priority=0)

        async def on_intent(msg) -> None:
            # Your app logic goes here. When you are done, respond with a result.
            request_uuid = (msg.meta or {}).get("requestUuid")
            if request_uuid:
                await client.send_intent_result(request_uuid, result={"type": "fdc3.nothing"})

        client.forwarded_intent_handlers.add(on_intent)
        await client.run_forever()


asyncio.run(main())
```

Tips:

- `forwarded_intent_handlers`, `broadcast_handlers`, and `intent_event_handlers` are event emitters you can subscribe to.
- Most request/response APIs require the handshake to complete; `FDC3Client` handles this during `connect()` / `async with`.

## Broadcast context

To broadcast a context payload to the current channel:

```python
await client.broadcast({"type": "fdc3.instrument", "id": {"ticker": "AAPL"}})
```

## Where to look next

- Generated reference: [api.md](api.md)
- Embedding details: [embedding-api.md](embedding-api.md)
- External handler details: [external-intent-handlers.md](external-intent-handlers.md)
