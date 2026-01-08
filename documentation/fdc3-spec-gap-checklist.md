# FDC3 Spec Gap Checklist (py-fdc3-desktop-agent)

This checklist captures remaining or partial areas vs the FDC3 Desktop Agent API + DACP surface.

## DesktopAgent info/metadata

- [x] Add a DACP-level `getInfo` (or equivalent) request/response for local apps.
- [ ] Align `implementationMetadata` fields to the FDC3 `ImplementationMetadata` model across surfaces (DACP, WCP, bridging handshake), especially `optionalFeatures` coverage/semantics.

## App metadata APIs

- [x] Add a DACP-level `getAppMetadata` request for local apps.

## Channels

- [ ] Implement private channel APIs (create/join/leave + any required invitations/handshake semantics).
- [ ] Implement channel-object semantics exposed to apps (e.g., `getCurrentContext()` behavior), not just DesktopAgent membership.

## Events

- [x] Implement DesktopAgent event listener APIs (add/remove) and emit `USER_CHANNEL_CHANGED` events.
- [x] Map internal channel membership changes to the FDC3 `USER_CHANNEL_CHANGED` event payload.

## Intents

- [ ] Improve `raiseIntentForContext` to respect context↔intent compatibility and resolver behavior.
- [ ] Improve `findIntentsByContext` to return spec-meaningful results (or documented limitations).

## Desktop Agent Bridging

- [ ] Populate `channelsState` during bridge handshake (currently empty by default; no channel state sync).
- [ ] Implement cross-agent channel behaviors (and private channel bridging flows, if required).
- [x] Bridge `getAppMetadataRequest`/`getAppMetadataResponse`.
- [ ] Bridge event listener APIs / `fdc3Event` delivery.
