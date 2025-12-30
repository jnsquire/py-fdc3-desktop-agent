# Embedding API

The FDC3 Desktop Agent can be embedded in other Python applications using the `create_app()` factory function. This allows you to:

- Run the agent alongside your existing FastAPI/Starlette application
- Configure the agent programmatically instead of via environment variables
- Inject custom storage, launcher, or distributed adapter implementations

## Basic Usage

```python
from fdc3.desktop_agent import create_app, DesktopAgentConfig

# Create with default configuration (reads from environment variables)
app = create_app()

# Or with custom configuration
config = DesktopAgentConfig(
    host="0.0.0.0",
    port=9000,
    db_path=":memory:",  # Use in-memory SQLite
    log_level="DEBUG",
)
app = create_app(config)
```

## Mounting in a Larger Application

```python
from fastapi import FastAPI
from fdc3.desktop_agent import create_app, DesktopAgentConfig

# Your main application
main_app = FastAPI(title="My Application")

@main_app.get("/")
def root():
    return {"message": "Hello from main app"}

# Mount the FDC3 agent at /fdc3
fdc3_config = DesktopAgentConfig(db_path="my_app_fdc3.db")
main_app.mount("/fdc3", create_app(fdc3_config))

# Now available:
# - Main app: http://localhost:8000/
# - FDC3 WebSocket: ws://localhost:8000/fdc3/ws
# - FDC3 GraphQL: http://localhost:8000/fdc3/graphql
# - FDC3 Admin: http://localhost:8000/fdc3/admin
```

## Configuration Options

`DesktopAgentConfig` supports the following options:

| Option                  | Type                        | Default              | Description                                                                             |
| ----------------------- | --------------------------- | -------------------- | --------------------------------------------------------------------------------------- |
| `host`                  | `str`                       | `"localhost"`        | Server bind host (also from `FDC3_HOST` env var)                                        |
| `port`                  | `int`                       | `8000`               | Server bind port (also from `FDC3_PORT` env var)                                        |
| `db_path`               | `str`                       | `"fdc3_agent.db"`    | SQLite database path; use `":memory:"` for in-memory (also from `FDC3_DB_PATH` env var) |
| `log_level`             | `str`                       | `"INFO"`             | Logging level (also from `FDC3_LOG_LEVEL` env var)                                      |
| `allowed_origins`       | `List[str]`                 | `["localhost", ...]` | Origins allowed to connect via WebSocket                                                |
| `agent_url`             | `str`                       | `None`               | WebSocket URL for launched apps; if `None`, computed from host/port                     |
| `bridge_enabled`         | `bool`                      | `False`              | Enable Desktop Agent Bridging (also from `FDC3_BRIDGE_ENABLED`)                         |
| `bridge_host`            | `str`                       | `"127.0.0.1"`        | Bridge host (also from `FDC3_BRIDGE_HOST`)                                              |
| `bridge_port_start`      | `int`                       | `4475`               | Bridge discovery start port (also from `FDC3_BRIDGE_PORT_START`)                        |
| `bridge_port_end`        | `int`                       | `4575`               | Bridge discovery end port (also from `FDC3_BRIDGE_PORT_END`)                            |
| `bridge_requested_name`  | `str`                       | hostname             | Requested Desktop Agent name (also from `FDC3_BRIDGE_REQUESTED_NAME`)                   |
| `bridge_connect_retry_seconds` | `float`              | `5`                  | Retry delay after discovery failure (also from `FDC3_BRIDGE_CONNECT_RETRY_SECONDS`)     |
| `bridge_request_timeout_seconds` | `float`            | `3`                  | Request timeout (also from `FDC3_BRIDGE_REQUEST_TIMEOUT_SECONDS`)                       |
| `storage`               | `Storage`                   | `None`               | Custom storage implementation; if `None`, uses `SqliteStorage`                          |
| `launcher`              | `ProcessLauncher`           | `None`               | Custom process launcher; if `None`, uses `SubprocessLauncher`                           |
| `distributed_adapter`   | `DistributedLogAdapter`     | `None`               | Custom distributed adapter; if `None`, uses factory based on env var                    |
| `plugins`               | `List[IntentHandlerPlugin]` | `[]`                 | Intent handler plugins to register at startup                                           |
| `auto_discover_plugins` | `bool`                      | `True`               | Discover plugins from entry points (also from `FDC3_AUTO_DISCOVER_PLUGINS` env var)     |

## Custom Implementations

You can provide custom implementations of the core interfaces:

```python
from fdc3.desktop_agent import create_app, DesktopAgentConfig, Storage, ProcessLauncher

class MyCustomStorage(Storage):
    # Implement Storage interface methods
    ...

class MyCustomLauncher(ProcessLauncher):
    # Implement ProcessLauncher interface methods
    ...

config = DesktopAgentConfig(
    storage=MyCustomStorage(),
    launcher=MyCustomLauncher(),
)
app = create_app(config)
```

## Exported Interfaces

The package exports these interfaces for custom implementations:

```python
from fdc3.desktop_agent import (
    # Main API
    create_app,
    app,  # Default app instance
    DesktopAgentConfig,

    # Interfaces
    Storage,           # Abstract storage interface
    AppMetadata,       # App directory entry
    LaunchConfig,      # App launch configuration
    ProcessLauncher,   # Process launcher interface
    LaunchResult,      # Launch operation result
    DistributedLogAdapter,  # Distributed event adapter

    # Plugin API
    IntentHandlerPlugin,      # Base class for custom intent handlers
    IntentHandlerResult,      # Result of intent handling
    PluginRegistry,           # Plugin registration manager
    discover_plugins,         # Discover plugins from entry points
    list_plugin_entry_points, # List available entry points
    PLUGIN_ENTRY_POINT_GROUP, # Entry point group name
)
```
