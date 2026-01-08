# External Intent Handlers

External intent handlers are standalone Python processes that connect to the desktop agent via WebSocket and register as intent handlers. Unlike embedded plugins, external handlers run in separate processes and can be written by third parties.

## Overview

External handlers:

- Connect to the agent's WebSocket endpoint (`/ws`)
- Complete the WCP (Web Connection Protocol) handshake using self-registration
- Register handlers for specific intents
- Receive forwarded intent requests and send results back

## Using the Client Library

The `fdc3.client` package provides a simple client for building external handlers:

```python
from fdc3.client import FDC3Client

async with FDC3Client("ws://localhost:8000/ws", handler_id="my-handler") as client:
    # Wait for WCP handshake to complete
    if not await client.wait_for_handshake():
        raise RuntimeError("Handshake failed")

    # Register for specific intents
    handler_uuid = await client.register_handler(
        handler_id="my-handler",
        intents=["ViewChart", "AnalyzeData"],
        priority=10,
    )

    # Handle incoming intents
    async def on_intent(request):
        # request has: request_uuid, intent, context, source
        result = await process_intent(request.intent, request.context)
        await client.send_intent_result(request.request_uuid, result=result)

    # Register handler using the public EventEmitter
    client.forwarded_intent_handlers.add(on_intent)
    await client.run_forever()
```

## FDC3Client API

### Constructor

```python
FDC3Client(
    agent_url: str,            # WebSocket URL (e.g., "ws://localhost:8000/ws")
    handler_id: str = "external-handler",  # Unique handler identifier
    ping_interval: float = 20.0,  # WebSocket ping interval in seconds
)
```

### Methods

| Method                                                             | Description                                                             |
| ------------------------------------------------------------------ | ----------------------------------------------------------------------- |
| `connect()`                                                        | Connect to the agent and initiate WCP handshake                         |
| `wait_for_handshake(timeout=10.0)`                                 | Wait for WCP handshake to complete; returns `True` if successful        |
| `register_handler(handler_id, intents, priority=0, metadata=None)` | Register as a handler for the specified intents; returns `handler_uuid` |
| `unregister_handler(handler_uuid)`                                 | Unregister a previously registered handler                              |
| `send_intent_result(request_uuid, result=None, error=None)`        | Send the result (or error) for a forwarded intent                       |
| `forwarded_intent_handlers`                                         | `EventEmitter` used to subscribe to forwarded intent events (use `add`/`remove`) |
| `close()`                                                          | Close the WebSocket connection                                          |
| `run_forever()`                                                    | Block until the connection is closed                                    |

## Protocol Messages

External handlers use these message types:

### registerExternalHandler (client → agent)

```json
{
  "type": "registerExternalHandler",
  "payload": {
    "handler_id": "my-handler",
    "intents": ["ViewChart", "AnalyzeData"],
    "priority": 10,
    "metadata": {}
  },
  "meta": { "requestUuid": "uuid-string" }
}
```

### registerExternalHandlerResponse (agent → client)

```json
{
  "type": "registerExternalHandlerResponse",
  "payload": { "handler_uuid": "uuid-string" },
  "meta": { "requestUuid": "uuid-string" }
}
```

### forwardedIntent (agent → client)

```json
{
  "type": "forwardedIntent",
  "payload": {
    "request_uuid": "uuid-string",
    "intent": "ViewChart",
    "context": { "type": "fdc3.chart", "data": {} },
    "source": { "appId": "app-id", "instanceId": "instance-id" },
    "timeout": 30
  }
}
```

### intentResult (client → agent)

```json
{
  "type": "intentResult",
  "payload": {
    "request_uuid": "uuid-string",
    "result": { "data": "value" },
    "error": null
  }
}
```

## Example External Handler

See the repository example at https://github.com/jnsquire/py-fdc3-desktop-agent/blob/main/examples/external_handler.py for a complete working example. Run it with:

```bash
python -m examples.external_handler --agent-url ws://localhost:8000/ws --handler-id my-handler
```

## Creating an External Handler Package

To package an external handler for distribution:

### pyproject.toml

```toml
[project]
name = "my-fdc3-handler"
version = "0.1.0"
dependencies = [
    "websockets>=11.0",
]

[project.scripts]
my-fdc3-handler = "my_handler.main:main"
```

### Handler Implementation

```python
# my_handler/main.py
import asyncio
from fdc3.client import FDC3Client

async def run():
    async with FDC3Client("ws://localhost:8000/ws", handler_id="my-handler") as client:
        await client.wait_for_handshake()
        await client.register_handler("my-handler", ["MyIntent"], priority=5)

        async def on_intent(req):
            # Handle the intent
            await client.send_intent_result(req.request_uuid, result={"handled": True})

        client.forwarded_intent_handlers.add(on_intent)
        await client.run_forever()

def main():
    asyncio.run(run())
```

## Security Considerations

External handlers connect via WebSocket and are trusted once connected. Consider these security measures:

1. **Network access**: Run the agent on `localhost` or behind a firewall to limit who can connect.

2. **Origin checking**: Configure `FDC3_ALLOWED_ORIGINS` to restrict WebSocket connections to known origins.

3. **Handler priority**: External handlers with high priority can intercept intents before other handlers. Monitor what handlers are registered.

4. **Connection monitoring**: The agent logs handler registrations. External handlers are automatically unregistered when their WebSocket connection closes.

5. **Authentication (future)**: For production environments, consider adding API key validation or certificate-based authentication before allowing external handler registration.

## Intent Resolution Order

When an intent is raised, resolution follows this order:

1. **System intents** (`fdc3.StartApp`, etc.)
2. **Embedded plugins** (by priority, highest first)
3. **External handlers** (by priority, highest first)
4. **Standard app resolution** (app directory lookup)
