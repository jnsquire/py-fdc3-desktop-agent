"""FDC3 Desktop Agent - A Python implementation of the FDC3 Desktop Agent.

This package provides a WebSocket-based FDC3 Desktop Agent that can be run
standalone or embedded in another Python application.

Basic usage (standalone)::

    from fdc3_desktop_agent import create_app

    app = create_app()
    # Run with uvicorn: uvicorn fdc3_desktop_agent:app

Embedding with custom configuration::

    from fdc3_desktop_agent import create_app, DesktopAgentConfig

    config = DesktopAgentConfig(
        host="0.0.0.0",
        port=9000,
        db_path=":memory:",
    )
    app = create_app(config)

Mounting in a larger application::

    from fastapi import FastAPI
    from fdc3_desktop_agent import create_app, DesktopAgentConfig

    main_app = FastAPI()
    main_app.mount("/fdc3", create_app(DesktopAgentConfig(db_path=":memory:")))
"""

__version__ = "0.9.0"

from .config import DesktopAgentConfig
from .server import create_app, app

# Re-export key interfaces for custom implementations
from .storage.interfaces import Storage, AppMetadata, LaunchConfig
from .launcher.interfaces import ProcessLauncher, LaunchResult
from .distributed.adapter import DistributedLogAdapter

__all__ = [
    # Version
    "__version__",
    # Main API
    "create_app",
    "app",
    "DesktopAgentConfig",
    # Interfaces for custom implementations
    "Storage",
    "AppMetadata",
    "LaunchConfig",
    "ProcessLauncher",
    "LaunchResult",
    "DistributedLogAdapter",
]
