# Storage interfaces and implementations

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any


class AppMetadata:
    """App metadata stored in the directory"""

    def __init__(
        self,
        app_id: str,
        name: str,
        version: str = "",
        description: str = "",
        icons: List[Dict[str, Any]] = None,
        intents: List[str] = None,
        allowed_origins: List[str] = None,
    ):
        self.app_id = app_id
        self.name = name
        self.version = version
        self.description = description
        self.icons = icons or []
        self.intents = intents or []
        self.allowed_origins = allowed_origins or []


class LaunchConfig:
    """Launch configuration for an app"""

    def __init__(
        self,
        app_id: str,
        command: str,
        args: List[str] = None,
        env: Dict[str, str] = None,
        cwd: str = "",
        timeout: int = 30,
    ):
        self.app_id = app_id
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.cwd = cwd
        self.timeout = timeout  # seconds to wait for app to register listeners


class AppDirectoryRepository(ABC):
    """Repository for app directory operations"""

    @abstractmethod
    async def get_app_metadata(self, app_id: str) -> Optional[AppMetadata]:
        """Get app metadata by app_id"""
        pass

    @abstractmethod
    async def list_apps(self) -> List[AppMetadata]:
        """List all apps in directory"""
        pass

    @abstractmethod
    async def add_app(self, metadata: AppMetadata) -> None:
        """Add or update app in directory"""
        pass

    @abstractmethod
    async def remove_app(self, app_id: str) -> None:
        """Remove app from directory"""
        pass


class LaunchConfigRepository(ABC):
    """Repository for launch configuration operations"""

    @abstractmethod
    async def get_launch_config(self, app_id: str) -> Optional[LaunchConfig]:
        """Get launch config for app"""
        pass

    @abstractmethod
    async def set_launch_config(self, config: LaunchConfig) -> None:
        """Set launch config for app"""
        pass

    @abstractmethod
    async def remove_launch_config(self, app_id: str) -> None:
        """Remove launch config for app"""
        pass

    @abstractmethod
    async def list_launch_configs(self) -> List[LaunchConfig]:
        """List all launch configs"""
        pass


class Storage(ABC):
    """Main storage interface"""

    @property
    @abstractmethod
    def apps(self) -> AppDirectoryRepository:
        """App directory repository"""
        pass

    @property
    @abstractmethod
    def launch_configs(self) -> LaunchConfigRepository:
        """Launch config repository"""
        pass

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize storage (create tables, etc.)"""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close storage connections"""
        pass
