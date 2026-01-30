# Implementation Notes

This document summarizes current implementation choices and how to change them.

## WCP over FastAPI WebSocket

- The project carries WCP messages over a single FastAPI WebSocket connection. Handshake and identity validation are implemented in:
  - `fdc3/desktop_agent/handlers/wcp.py` (WCPHandler)
  - `fdc3/desktop_agent/server/__init__.py` (websocket endpoint)

- Message flow:
  - Browser app sends `WCP1Hello` -> server replies with `WCP3Handshake`.
  - Browser app sends `WCP4ValidateAppIdentity` -> server validates and replies with `WCP5ValidateAppIdentityResponse` (or failure).
  - After successful validation, the connection transitions to DACP phase and normal DACP messages are exchanged on the same WebSocket.

- MessagePort: the implementation does not proxy a native MessagePort object; instead, the standard WCP message types are serialized into JSON and sent over the WebSocket. If you need an explicit MessagePort bridge, add a small client-side postMessage shim that maps MessagePort messages to WCP envelopes and vice versa.

## Desktop Agent Bridging (experimental BCP/BMP)

This agent includes an experimental implementation of FDC3 Desktop Agent Bridging.

### High-level design

- A background `BridgeClient` connects to a Desktop Agent Bridge over WebSocket.
- Connection uses the recommended bridge port discovery range (default 4475-4575) and retries periodically.
- On connection, the client completes the BCP handshake:
  - waits for `hello`
  - sends `handshake` including:
    - `requestedName`
    - `implementationMetadata`
    - `channelsState`
  - waits for `connectedAgentsUpdate` assigning a local name.
- After handshake:
  - BMP request/response correlation is performed via `meta.requestUuid`.
  - Inbound bridge-forwarded requests are handled by an injected `BridgeRequestRouter`.

Key modules:

- `fdc3/desktop_agent/bridging/client.py` — BCP/BMP client
- `fdc3/desktop_agent/bridging/router.py` — handles requests received from the bridge
- `fdc3/desktop_agent/server/__init__.py` — wires the bridge client into the FastAPI lifespan

### Configuration

Bridging is controlled by `DesktopAgentConfig` (or environment variables):

- `bridge_enabled` / `FDC3_BRIDGE_ENABLED` (default false)
- `bridge_host` / `FDC3_BRIDGE_HOST` (default 127.0.0.1)
- `bridge_port_start` / `FDC3_BRIDGE_PORT_START` (default 4475)
- `bridge_port_end` / `FDC3_BRIDGE_PORT_END` (default 4575)
- `bridge_requested_name` / `FDC3_BRIDGE_REQUESTED_NAME` (default hostname)
- `bridge_connect_retry_seconds` / `FDC3_BRIDGE_CONNECT_RETRY_SECONDS` (default 5)
- `bridge_request_timeout_seconds` / `FDC3_BRIDGE_REQUEST_TIMEOUT_SECONDS` (default 3)

### Supported bridged operations

Outbound (this agent -> bridge):

- `broadcast` is forwarded to the bridge as `broadcastRequest` (best-effort; local delivery still occurs).
- `raiseIntent` is forwarded when the target includes `desktopAgent` (remote desktop agent).

Inbound (bridge -> this agent):

- `broadcastRequest` (fan-out to local listeners/channel members)
- `openRequest`
- `getAppMetadataRequest`
- `findInstancesRequest`
- `findIntentRequest`
- `findIntentsByContextRequest` (currently returns an empty result rather than guessing)
- `raiseIntentRequest`

### Current limitations

- Bridging is best-effort and does not block the agent startup if the bridge is unavailable.
- `channelsState` is currently reported as an empty map during handshake (no cross-agent channel state sync yet).
- Channel membership APIs are local-only; there is no bridged join/leave or cross-agent channel selector at this time.

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

- `fdc3/desktop_agent/handlers/wcp.py`
- `fdc3/desktop_agent/handlers/dacp/` — DACP handler package (see below)
- `fdc3/desktop_agent/server/__init__.py`
- `fdc3/desktop_agent/core/channel_manager.py`

## DACP Handler Module Structure

The DACP handler was refactored from a single monolithic file into a package with domain-focused modules using a mixin pattern:

- `fdc3/desktop_agent/handlers/dacp/__init__.py` — Public exports (`DACPHandler`, `dacp_handler`, `DACPError`)
- `fdc3/desktop_agent/handlers/dacp/base.py` — Core `DACPHandler` class, shared utilities (`_send_error`, `_send_model`, `_emit_*`, `_wire_channel`, bridging helpers)
- `fdc3/desktop_agent/handlers/dacp/app.py` — `AppHandlersMixin` with app lifecycle handlers (`open`, `getAppMetadata`, `findInstances`, `getInfo`)
- `fdc3/desktop_agent/handlers/dacp/channel.py` — `ChannelHandlersMixin` with channel handlers (user channels, private channels, context broadcast/listeners)
- `fdc3/desktop_agent/handlers/dacp/event.py` — `EventHandlersMixin` with event subscription handlers (`addEventListener`, `removeEventListener`)
- `fdc3/desktop_agent/handlers/dacp/intent.py` — `IntentHandlersMixin` with intent handlers (`findIntent`, `raiseIntent`, external handler registration)
- `fdc3/desktop_agent/handlers/dacp/registry.py` — `@dacp_handler` decorator and `DACPError` exception
- `fdc3/desktop_agent/handlers/dacp/models.py` — Shared Pydantic models

The `DACPHandler` class inherits from all mixin classes, and handler discovery uses MRO traversal to find all `@dacp_handler`-decorated methods. A compatibility shim at `fdc3/desktop_agent/handlers/dacp.py` preserves backward compatibility for existing imports.
