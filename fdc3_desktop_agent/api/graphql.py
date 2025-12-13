import strawberry
from typing import List, Optional, AsyncGenerator
import asyncio
import logging

# Import storage types
from ..storage.interfaces import Storage as StorageInterface
from ..core import core_services

# Global storage instance - will be set by the server
_storage: Optional[StorageInterface] = None


def set_graphql_storage(storage_instance: StorageInterface):
    """Set the storage instance for GraphQL queries"""
    global _storage
    _storage = storage_instance


# Simple GraphQL types for admin/observability
@strawberry.type
class IconType:
    src: str
    size: Optional[str]
    type: Optional[str]


@strawberry.type
class EnvVarType:
    key: str
    value: str


@strawberry.type
class AppMetadataType:
    app_id: str
    name: Optional[str]
    version: Optional[str]
    description: Optional[str]
    icons: List[IconType]  # List of icon objects
    intents: List[str]


@strawberry.type
class LaunchConfigType:
    app_id: str
    command: str
    args: List[str]
    env: List[EnvVarType]  # Environment variables as key-value pairs
    cwd: str
    timeout: int


@strawberry.input
class EnvVarInput:
    key: str
    value: str


@strawberry.input
class LaunchConfigInput:
    app_id: str
    command: str
    args: List[str]
    env: List[EnvVarInput]  # Environment variables as key-value pairs
    cwd: str
    timeout: int


@strawberry.type
class AppInstanceType:
    app_id: str
    instance_id: str
    instance_uuid: str
    connected: bool
    channels: List[str]


@strawberry.type
class ChannelEventType:
    event_type: str  # "joined", "left", "broadcast", "created", "deleted"
    channel_id: str
    instance_uuid: Optional[str]
    context: Optional[str]  # JSON string of context data
    timestamp: str


@strawberry.type
class ChannelType:
    id: str
    type: str  # "user", "app", "private"
    display_name: Optional[str]
    color: Optional[str]
    member_count: int


# Define the GraphQL schema
@strawberry.type
class Query:
    @strawberry.field
    async def apps(self) -> List[AppMetadataType]:
        """List all apps in the app directory"""
        if _storage is None:
            return []
        try:
            apps = await _storage.apps.list_apps()
            return [
                AppMetadataType(
                    app_id=app.app_id,
                    name=app.name,
                    version=app.version,
                    description=app.description,
                    icons=[
                        IconType(
                            src=icon.get("src", ""),
                            size=icon.get("size"),
                            type=icon.get("type"),
                        )
                        for icon in app.icons
                    ],
                    intents=app.intents,
                )
                for app in apps
            ]
        except Exception:
            return []

    @strawberry.field
    async def launch_configs(self) -> List[LaunchConfigType]:
        """List all launch configurations"""
        if _storage is None:
            return []
        try:
            configs = await _storage.launch_configs.list_launch_configs()
            return [
                LaunchConfigType(
                    app_id=config.app_id,
                    command=config.command,
                    args=config.args,
                    env=[EnvVarType(key=k, value=v) for k, v in config.env.items()],
                    cwd=config.cwd,
                    timeout=config.timeout,
                )
                for config in configs
            ]
        except Exception:
            return []

    @strawberry.field
    def instances(self) -> List[AppInstanceType]:
        """List all running app instances"""
        instances = core_services.app_registry.list_instances()
        return [
            AppInstanceType(
                app_id=instance.app_id,
                instance_id=instance.instance_id,
                instance_uuid=instance.instance_uuid,
                connected=instance.connected,
                channels=instance.channels,
            )
            for instance in instances
        ]

    @strawberry.field
    def channels(self) -> List[ChannelType]:
        """List all channels"""
        if not hasattr(core_services, "channel_manager"):
            return []

        channels = core_services.channel_manager.list_channels()
        return [
            ChannelType(
                id=channel.id,
                type=channel.type,
                display_name=(
                    channel.display_metadata.name if channel.display_metadata else None
                ),
                color=(
                    getattr(channel.display_metadata, "color", None)
                    if channel.display_metadata
                    else None
                ),
                member_count=len(channel.members),
            )
            for channel in channels
        ]

    @strawberry.field
    def version(self) -> str:
        """Version information"""
        return "0.1.0"


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def create_launch_config(self, config: LaunchConfigInput) -> LaunchConfigType:
        """Create or update a launch configuration"""
        if _storage is None:
            raise Exception("Storage not initialized")

        # Convert input to LaunchConfig
        from ..storage.interfaces import LaunchConfig

        launch_config = LaunchConfig(
            app_id=config.app_id,
            command=config.command,
            args=config.args,
            env={env_var.key: env_var.value for env_var in config.env},
            cwd=config.cwd,
            timeout=config.timeout,
        )

        await _storage.launch_configs.set_launch_config(launch_config)

        # Return the created config
        return LaunchConfigType(
            app_id=config.app_id,
            command=config.command,
            args=config.args,
            env=[
                EnvVarType(key=env_var.key, value=env_var.value)
                for env_var in config.env
            ],
            cwd=config.cwd,
            timeout=config.timeout,
        )

    @strawberry.mutation
    async def delete_launch_config(self, app_id: str) -> bool:
        """Delete a launch configuration"""
        if _storage is None:
            raise Exception("Storage not initialized")

        await _storage.launch_configs.remove_launch_config(app_id)
        return True


@strawberry.type
class Subscription:
    @strawberry.subscription
    async def channel_events(
        self, channel_id: Optional[str] = None
    ) -> AsyncGenerator[ChannelEventType, None]:
        """Subscribe to channel events. If channel_id is provided, only events for that channel."""
        # Create a queue for this subscription
        queue = asyncio.Queue()

        # Subscribe to channel events
        def event_callback(event_data):
            try:
                queue.put_nowait(event_data)
            except asyncio.QueueFull:
                logging.warning("Channel event queue full, dropping event")

        # Register the callback with the channel manager
        if hasattr(core_services, "channel_manager") and hasattr(
            core_services.channel_manager, "subscribe_to_events"
        ):
            subscription_id = core_services.channel_manager.subscribe_to_events(
                event_callback, channel_id
            )

            try:
                while True:
                    # Wait for events
                    event_data = await queue.get()
                    yield ChannelEventType(**event_data)
            finally:
                # Unsubscribe when the subscription ends
                if hasattr(core_services.channel_manager, "unsubscribe_from_events"):
                    core_services.channel_manager.unsubscribe_from_events(
                        subscription_id
                    )
        else:
            # If channel manager doesn't support subscriptions yet, yield a placeholder
            logging.warning("Channel manager does not support event subscriptions")
            yield ChannelEventType(
                event_type="system",
                channel_id="system",
                instance_uuid=None,
                context='{"message": "Channel event subscriptions not yet implemented"}',
                timestamp=str(asyncio.get_event_loop().time()),
            )


schema = strawberry.Schema(query=Query, mutation=Mutation, subscription=Subscription)
