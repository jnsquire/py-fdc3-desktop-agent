# Implementation Notes

This document summarizes current implementation choices and how to change them.

## WCP over FastAPI WebSocket

- The project carries WCP messages over a single FastAPI WebSocket connection. Handshake and identity validation are implemented in:
  - `src/fdc3_desktop_agent/handlers/wcp.py` (WCPHandler)
  - `src/fdc3_desktop_agent/server/__init__.py` (websocket endpoint)

- Message flow:
  - Browser app sends `WCP1Hello` -> server replies with `WCP3Handshake`.
  - Browser app sends `WCP4ValidateAppIdentity` -> server validates and replies with `WCP5ValidateAppIdentityResponse` (or failure).
  - After successful validation, the connection transitions to DACP phase and normal DACP messages are exchanged on the same WebSocket.

- MessagePort: the implementation does not proxy a native MessagePort object; instead, the standard WCP message types are serialized into JSON and sent over the WebSocket. If you need an explicit MessagePort bridge, add a small client-side postMessage shim that maps MessagePort messages to WCP envelopes and vice versa.

## `implementationMetadata` policy

- Current behavior: the `WCP5ValidateAppIdentityResponse` now includes a populated `implementationMetadata` object assembled from two sources:
  - stored `AppMetadata` (a curated subset: `appId`, `name`, `version`, `intents`, `capabilities`);
  - runtime/launcher info added at handshake time (under a `runtime` and optional `launcher` key) such as the Python executable, platform string, and agent WebSocket URL.

- Recommended contents and structure (example):

  {
    "app": { "appId": "com.example.app", "name": "Example", "version": "1.2.3", "intents": ["fdc3.openAppDirectory"] },
    "runtime": { "python": "C:/path/to/python.exe", "platform": "Windows-10-10.0.19041", "agentUrl": "ws://localhost:8000/ws" },
    "launcher": { "type": "subprocess", "capabilities": ["env", "cwd"] }
  }

- Implementation notes:
  - `WCPHandler` gathers `AppMetadata` from storage and merges a small runtime block produced from the agent process (for example `sys.executable`, `platform.platform()` and the configured agent URL).
  - Keep `implementationMetadata` minimal and avoid embedding secrets or sensitive environment variables.
  - Make runtime fields overridable via env vars (e.g. `FDC3_AGENT_URL`) or per-app metadata when needed.
  - Tests should assert presence/shape of the curated fields rather than exact environment-specific values.

- To change behavior: update the assembler helper in `WCPHandler` to include/exclude specific keys, or provide a configurable serializer that maps `AppMetadata` to the handshake payload.

## `intentResolverUrl` and `channelSelectorUrl` in `WCP3Handshake`

- Current behavior: both fields are set to `None` in the handshake (`WCP3Handshake` payload).
- Options to change behavior:
  - Per-agent default URLs via environment variables `FDC3_INTENT_RESOLVER_URL` and `FDC3_CHANNEL_SELECTOR_URL`.
  - Per-app override stored in `AppMetadata` (preferable when apps ship their own UIs).

- To enable: update `WCPHandler` to read `os.getenv('FDC3_INTENT_RESOLVER_URL')` and/or `app_metadata.intent_resolver_url` and set them in the `WCP3HandshakePayload`.

## Launch / Listener timing

- The agent currently waits up to 15 seconds for a launched app to connect and register listeners. This is implemented in `DACPHandler._handle_open` via `wait_for_instance_connection(..., timeout=15.0)`.
- You can change this timeout by modifying that call or making it configurable via an env var like `FDC3_LAUNCH_TIMEOUT_SECONDS`.

## Instance policy (single-instance default)

- Current behavior: when opening an app, if an existing instance for that `appId` already exists, the agent reuses the existing instance by default (single-instance policy). If the caller provides an explicit `instanceId`, the agent will attempt to find or launch that instance.
- To change behavior (allow multiple instances by default), update `DACPHandler._handle_open` to skip the existing-instance reuse branch and always allow creating a new instance unless explicitly constrained by app metadata.

## Error handling

- Current approach: handlers use defensive try/except and best-effort fallbacks; errors in callbacks are swallowed to avoid crashing event loops.
- Recommended improvements:
  - Add a central error reporting hook/metrics endpoint to track malformed messages and disconnections.
  - Emit structured logs with context (requestUuid, instanceUuid) for easier debugging.

## References
- `src/fdc3_desktop_agent/handlers/wcp.py`
- `src/fdc3_desktop_agent/handlers/dacp.py`
- `src/fdc3_desktop_agent/server/__init__.py`
- `src/fdc3_desktop_agent/core/channel_manager.py`

*** End of notes
