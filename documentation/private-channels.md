# Private Channel APIs

Private channels team up secure conversations between a small set of apps. The agent already emits lifecycle events for private channels, and the following APIs let owners create channels, hand out invitations, and enforce channel-scoped membership.

## Creating a private channel

Use `createPrivateChannel` exactly as before: the caller becomes the owner, receives a channelId, and automatically joins the membership list. The channel manager tracks the owner, active members, and invitation metadata via `get_private_channel_state(channelId)` so bridging clients or CLI tooling can inspect who belongs or who has been invited.

## Invitation handshake

Owners must explicitly invite other participants before they are allowed to join. Call `createPrivateChannelInvitation` with the `channelId` (and optionally the `instanceId` you expect to accept the invite) to obtain a one-time `invitationToken`:

```json
{
  "type": "createPrivateChannelInvitation",
  "payload": { "channelId": "private:abc123", "instanceId": "participant-1" },
  "meta": { "requestUuid": "r-invite" }
}
```

The response contains the token that the invited app must present when joining:

```json
{
  "type": "createPrivateChannelInvitationResponse",
  "payload": { "invitationToken": "d6a8a4f4-..." },
  "meta": { "requestUuid": "r-invite" }
}
```

## Joining with an invitation

`joinPrivateChannel` now requires the `invitationToken` for anyone who is not the channel owner. That token is consumed on the first successful join, so it cannot be reused:

```json
{
  "type": "joinPrivateChannel",
  "payload": {
    "channelId": "private:abc123",
    "invitationToken": "d6a8a4f4-..."
  },
  "meta": { "requestUuid": "r-join" }
}
```

If the caller supplies an invalid, missing, or instance-scoped token, the agent responds with `AccessDenied`. Owners can still join without a token because they already own the space.

## Leaving and lifecycle

Participants leave via `leavePrivateChannel` (same as before). Private channel events—`onAddContextListener`, `onDisconnect`, etc.—continue to fire so tooling can track membership changes.

## Inspecting channel state

`ChannelManager.get_private_channel_state(channelId)` returns the owner, current members, and outstanding invites, making it easy for bridge clients or CLI helpers to surface invitation tokens or membership snapshots when needed.
