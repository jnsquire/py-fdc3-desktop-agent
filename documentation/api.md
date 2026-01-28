# API Reference

## Desktop Agent

::: fdc3.desktop_agent.server

::: fdc3.desktop_agent.cli

::: fdc3.desktop_agent.config

### Examples

Start the agent quickly with Docker:

```bash
docker-compose up
```

See [getting-started.md](getting-started.md) for the full walkthrough.

## Client

::: fdc3.client.client

### Examples

Register an external handler and run the client:

```python
import asyncio

from fdc3.client.client import FDC3Client


async def main() -> None:
	async with FDC3Client("ws://localhost:8000/ws", handler_id="my-handler") as c:
		await c.register_handler("my-handler", intents=["ViewChart"])
		await c.run_forever()


asyncio.run(main())
```

See [getting-started.md](getting-started.md) for a minimal demo client.

## Models

::: fdc3.models.identifiers
