# Plan: External Process Intent Handler Registration

Allow separate Python processes (not embedded plugins) to connect to the desktop agent and register as intent handlers.

## Steps

### 1. Define protocol messages in `fdc3_desktop_agent/protocol/dacp/dacp.py`

- Add `RegisterExternalHandlerRequest` and `RegisterExternalHandlerResponse` message types
- Add `UnregisterExternalHandlerRequest` and `ForwardedIntentEvent` messages

### 2. Create external handler registry as `fdc3_desktop_agent/core/external_registry.py`

- `ExternalHandler` dataclass (handler_uuid, instance_uuid, handler_id, intents, priority)
- `ExternalHandlerRegistry` class with register/unregister/get_handlers_for_intent methods
- Integrate into `CoreServices` in `fdc3_desktop_agent/core/__init__.py`

### 3. Extend DACP handler in `fdc3_desktop_agent/handlers/dacp.py`

- Handle `registerExternalHandler` / `unregisterExternalHandler` messages
- Add `_try_external_handler()` in intent resolution (after plugins, before normal resolution)
- Forward intents to external handlers via WebSocket and correlate responses

### 4. Support self-registration identity in `fdc3_desktop_agent/handlers/wcp.py`

- Allow WCP `hello`/`validate` from processes that weren't agent-launched
- Recognize `app_id` patterns like `external-handler:*` for self-registering handlers

### 5. Add intent result forwarding

- Track pending intent requests with futures
- Handle `intentResultEvent` from external handlers and resolve futures
- Return results to original intent raiser

## Further Considerations

1. **Connection cleanup** - When an external handler's WebSocket disconnects, should all its registered handlers be auto-unregistered? (Recommend: Yes, with optional reconnection grace period)

2. **Security** - Should external handlers require authentication/authorization before registering? (Consider: API key validation, origin checking, or trust-on-first-use)

3. **Load balancing** - If multiple external handlers register for the same intent, use first-match by priority or round-robin? (Current plugins use priority-based first-wins)

## Client library and example external process

To make it easy for third-party Python processes to act as external intent handlers, provide a small client library and an example process.

### `fdc3_client` library

Responsibilities:

- Manage WebSocket connection to the agent WCP endpoint, including the WCP hello/identify handshake and reconnection/backoff logic.
- Provide `register_handler(handler_id, intents, priority=0, metadata=None)` and `unregister_handler(handler_uuid)` helpers that send the protocol messages and return the agent-assigned `handler_uuid`.
- Emit incoming forwarded intent events to user-provided callbacks and expose a synchronous/async API for replying with results or errors.
- Correlate `request_uuid` values and optionally support timeouts and cancellation.
- Provide built-in heartbeats/ping handling and automatic re-registration of handlers after reconnect.

Suggested API (minimal):

```python
from fdc3_client import FDC3Client

async with FDC3Client(agent_url) as client:
		handler_uuid = await client.register_handler(
				handler_id="my-handler",
				intents=["ViewChart", "AnalyzeData"],
				priority=10,
		)

		async def on_intent(request):
				# request has attributes: request_uuid, intent, context, source
				result = await do_work(request.intent, request.context)
				await client.send_intent_result(request.request_uuid, result=result)

		client.on_intent(on_intent)
		await client.run_forever()
```

### Example external process

Include a lightweight example in `examples/external_handler.py` demonstrating:

- Using `fdc3_client` to connect and register
- Handling a forwarded intent and returning a result
- Graceful unregister on SIGTERM/SIGINT

The example should be runnable with:

```bash
python -m examples.external_handler --agent-url ws://localhost:8000/ws
```

## Server-side protocol message definitions (expanded)

Add concrete JSON schemas and message types to `fdc3_desktop_agent/protocol/dacp/dacp.py` for the messages described earlier. Include explicit fields and examples.

Example JSON schemas (concise):

- `registerExternalHandler` request

```json
{
  "type": "registerExternalHandler",
  "payload": {
    "handler_id": "string",
    "intents": ["string"],
    "priority": 0,
    "metadata": { "optional": "object" }
  }
}
```

- `registerExternalHandlerResponse`

```json
{
  "type": "registerExternalHandlerResponse",
  "payload": { "handler_uuid": "uuid-string" }
}
```

- `forwardedIntent` (agent → external handler)

```json
{
  "type": "forwardedIntent",
  "payload": {
    "request_uuid": "uuid-string",
    "intent": "string",
    "context": { "optional": "object" },
    "source": { "appId": "string", "instanceId": "string" },
    "timeout": 30
  }
}
```

- `intentResult` (handler → agent)

```json
{
  "type": "intentResult",
  "payload": {
    "request_uuid": "uuid-string",
    "result": { "optional": "object" },
    "error": "optional-error-message"
  }
}
```

## Tests and documentation

- Add unit tests for the registry and DACP handler logic (message parsing, register/unregister, forward/response correlation).
- Add a short README section with instructions for third-party authors to implement and package external handlers, including an example `pyproject.toml` and entry about security considerations.

---

This update extends the original plan to include concrete work items for building the client library and sample process plus the server-side message definitions, tests, and docs.
