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

## H. Tests (pytest)

- [ ] Launcher tests:
  - [ ] single-instance-default vs multi-instance override

---


## Notes / open questions

- [ ] Add comprehensive error handling for edge cases (malformed messages, connection drops, etc.)
