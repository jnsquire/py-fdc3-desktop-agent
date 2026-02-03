import copy
import uuid
import threading
from typing import Dict, List, Optional, Callable, Any, Set
from typing_extensions import TypedDict
import inspect
import json
import asyncio
from datetime import datetime
import logging
from fdc3.models.dacp.dacp import Fdc3Context
from pydantic import BaseModel
from ..distributed.adapter import DistributedLogAdapter
from ..api import DisplayMetadata


logger = logging.getLogger(__name__)


class ChannelEvent(TypedDict):
    event_type: str
    channel_id: str
    instance_uuid: Optional[str]
    context: Optional[str]
    timestamp: str


class EventSubscription(TypedDict):
    callback: Callable[[ChannelEvent], Any]
    channel_filter: Optional[str]


class ChannelInfo(TypedDict):
    id: str
    type: str
    display_name: Optional[str]
    color: Optional[str]
    member_count: int


class PrivateChannelInvite(BaseModel):
    token: str
    instanceId: Optional[str] = None


class PrivateChannelState(TypedDict):
    id: str
    owner: Optional[str]
    members: List[str]
    invites: List[PrivateChannelInvite]


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

    LAST_CONTEXT_KEY = "__last__"

    def __init__(self):
        self.channels: Dict[str, ChannelInstance] = {}  # channel_id -> channel
        self.instance_channels: Dict[
            str, str
        ] = {}  # instance_uuid -> current_channel_id
        self.event_subscriptions: Dict[str, EventSubscription] = {}
        self.private_channel_owners: Dict[str, str] = {}
        self.private_channel_participants: Dict[str, Set[str]] = {}
        self.private_channel_invites: Dict[str, Dict[str, Optional[str]]] = {}
        self.remote_private_channel_listeners: Dict[str, Set[str]] = {}
        self.next_subscription_id = 1
        self.channel_contexts: Dict[str, Dict[str, Fdc3Context]] = {}
        # Optional distributed adapter to relay events across workers
        self.distributed_adapter: Optional[DistributedLogAdapter] = None
        # Lock to serialize access to channel membership and related structures
        self._lock = threading.RLock()

    def create_channel(
        self,
        channel_id: str,
        channel_type: str,
        display_metadata: Optional[DisplayMetadata] = None,
    ) -> ChannelInstance:
        """Create a channel or return the existing channel with the same ID."""
        with self._lock:
            existing = self.channels.get(channel_id)
            if existing is not None:
                logger.info(
                    f"create_channel: channel already exists channel_id={channel_id} obj_id={id(existing)} type={getattr(existing, 'type', None)}"
                )
                return existing

            channel = ChannelInstance(channel_id, channel_type, display_metadata)
            self.channels[channel_id] = channel
            logger.info(
                f"create_channel: created channel_id={channel_id} obj_id={id(channel)} type={channel_type}"
            )

        self._emit_event("created", channel_id)
        return channel

    def delete_channel(self, channel_id: str) -> bool:
        """Delete a channel and clean up all associated state.

        Removes the channel, clears its context, and disassociates any
        instances that were members of the channel.

        Returns:
            True if the channel was deleted, False if it didn't exist.
        """
        with self._lock:
            if channel_id not in self.channels:
                return False

            # Remove the channel
            del self.channels[channel_id]

            # Clear channel context
            self.channel_contexts.pop(channel_id, None)

            # Remove any instance associations with this channel
            instances_to_remove = [
                inst_uuid
                for inst_uuid, ch_id in self.instance_channels.items()
                if ch_id == channel_id
            ]
            for inst_uuid in instances_to_remove:
                del self.instance_channels[inst_uuid]

            # Clean up private channel state if applicable
            self.private_channel_owners.pop(channel_id, None)
            self.private_channel_participants.pop(channel_id, None)
            self.private_channel_invites.pop(channel_id, None)
            self.remote_private_channel_listeners.pop(channel_id, None)

            logger.info(f"delete_channel: deleted channel_id={channel_id}")

        # Emit event outside the lock
        self._emit_event("deleted", channel_id)
        return True

    def create_private_channel(
        self,
        owner_instance_uuid: str,
        channel_id: Optional[str] = None,
        display_metadata: Optional[DisplayMetadata] = None,
    ) -> ChannelInstance:
        """Create a private channel and assign an owner instance."""
        with self._lock:
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
        """Create an invite token for a private channel.

        If instance_uuid is provided, the token is restricted to that instance.
        """
        with self._lock:
            channel = self.get_channel(channel_id)
            if channel is None or channel.type != "private":
                raise ValueError("private channel not found")

            token = uuid.uuid4().hex
            invites = self.private_channel_invites.setdefault(channel_id, {})
            invites[token] = instance_uuid
            return token

    def consume_private_channel_invite(
        self, channel_id: str, token: str, instance_uuid: str
    ) -> bool:
        """Consume an invite token and validate instance access."""
        with self._lock:
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

    def get_private_channel_state(
        self, channel_id: str
    ) -> Optional[PrivateChannelState]:
        """Return the private channel state (owner, members, invites) if valid."""
        channel = self.get_channel(channel_id)
        if channel is None or channel.type != "private":
            return None
        with self._lock:
            invites: List[PrivateChannelInvite] = [
                PrivateChannelInvite(token=token, instanceId=inst)
                for token, inst in self.private_channel_invites.get(
                    channel_id, {}
                ).items()
            ]
            return {
                "id": channel.id,
                "owner": self.private_channel_owners.get(channel_id),
                "members": channel.members.copy(),
                "invites": invites,
            }

    def get_channel(self, channel_id: str) -> Optional[ChannelInstance]:
        """Return a channel instance by ID, if present."""
        with self._lock:
            return self.channels.get(channel_id)

    def join_channel(self, instance_uuid: str, channel_id: str):
        """Join the given channel, leaving the current channel if necessary."""
        left_channel_id: str | None = None
        joined = False
        with self._lock:
            if channel_id in self.channels:
                # Leave current channel
                if instance_uuid in self.instance_channels:
                    old_channel_id = self.instance_channels[instance_uuid]
                    if old_channel_id in self.channels:
                        members = self.channels[old_channel_id].members
                        if instance_uuid in members:
                            members.remove(instance_uuid)
                        left_channel_id = old_channel_id

                # Debug: log members and channel object id before join
                try:
                    before = self.channels[channel_id].members.copy()
                    before_obj_id = id(self.channels[channel_id])
                except Exception:
                    before = None
                    before_obj_id = None
                logger.debug(
                    f"join_channel: instance={instance_uuid} joining {channel_id} before_members={before} before_obj_id={before_obj_id}"
                )

                # Join new channel
                self.channels[channel_id].members.append(instance_uuid)
                self.instance_channels[instance_uuid] = channel_id
                if self.channels[channel_id].type == "private":
                    self.private_channel_participants.setdefault(channel_id, set()).add(
                        instance_uuid
                    )
                # Debug: log members and channel object id after join
                try:
                    after = self.channels[channel_id].members.copy()
                    after_obj_id = id(self.channels[channel_id])
                except Exception:
                    after = None
                    after_obj_id = None
                logger.debug(
                    f"join_channel: instance={instance_uuid} joined {channel_id} after_members={after} after_obj_id={after_obj_id}"
                )

                joined = True

        if left_channel_id is not None:
            self._emit_event("left", left_channel_id, instance_uuid)
        if joined:
            self._emit_event("joined", channel_id, instance_uuid)

    def leave_current_channel(self, instance_uuid: str):
        """Leave the current channel for the given instance, if any."""
        left_channel_id: str | None = None
        with self._lock:
            if instance_uuid in self.instance_channels:
                channel_id = self.instance_channels[instance_uuid]
                # Debug: log members before leave
                try:
                    before = self.channels[channel_id].members.copy()
                except Exception:
                    before = None
                logger.debug(
                    f"leave_current_channel: instance={instance_uuid} leaving {channel_id} before_members={before}"
                )

                if channel_id in self.channels:
                    members = self.channels[channel_id].members
                    if instance_uuid in members:
                        members.remove(instance_uuid)
                    if self.channels[channel_id].type == "private":
                        participants = self.private_channel_participants.get(channel_id)
                        if participants:
                            participants.discard(instance_uuid)
                    left_channel_id = channel_id
                del self.instance_channels[instance_uuid]

                # Debug: log members after leave
                try:
                    after = (
                        self.channels[channel_id].members.copy()
                        if channel_id in self.channels
                        else None
                    )
                except Exception:
                    after = None
                logger.debug(
                    f"leave_current_channel: instance={instance_uuid} left {channel_id} after_members={after}"
                )

        if left_channel_id is not None:
            self._emit_event("left", left_channel_id, instance_uuid)

    def get_current_channel(self, instance_uuid: str) -> Optional[ChannelInstance]:
        """Return the current channel for the instance, if joined."""
        with self._lock:
            channel_id = self.instance_channels.get(instance_uuid)
            if channel_id:
                return self.channels.get(channel_id)
            return None

    def get_channel_members(self, channel_id: str) -> List[str]:
        """Return a list of instance UUIDs currently in the channel."""
        with self._lock:
            if channel_id in self.channels:
                members = self.channels[channel_id].members.copy()
                logger.debug(
                    f"get_channel_members: channel={channel_id} members={members}"
                )
                return members
            logger.debug(f"get_channel_members: channel={channel_id} not found")
            return []

    def list_channels(self) -> List[ChannelInstance]:
        """Return a list of all channels."""
        return list(self.channels.values())

    def get_private_channel_owner(self, channel_id: str) -> Optional[str]:
        """Return the instance UUID that owns the private channel, if any."""
        return self.private_channel_owners.get(channel_id)

    def destroy_private_channel(self, channel_id: str) -> None:
        """Remove all state associated with a private channel."""
        destroyed = False
        with self._lock:
            channel = self.channels.pop(channel_id, None)
            if channel is None:
                return

            self.private_channel_owners.pop(channel_id, None)
            self.private_channel_participants.pop(channel_id, None)
            self.private_channel_invites.pop(channel_id, None)
            self.channel_contexts.pop(channel_id, None)
            self.remote_private_channel_listeners.pop(channel_id, None)

            for instance_uuid in list(channel.members):
                if self.instance_channels.get(instance_uuid) == channel_id:
                    del self.instance_channels[instance_uuid]

            destroyed = True

        if destroyed:
            self._emit_event("destroyed", channel_id)

    def broadcast_to_channel(
        self, channel_id: str, context: Fdc3Context, source_instance_uuid: str
    ):
        """Emit a broadcast event for a channel."""
        should_emit = False
        with self._lock:
            if channel_id in self.channels:
                self.set_channel_context(channel_id, context)
                should_emit = True

        if should_emit:
            self._emit_event("broadcast", channel_id, source_instance_uuid, context)

    def set_channel_context(self, channel_id: str, context: Fdc3Context) -> None:
        """Store the latest context for a channel."""
        if not context or not isinstance(context, dict):
            return

        context_type = context.get("type")
        if not context_type:
            return

        with self._lock:
            stored = self.channel_contexts.setdefault(channel_id, {})
            sanitized = copy.deepcopy(context)
            stored[context_type] = sanitized
            stored[self.LAST_CONTEXT_KEY] = sanitized

    def get_channel_context(
        self, channel_id: str, context_type: Optional[str] = None
    ) -> Optional[Fdc3Context]:
        """Return the latest context for a channel, optionally filtered by type."""
        with self._lock:
            contexts = self.channel_contexts.get(channel_id)
            if not contexts:
                return None

            if context_type is not None:
                return contexts.get(context_type)
            return contexts.get(self.LAST_CONTEXT_KEY)

    def clear_channel_context(self, channel_id: str) -> None:
        """Remove all stored context for a channel."""
        with self._lock:
            self.channel_contexts.pop(channel_id, None)

    def add_remote_private_channel_listener(
        self, channel_id: str, desktop_agent: str
    ) -> None:
        """Track a remote agent interested in a private channel."""
        if not channel_id or not desktop_agent:
            return
        with self._lock:
            self.remote_private_channel_listeners.setdefault(channel_id, set()).add(
                desktop_agent
            )

    def remove_remote_private_channel_listener(
        self, channel_id: str, desktop_agent: str
    ) -> None:
        """Stop tracking a remote agent for a private channel."""
        if not channel_id or not desktop_agent:
            return
        with self._lock:
            listeners = self.remote_private_channel_listeners.get(channel_id)
            if not listeners:
                return
            listeners.discard(desktop_agent)
            if not listeners:
                self.remote_private_channel_listeners.pop(channel_id, None)

    def get_remote_private_channel_listeners(self, channel_id: str) -> Set[str]:
        """Return remote agents listening for the private channel."""
        if not channel_id:
            return set()
        with self._lock:
            return set(self.remote_private_channel_listeners.get(channel_id, set()))

    def get_channel_info(self, channel_id: str) -> Optional[ChannelInfo]:
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
                    channel.display_metadata.color if channel.display_metadata else None
                ),
                "member_count": len(channel.members),
            }
        return None

    def subscribe_to_events(
        self,
        callback: Callable[[ChannelEvent], None],
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
        context: Optional[Fdc3Context] = None,
        remote: bool = False,
    ):
        """Emit an event to all subscribers."""
        event_data: ChannelEvent = {
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

    async def _publish_event(self, event_data: ChannelEvent):
        try:
            adapter = self.distributed_adapter
            if adapter:
                await adapter.publish("channel_events", event_data)
        except Exception:
            # Swallow errors - publishing is best-effort
            return
