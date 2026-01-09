import copy
import uuid
from typing import Dict, List, Optional, Callable, Any, Set
import inspect
import json
import asyncio
from datetime import datetime
import logging
from ..distributed.adapter import DistributedLogAdapter
from ..api import DisplayMetadata


logger = logging.getLogger(__name__)


class ChannelInstance:
    def __init__(
        self,
        channel_id: str,
        channel_type: str,
        display_metadata: Optional[DisplayMetadata] = None,
    ):
        self.id = channel_id
        self.type = channel_type
        self.display_metadata = display_metadata
        self.members: List[str] = []  # instance_uuids


class ChannelManager:
    """Manages user/app/private channels and joined channel per instance."""

    def __init__(self):
        self.channels: Dict[str, ChannelInstance] = {}  # channel_id -> channel
        self.instance_channels: Dict[
            str, str
        ] = {}  # instance_uuid -> current_channel_id
        self.event_subscriptions: Dict[
            str, Dict[str, Any]
        ] = {}  # subscription_id -> subscription info
        self.private_channel_owners: Dict[str, str] = {}
        self.private_channel_participants: Dict[str, Set[str]] = {}
        self.private_channel_invites: Dict[str, Dict[str, Optional[str]]] = {}
        self.next_subscription_id = 1
        self.channel_contexts: Dict[str, Dict[str, dict]] = {}
        # Optional distributed adapter to relay events across workers
        self.distributed_adapter: Optional[DistributedLogAdapter] = None

    def create_channel(
        self,
        channel_id: str,
        channel_type: str,
        display_metadata: Optional[DisplayMetadata] = None,
    ) -> ChannelInstance:
        channel = ChannelInstance(channel_id, channel_type, display_metadata)
        self.channels[channel_id] = channel
        self._emit_event("created", channel_id)
        return channel

    def create_private_channel(
        self,
        owner_instance_uuid: str,
        channel_id: Optional[str] = None,
        display_metadata: Optional[DisplayMetadata] = None,
    ) -> ChannelInstance:
        assigned_id = channel_id or f"private:{uuid.uuid4()}"
        if assigned_id in self.channels:
            raise ValueError("channel already exists")

        channel = self.create_channel(assigned_id, "private", display_metadata)
        channel.members.append(owner_instance_uuid)
        self.private_channel_owners[assigned_id] = owner_instance_uuid
        self.private_channel_participants[assigned_id] = {owner_instance_uuid}
        self.private_channel_invites.pop(assigned_id, None)
        return channel

    def create_private_channel_invite(
        self,
        channel_id: str,
        instance_uuid: Optional[str] = None,
    ) -> str:
        channel = self.get_channel(channel_id)
        if channel is None or getattr(channel, "type", None) != "private":
            raise ValueError("private channel not found")

        token = uuid.uuid4().hex
        invites = self.private_channel_invites.setdefault(channel_id, {})
        invites[token] = instance_uuid
        return token

    def consume_private_channel_invite(
        self, channel_id: str, token: str, instance_uuid: str
    ) -> bool:
        invites = self.private_channel_invites.get(channel_id)
        if not invites or token not in invites:
            return False

        allowed_instance = invites[token]
        if allowed_instance is not None and allowed_instance != instance_uuid:
            return False

        del invites[token]
        if not invites:
            self.private_channel_invites.pop(channel_id, None)
        return True

    def get_private_channel_state(self, channel_id: str) -> Optional[Dict[str, Any]]:
        channel = self.get_channel(channel_id)
        if channel is None or getattr(channel, "type", None) != "private":
            return None

        return {
            "id": channel.id,
            "owner": self.private_channel_owners.get(channel_id),
            "members": channel.members.copy(),
            "invites": [
                {"token": token, "instanceId": inst}
                for token, inst in self.private_channel_invites.get(
                    channel_id, {}
                ).items()
            ],
        }

    def get_channel(self, channel_id: str) -> Optional[ChannelInstance]:
        return self.channels.get(channel_id)

    def join_channel(self, instance_uuid: str, channel_id: str):
        if channel_id in self.channels:
            # Leave current channel
            if instance_uuid in self.instance_channels:
                old_channel_id = self.instance_channels[instance_uuid]
                if old_channel_id in self.channels:
                    members = self.channels[old_channel_id].members
                    if instance_uuid in members:
                        members.remove(instance_uuid)
                    self._emit_event("left", old_channel_id, instance_uuid)

            # Join new channel
            self.channels[channel_id].members.append(instance_uuid)
            self.instance_channels[instance_uuid] = channel_id
            if getattr(self.channels[channel_id], "type", None) == "private":
                self.private_channel_participants.setdefault(channel_id, set()).add(
                    instance_uuid
                )
            self._emit_event("joined", channel_id, instance_uuid)

    def leave_current_channel(self, instance_uuid: str):
        if instance_uuid in self.instance_channels:
            channel_id = self.instance_channels[instance_uuid]
            if channel_id in self.channels:
                members = self.channels[channel_id].members
                if instance_uuid in members:
                    members.remove(instance_uuid)
                if getattr(self.channels[channel_id], "type", None) == "private":
                    participants = self.private_channel_participants.get(channel_id)
                    if participants:
                        participants.discard(instance_uuid)
                self._emit_event("left", channel_id, instance_uuid)
            del self.instance_channels[instance_uuid]

    def get_current_channel(self, instance_uuid: str) -> Optional[ChannelInstance]:
        channel_id = self.instance_channels.get(instance_uuid)
        if channel_id:
            return self.channels.get(channel_id)
        return None

    def get_channel_members(self, channel_id: str) -> List[str]:
        if channel_id in self.channels:
            return self.channels[channel_id].members.copy()
        return []

    def list_channels(self) -> List[ChannelInstance]:
        return list(self.channels.values())

    def get_private_channel_owner(self, channel_id: str) -> Optional[str]:
        return self.private_channel_owners.get(channel_id)

    def destroy_private_channel(self, channel_id: str) -> None:
        channel = self.channels.pop(channel_id, None)
        if channel is None:
            return

        self.private_channel_owners.pop(channel_id, None)
        self.private_channel_participants.pop(channel_id, None)
        self.private_channel_invites.pop(channel_id, None)
        self.channel_contexts.pop(channel_id, None)

        for instance_uuid in list(channel.members):
            if self.instance_channels.get(instance_uuid) == channel_id:
                del self.instance_channels[instance_uuid]

        self._emit_event("destroyed", channel_id)

    def broadcast_to_channel(
        self, channel_id: str, context: Dict[str, Any], source_instance_uuid: str
    ):
        """Emit a broadcast event for a channel."""
        if channel_id in self.channels:
            self.set_channel_context(channel_id, context)
            self._emit_event("broadcast", channel_id, source_instance_uuid, context)

    def set_channel_context(self, channel_id: str, context: Dict[str, Any]) -> None:
        if not context or not isinstance(context, dict):
            return

        context_type = context.get("type")
        if not context_type:
            return

        stored = self.channel_contexts.setdefault(channel_id, {})
        sanitized = copy.deepcopy(context)
        stored[context_type] = sanitized
        stored["__last__"] = sanitized

    def get_channel_context(
        self, channel_id: str, context_type: Optional[str] = None
    ) -> Optional[dict]:
        contexts = self.channel_contexts.get(channel_id)
        if not contexts:
            return None

        if context_type is not None:
            return contexts.get(context_type)
        return contexts.get("__last__")

    def clear_channel_context(self, channel_id: str) -> None:
        self.channel_contexts.pop(channel_id, None)

    def get_channel_info(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """Get channel information for GraphQL queries."""
        channel = self.get_channel(channel_id)
        if channel:
            return {
                "id": channel.id,
                "type": channel.type,
                "display_name": (
                    channel.display_metadata.name if channel.display_metadata else None
                ),
                "color": (
                    getattr(channel.display_metadata, "color", None)
                    if channel.display_metadata
                    else None
                ),
                "member_count": len(channel.members),
            }
        return None

    def subscribe_to_events(
        self,
        callback: Callable[[Dict[str, Any]], None],
        channel_filter: Optional[str] = None,
    ) -> str:
        """Subscribe to channel events. Returns subscription ID."""
        subscription_id = f"sub_{self.next_subscription_id}"
        self.next_subscription_id += 1

        self.event_subscriptions[subscription_id] = {
            "callback": callback,
            "channel_filter": channel_filter,
        }

        return subscription_id

    def unsubscribe_from_events(self, subscription_id: str):
        """Unsubscribe from channel events."""
        if subscription_id in self.event_subscriptions:
            del self.event_subscriptions[subscription_id]

    def _emit_event(
        self,
        event_type: str,
        channel_id: str,
        instance_uuid: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        remote: bool = False,
    ):
        """Emit an event to all subscribers."""
        event_data = {
            "event_type": event_type,
            "channel_id": channel_id,
            "instance_uuid": instance_uuid,
            "context": json.dumps(context) if context else None,
            "timestamp": datetime.now().isoformat(),
        }

        for subscription in self.event_subscriptions.values():
            channel_filter = subscription["channel_filter"]
            if channel_filter is None or channel_filter == channel_id:
                try:
                    result = subscription["callback"](event_data)
                    if inspect.isawaitable(result):
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(result)
                        except RuntimeError:
                            # No running loop in this thread; try thread-safe scheduling
                            try:
                                asyncio.get_event_loop().call_soon_threadsafe(
                                    asyncio.create_task, result
                                )
                            except Exception:
                                if inspect.iscoroutine(result):
                                    result.close()
                                logger.exception(
                                    "Failed to schedule async channel callback"
                                )
                except Exception:
                    logger.exception("Error in channel event callback")

        # Publish to distributed adapter for cross-worker delivery unless this event
        # originated from the distributed bus (avoid loops).
        if not remote and self.distributed_adapter is not None:
            try:
                from ..tools import create_task_safe

                coro = self._publish_event(event_data)
                try:
                    create_task_safe(coro)
                except Exception:
                    coro.close()
                    raise
            except Exception:
                # Best-effort: do not break local emission if publishing fails
                logger.exception("Failed to schedule distributed publish task")

    async def _publish_event(self, event_data: Dict[str, Any]):
        try:
            adapter = self.distributed_adapter
            if adapter:
                await adapter.publish("channel_events", event_data)
        except Exception:
            # Swallow errors - publishing is best-effort
            return
