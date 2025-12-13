from typing import Dict, List, Optional
import asyncio
from ..api import AppMetadata


class AppInstance:
    def __init__(self, app_id: str, instance_id: str, instance_uuid: str):
        self.app_id = app_id
        self.instance_id = instance_id
        self.instance_uuid = instance_uuid
        self.metadata: Optional[AppMetadata] = None
        self.channels: List[str] = []  # joined channels
        self.connected = False  # whether the instance has connected via WCP


class AppRegistry:
    """Manages runtime app instances and their capabilities."""

    def __init__(self):
        self.instances: Dict[str, AppInstance] = {}  # instance_uuid -> instance
        self._connection_events: Dict[str, asyncio.Event] = (
            {}
        )  # instance_uuid -> connection event

    def register_pending_instance(
        self, app_id: str, instance_id: str, instance_uuid: str
    ) -> AppInstance:
        """Register an instance that has been launched but hasn't connected yet"""
        instance = AppInstance(app_id, instance_id, instance_uuid)
        instance.connected = False
        self.instances[instance_uuid] = instance
        self._connection_events[instance_uuid] = asyncio.Event()
        return instance

    def register_instance(
        self, app_id: str, instance_id: str, instance_uuid: str
    ) -> AppInstance:
        """Register a fully connected instance"""
        instance = self.instances.get(instance_uuid)
        if instance:
            # Update existing pending instance
            instance.connected = True
            # Set the connection event
            if instance_uuid in self._connection_events:
                self._connection_events[instance_uuid].set()
        else:
            # Create new instance
            instance = AppInstance(app_id, instance_id, instance_uuid)
            instance.connected = True
            self.instances[instance_uuid] = instance
            # For new connected instances, set event immediately
            if instance_uuid not in self._connection_events:
                self._connection_events[instance_uuid] = asyncio.Event()
            self._connection_events[instance_uuid].set()
        return instance

    def get_instance(self, instance_uuid: str) -> Optional[AppInstance]:
        return self.instances.get(instance_uuid)

    def unregister_instance(self, instance_uuid: str):
        if instance_uuid in self.instances:
            del self.instances[instance_uuid]
        if instance_uuid in self._connection_events:
            del self._connection_events[instance_uuid]

    def get_instances_for_app(self, app_id: str) -> List[AppInstance]:
        return [inst for inst in self.instances.values() if inst.app_id == app_id]

    def get_connected_instances_for_app(self, app_id: str) -> List[AppInstance]:
        return [
            inst
            for inst in self.instances.values()
            if inst.app_id == app_id and inst.connected
        ]

    async def wait_for_instance_connection(
        self, instance_uuid: str, timeout: Optional[float] = None
    ) -> bool:
        """Wait for an instance to connect. Returns True if connected, False if timeout."""
        if instance_uuid not in self._connection_events:
            return False  # Instance doesn't exist

        instance = self.instances.get(instance_uuid)
        if instance and instance.connected:
            return True  # Already connected

        try:
            await asyncio.wait_for(
                self._connection_events[instance_uuid].wait(), timeout=timeout
            )
            return True
        except asyncio.TimeoutError:
            return False

    def list_instances(self) -> List[AppInstance]:
        return list(self.instances.values())
