from typing import Dict, List, Optional, Callable, Any
import json
import asyncio
from datetime import datetime
from ..distributed.adapter import DistributedLogAdapter
from ..api import DisplayMetadata


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
        self.next_subscription_id = 1
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

    def get_channel(self, channel_id: str) -> Optional[ChannelInstance]:
        return self.channels.get(channel_id)

    def join_channel(self, instance_uuid: str, channel_id: str):
        if channel_id in self.channels:
            # Leave current channel
            if instance_uuid in self.instance_channels:
                old_channel_id = self.instance_channels[instance_uuid]
                if old_channel_id in self.channels:
                    self.channels[old_channel_id].members.remove(instance_uuid)
                    self._emit_event("left", old_channel_id, instance_uuid)

            # Join new channel
            self.channels[channel_id].members.append(instance_uuid)
            self.instance_channels[instance_uuid] = channel_id
            self._emit_event("joined", channel_id, instance_uuid)

    def leave_current_channel(self, instance_uuid: str):
        if instance_uuid in self.instance_channels:
            channel_id = self.instance_channels[instance_uuid]
            if channel_id in self.channels:
                self.channels[channel_id].members.remove(instance_uuid)
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

    def broadcast_to_channel(
        self, channel_id: str, context: Dict[str, Any], source_instance_uuid: str
    ):
        """Emit a broadcast event for a channel."""
        if channel_id in self.channels:
            self._emit_event("broadcast", channel_id, source_instance_uuid, context)

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
                    subscription["callback"](event_data)
                except Exception as e:
                    # Log error but don't let it break the event emission
                    print(f"Error in channel event callback: {e}")

        # Publish to distributed adapter for cross-worker delivery unless this event
        # originated from the distributed bus (avoid loops).
        if not remote and self.distributed_adapter is not None:
            try:
                asyncio.create_task(self._publish_event(event_data))
            except Exception:
                # Best-effort: do not break local emission if publishing fails
                pass

    async def _publish_event(self, event_data: Dict[str, Any]):
        try:
            adapter = self.distributed_adapter
            if adapter is None:
                return
            await adapter.publish("channel_events", event_data)
        except Exception:
            # Swallow errors - publishing is best-effort
            return
