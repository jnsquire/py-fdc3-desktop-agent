# FDC3 Desktop Agent (Python) — Build Checklist

This checklist tracks the initial build plan for an FDC3 Desktop Agent with **browser app support** via **WCP**, and **agent/app communication** via **DACP**.

Primary goals:
- Browser apps connect via WCP (Web Connection Protocol) over a local transport.
- App-to-agent calls and agent-to-app events use DACP message envelopes.
- Expose communications via a **FastAPI** server:
  - WebSocket endpoint for WCP + subsequent DACP messaging
  - Strawberry-based GraphQL endpoint (optional management/observability surface)
- Auto-generate Pydantic models from the `fdc3-for-web` JSON Schemas and provide Strawberry types derived from those models.
- **Multiple instances supported**; **single instance per app is the default policy**.
- Persist only **app directory + launch configuration** initially (SQLite), while **listeners/instances are in-memory**.
- Prepare for real process launching now (static env vars + command line args), with a launcher abstraction.
- Storage is behind an abstraction layer so we can later swap to a distributed transactional DB.

---

## Source of truth (schemas)

Use these schemas (FINOS FDC3, `fdc3-for-web` branch) as authoritative for field names and message shapes:

### WCP schemas
- WCP1Hello: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/WCP1Hello.schema.json
- WCP2LoadUrl: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/WCP2LoadUrl.schema.json
- WCP3Handshake: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/WCP3Handshake.schema.json
- WCP4ValidateAppIdentity: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/WCP4ValidateAppIdentity.schema.json
- WCP5ValidateAppIdentityResponse: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/WCP5ValidateAppIdentityResponse.schema.json
- WCP5ValidateAppIdentityFailedResponse: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/WCP5ValidateAppIdentityFailedResponse.schema.json
- WCP6Goodbye: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/WCP6Goodbye.schema.json

### DACP envelopes + types
- appRequest: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/appRequest.schema.json
- agentResponse: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/agentResponse.schema.json
- agentEvent: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/agentEvent.schema.json
- common: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/common.schema.json
- api types (AppIdentifier / IntentResolution / ImplementationMetadata / errors): https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/api.schema.json

### Key message schemas to implement first
- open: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/openRequest.schema.json, https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/openResponse.schema.json
- broadcast: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/broadcastRequest.schema.json, https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/broadcastEvent.schema.json
- context listeners: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/addContextListenerRequest.schema.json, https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/addContextListenerResponse.schema.json
- context unsubscribe: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/contextListenerUnsubscribeRequest.schema.json, https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/contextListenerUnsubscribeResponse.schema.json
- intent listeners: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/addIntentListenerRequest.schema.json, https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/addIntentListenerResponse.schema.json
- intent unsubscribe: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/intentListenerUnsubscribeRequest.schema.json, https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/intentListenerUnsubscribeResponse.schema.json
- raiseIntent: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/raiseIntentRequest.schema.json, https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/raiseIntentResponse.schema.json
- raiseIntentForContext: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/raiseIntentForContextRequest.schema.json, https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/raiseIntentForContextResponse.schema.json
- intentEvent: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/intentEvent.schema.json
- intentResult: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/intentResultRequest.schema.json, https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/intentResultResponse.schema.json
- raiseIntentResultResponse: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/raiseIntentResultResponse.schema.json
- heartbeat: https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/heartbeatEvent.schema.json, https://raw.githubusercontent.com/finos/FDC3/refs/heads/fdc3-for-web/schemas/api/heartbeatAcknowledgmentRequest.schema.json

---

## B. Policy decisions (write down early)

- [ ] Optional: add a local-only control (e.g., config allowlist + per-app key) even though WCP schemas don't define auth fields.

---

## C. WCP implementation (browser connectivity)

Implement WCP message types and validate against the schema shapes.

- [x] Implement WCP flow:
  - [x] Optionally respond with `WCP2LoadUrl` (`iframeUrl`) if needed
  - [x] `WCP5ValidateAppIdentityFailedResponse` (`message`)

- [x] Bind a WCP connection to runtime identity:
  - [x] `appId`
  - [x] `instanceId`
  - [x] `instanceUuid`

---

## D2. FastAPI server (HTTP + WebSocket + GraphQL)

Use FastAPI as the hosting layer for communications.

### WebSocket endpoint (WCP + DACP)

- [x] Implement a single WebSocket endpoint that:
  - [x] Emits DACP `agentResponse` and `agentEvent` messages on the same connection

---

## H. Tests (pytest)

- [x] WCP schema-level tests:
  - [x] validate parsing of WCP1..WCP6 payloads
  - [x] origin rules (`identityUrl` vs `actualUrl`)
- [x] DACP envelope tests:
  - [x] requestUuid/responseUuid/eventUuid correlation
  - [x] error enums only (no invented error objects)
- [x] Core service tests:
  - [x] broadcast validation (`context.type` required)
  - [x] no-echo broadcast policy
  - [x] raiseIntent → intentEvent → intentResultRequest → raiseIntentResultResponse plumbing
- [x] Launcher tests:
  - [x] argv/env expansion from stored config
  - [ ] single-instance-default vs multi-instance override

---

## I. System App Intents

Implement system-level intents that the desktop agent handles directly, providing built-in functionality and fallback behavior.

### System Management Intents
- [x] **App Directory Management**
  - [x] `fdc3.openAppDirectory` - Open app directory management interface
  - [x] `fdc3.manageApps` - Launch app management/configuration UI
  - [x] `fdc3.installApp` - Handle app installation from app directory
  - [x] `fdc3.uninstallApp` - Remove apps from the system

- [x] **System Configuration**
  - [x] `fdc3.systemSettings` - Open system configuration panel
  - [x] `fdc3.configureChannels` - Manage user/system channels
  - [x] `fdc3.systemDiagnostics` - Run system health checks and diagnostics

- [x] **Channel Management**
  - [x] `fdc3.createChannel` - Create new user channels
  - [x] `fdc3.deleteChannel` - Remove user channels
  - [x] `fdc3.manageChannel` - Configure channel settings and membership

### Built-in System Apps
- [x] **Resolver UI**
  - [x] `fdc3.resolveIntent` - Show intent resolver when multiple apps can handle an intent

- [x] **System Browser/File Manager**
  - [x] `fdc3.openUrl` - Launch system browser for URLs
  - [x] `fdc3.openFile` - Launch system file manager for local files
  - [x] `fdc3.systemSearch` - System-wide search functionality

- [x] **System Notifications**
  - [x] `fdc3.showNotification` - Display system notifications
  - [x] `fdc3.systemAlert` - Show system alerts and confirmations

### Implementation Requirements
- [x] Register desktop agent as system app in its own directory
- [x] Create HTML/JS UI components for system interfaces
- [x] Add system intent handlers to server message routing
- [x] Integrate with OS APIs for system operations
- [x] Add system intent resolution logic to IntentResolver
- [x] Test system intent handling and UI components

---

## Notes / open questions

- [ ] Document how WCP (MessagePort-oriented) is carried over a FastAPI WebSocket connection.
- [ ] Decide how `implementationMetadata` will be populated.
- [ ] Decide how to handle `intentResolverUrl` and `channelSelectorUrl` in WCP3Handshake in a desktop-agent-with-browser scenario.
- [ ] Implement launch/listener timing: Allow ≥15s for a launched app to register required listeners (per standard semantics)
- [ ] Add comprehensive error handling for edge cases (malformed messages, connection drops, etc.)
- [ ] Implement instance policy: support multiple instances, default to one instance per app
- [ ] Complete GraphQL endpoint implementation and mounting
