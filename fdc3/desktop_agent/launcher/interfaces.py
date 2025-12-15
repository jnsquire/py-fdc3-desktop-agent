# Process launcher interfaces and implementations

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from ..api import AppIdentifier
from ..storage import LaunchConfig


class LaunchResult:
    """Result of a launch operation"""

    def __init__(
        self,
        success: bool,
        instance_id: Optional[str] = None,
        instance_uuid: Optional[str] = None,
        error: Optional[str] = None,
    ):
        self.success = success
        self.instance_id = instance_id
        self.instance_uuid = instance_uuid
        self.error = error


class ProcessLauncher(ABC):
    """Interface for launching app processes"""

    @abstractmethod
    async def launch_app(
        self,
        app_id: str,
        launch_config: LaunchConfig,
        context: Optional[Dict[str, Any]] = None,
        target: Optional[AppIdentifier] = None,
    ) -> LaunchResult:
        """Launch an app process with the given configuration"""
        pass

    @abstractmethod
    async def terminate_app(self, instance_uuid: str) -> bool:
        """Terminate a running app instance"""
        pass

    @abstractmethod
    async def is_app_running(self, instance_uuid: str) -> bool:
        """Check if an app instance is still running"""
        pass

    @abstractmethod
    async def wait_for_app_exit(
        self, instance_uuid: str, timeout: Optional[float] = None
    ) -> bool:
        """Wait for an app instance to exit. Returns True if it exited, False if timeout."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Clean up launcher resources (terminate all running processes, etc.)."""
        pass
