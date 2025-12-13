"""Configuration for the FDC3 Desktop Agent.

This module provides the `DesktopAgentConfig` dataclass used to configure
the agent when embedding it in another Python application.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from .distributed.adapter import DistributedLogAdapter
    from .launcher.interfaces import ProcessLauncher
    from .storage.interfaces import Storage


def _default_allowed_origins() -> List[str]:
    """Get allowed origins from environment or use localhost defaults."""
    env_origins = os.getenv("FDC3_ALLOWED_ORIGINS")
    if env_origins:
        return env_origins.split(",")
    return ["localhost", "127.0.0.1", "localhost:*", "127.0.0.1:*"]


@dataclass
class DesktopAgentConfig:
    """Configuration for the FDC3 Desktop Agent.

    All fields have sensible defaults, allowing you to create a minimal
    configuration with just ``DesktopAgentConfig()``.

    When embedding the agent, you can override any field::

        config = DesktopAgentConfig(
            host="0.0.0.0",
            port=9000,
            db_path=":memory:",
        )
        app = create_app(config)

    You can also inject custom implementations of storage, launcher, or
    distributed adapter::

        config = DesktopAgentConfig(
            storage=MyCustomStorage(),
            launcher=MyCustomLauncher(),
        )
    """

    # Network settings
    host: str = field(default_factory=lambda: os.getenv("FDC3_HOST", "localhost"))
    port: int = field(default_factory=lambda: int(os.getenv("FDC3_PORT", "8000")))

    # Storage settings
    db_path: str = field(
        default_factory=lambda: os.getenv("FDC3_DB_PATH", "fdc3_agent.db")
    )

    # Logging
    log_level: str = field(default_factory=lambda: os.getenv("FDC3_LOG_LEVEL", "INFO"))

    # Access control
    allowed_origins: List[str] = field(default_factory=_default_allowed_origins)

    # Optional custom implementations (if None, defaults are used)
    storage: Optional["Storage"] = None
    launcher: Optional["ProcessLauncher"] = None
    distributed_adapter: Optional["DistributedLogAdapter"] = None

    # Agent WebSocket URL (used by launched apps to connect back)
    # If None, computed from host/port
    agent_url: Optional[str] = None

    @property
    def computed_agent_url(self) -> str:
        """Return the agent WebSocket URL, computing from host/port if not set."""
        if self.agent_url:
            return self.agent_url
        return f"ws://{self.host}:{self.port}/ws"

    @property
    def templates_dir(self) -> Path:
        """Return the path to the templates directory."""
        return Path(__file__).parent / "templates"
