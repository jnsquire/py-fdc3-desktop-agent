from typing import List
from .listener_store import ListenerStore
from .channel_manager import ChannelManager
from .app_registry import AppRegistry


class ContextRouter:
    """Handles broadcast routing, context validation, and avoids echo."""

    def __init__(
        self,
        listener_store: ListenerStore,
        channel_manager: ChannelManager,
        app_registry: AppRegistry,
    ):
        self.listener_store = listener_store
        self.channel_manager = channel_manager
        self.app_registry = app_registry

    def broadcast_context(self, context: dict, source_instance_uuid: str) -> List[str]:
        """Broadcast context to all relevant listeners, avoiding echo. Returns list of target instance_uuids."""
        targets = set()

        # Get context type
        context_type = context.get("type")
        if not context_type:
            raise ValueError("Context must have a 'type' field")

        # Find context listeners
        current_channel = self.channel_manager.get_current_channel(source_instance_uuid)
        channel_id: str | None = None
        if current_channel:
            channel_id = current_channel.id
            self.channel_manager.set_channel_context(channel_id, context)

        listeners = self.listener_store.get_context_listeners_for_type(
            context_type, channel_id=channel_id, include_global=True
        )
        for listener in listeners:
            if listener.instance_uuid != source_instance_uuid:  # Avoid echo
                targets.add(listener.instance_uuid)

        # Also broadcast to current channel members
        current_channel = self.channel_manager.get_current_channel(source_instance_uuid)
        if current_channel:
            for member_uuid in current_channel.members:
                if member_uuid != source_instance_uuid:
                    targets.add(member_uuid)

            # Emit broadcast event for the channel
            self.channel_manager.broadcast_to_channel(
                current_channel.id, context, source_instance_uuid
            )

        return list(targets)
