# FDC3 Spec Gap Checklist (py-fdc3-desktop-agent)

This checklist captures remaining or partial areas vs the FDC3 Desktop Agent API + DACP surface.

## DesktopAgent info/metadata

- [x] Align `implementationMetadata` fields to the FDC3 `ImplementationMetadata` model across surfaces (DACP, WCP, bridging handshake), especially `optionalFeatures` coverage/semantics.
- [x] Ensure `optionalFeatures` correctly reflects `UserChannelMembershipAPIs` + `OriginatingAppMetadata` support.

## App metadata APIs

## Channels

## Events

## Intents

- [ ] Ensure intent resolution includes apps registered to return channels for specific context types.
- [ ] Enforce/ensure launch-time listener wait (minimum 15s) before delivering intent/context to launched targets.

## Desktop Agent Bridging

- [ ] Implement bridging error semantics (`BridgingError.*`, `DesktopAgentNotFound`, `AgentDisconnected`, `errorSources`/`errorDetails`).

## App Directory

- [ ] Support fully-qualified `appId` forms (`appId@host`) where applicable.
- [ ] If external App Directory integration is planned, ensure `/v2/apps` + `/v2/apps/{appId}` compatibility.

## Deprecated APIs

- [ ] Implement deprecated API variants (`addContextListener` without type, deprecated `open`/`raiseIntent` by name).
