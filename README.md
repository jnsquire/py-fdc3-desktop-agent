# FDC3 Desktop Agent (Python)

A Python implementation of an FDC3 Desktop Agent with WebSocket support for browser app connections.

## Quick Start

```bash
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python -m pytest
```

## Configuration

The agent can be configured via environment variables:

- `FDC3_HOST`: Server host (default: `localhost`)
- `FDC3_PORT`: Server port (default: `8000`)
- `FDC3_DB_PATH`: SQLite database path (default: `fdc3_agent.db`)
- `FDC3_LOG_LEVEL`: Logging level (default: `INFO`)
- `FDC3_ALLOWED_ORIGINS`: Comma-separated list of allowed origins for WebSocket connections

### Origin Whitelist

By default, the agent allows connections from localhost origins:

- `localhost`
- `127.0.0.1`
- `localhost:*` (any port)
- `127.0.0.1:*` (any port)

To allow connections from specific domains, set `FDC3_ALLOWED_ORIGINS`:

```bash
export FDC3_ALLOWED_ORIGINS="localhost,127.0.0.1,example.com"
```

To allow all origins (not recommended for production):

```bash
export FDC3_ALLOWED_ORIGINS="*"
```

## Running the Agent

The agent can be started in different modes using uv run:

### Development Mode (with auto-reload)

```bash
uv run uvicorn fdc3.desktop_agent.server:app --host localhost --port 8000 --reload --log-level info
```

### Production Mode (multi-worker)

```bash
uv run uvicorn fdc3.desktop_agent.server:app --host 0.0.0.0 --port 8000 --workers 4 --log-level warning
```

### Debug Mode (verbose logging)

```bash
uv run uvicorn fdc3.desktop_agent.server:app --host localhost --port 8000 --reload --log-level debug
```

### Running Tests

```bash
uv run python -m pytest tests/ -v
```

### Quick Development Start

```bash
uv run uvicorn fdc3.desktop_agent.server:app --reload
```

## Distributed Adapters (optional)

This project supports optional distributed log adapters to relay channel events across multiple agent
workers. Adapters are optional and require extra dependencies which are not installed by default.

- Select adapter with environment variable `FDC3_DISTRIBUTED_ADAPTER`:

  - `etcd` — use an etcd cluster (requires `etcd3` or `etcd3gw`)
  - `consul` — use Consul KV (requires `aiohttp`)
  - any other value or unset — no distributed adapter (local-only behavior)

- Install optional extras via pip from the project root:

```bash
pip install .[etcd]
# or
pip install .[consul]
```

- Or install both helpers together:

```bash
pip install .[distributed]
```

- Notes:
  - Adapters are best-effort: failures to publish/subscribe will not stop local event delivery.
  - `etcd` and `consul` adapters are prototypes; for production use validate adapter stability and
    run the corresponding backend (etcd or Consul) in your environment.

## Embedding API

The FDC3 Desktop Agent can be embedded in other Python applications using the `create_app()` factory function. This allows you to:

- Run the agent alongside your existing FastAPI/Starlette application
- Configure the agent programmatically instead of via environment variables
- Inject custom storage, launcher, or distributed adapter implementations

### Basic Usage

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

### Mounting in a Larger Application

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

### Configuration Options

`DesktopAgentConfig` supports the following options:

| Option                  | Type                        | Default              | Description                                                                             |
| ----------------------- | --------------------------- | -------------------- | --------------------------------------------------------------------------------------- |
| `host`                  | `str`                       | `"localhost"`        | Server bind host (also from `FDC3_HOST` env var)                                        |
| `port`                  | `int`                       | `8000`               | Server bind port (also from `FDC3_PORT` env var)                                        |
| `db_path`               | `str`                       | `"fdc3_agent.db"`    | SQLite database path; use `":memory:"` for in-memory (also from `FDC3_DB_PATH` env var) |
| `log_level`             | `str`                       | `"INFO"`             | Logging level (also from `FDC3_LOG_LEVEL` env var)                                      |
| `allowed_origins`       | `List[str]`                 | `["localhost", ...]` | Origins allowed to connect via WebSocket                                                |
| `agent_url`             | `str`                       | `None`               | WebSocket URL for launched apps; if `None`, computed from host/port                     |
| `storage`               | `Storage`                   | `None`               | Custom storage implementation; if `None`, uses `SqliteStorage`                          |
| `launcher`              | `ProcessLauncher`           | `None`               | Custom process launcher; if `None`, uses `SubprocessLauncher`                           |
| `distributed_adapter`   | `DistributedLogAdapter`     | `None`               | Custom distributed adapter; if `None`, uses factory based on env var                    |
| `plugins`               | `List[IntentHandlerPlugin]` | `[]`                 | Intent handler plugins to register at startup                                           |
| `auto_discover_plugins` | `bool`                      | `True`               | Discover plugins from entry points (also from `FDC3_AUTO_DISCOVER_PLUGINS` env var)     |

### Custom Implementations

You can provide custom implementations of the core interfaces:

```python
from fdc3_desktop_agent import create_app, DesktopAgentConfig, Storage, ProcessLauncher

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

### Exported Interfaces

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

## Plugin API

The Plugin API allows you to extend the desktop agent with custom intent handlers. Plugins can intercept and handle intents before the standard resolution logic runs, enabling custom workflows, integrations with external systems, or specialized intent handling.

### Creating a Plugin

Create a plugin by subclassing `IntentHandlerPlugin`:

```python
from fdc3_desktop_agent import IntentHandlerPlugin, IntentHandlerResult

class MyCustomIntentHandler(IntentHandlerPlugin):
    """Handle custom intents for my application."""

    @property
    def name(self) -> str:
        return "my-custom-handler"

    @property
    def handled_intents(self) -> list[str]:
        # List of intent names this plugin can handle
        return ["ViewChart", "AnalyzeData", "ExportReport"]

    @property
    def priority(self) -> int:
        # Higher priority plugins are checked first (default is 0)
        return 10

    async def handle_intent(
        self,
        intent: str,
        context: dict,
        source: dict,
        target: dict | None = None,
    ) -> IntentHandlerResult:
        """Handle an intent request.

        Args:
            intent: The intent name (e.g., "ViewChart")
            context: The FDC3 context object being passed
            source: Metadata about the source application
            target: Optional target application metadata

        Returns:
            IntentHandlerResult indicating whether the intent was handled
        """
        if intent == "ViewChart":
            # Handle the intent and return a result
            chart_data = await self._generate_chart(context)
            return IntentHandlerResult(
                handled=True,
                result={"chartUrl": chart_data["url"]},
            )

        if intent == "AnalyzeData":
            try:
                analysis = await self._analyze(context)
                return IntentHandlerResult(handled=True, result=analysis)
            except Exception as e:
                return IntentHandlerResult(handled=True, error=str(e))

        # Return handled=False to let other plugins or default resolution handle it
        return IntentHandlerResult(handled=False)
```

### Registering Plugins

#### Via Configuration

Pass plugins when creating the app:

```python
from fdc3_desktop_agent import create_app, DesktopAgentConfig

config = DesktopAgentConfig(
    plugins=[
        MyCustomIntentHandler(),
        AnotherPlugin(),
    ],
)
app = create_app(config)
```

#### Via Entry Points (Automatic Discovery)

External packages can register plugins using Python's entry points system. This allows plugins to be automatically discovered and loaded when the agent starts.

Add an entry point in your package's `pyproject.toml`:

```toml
[project.entry-points."fdc3_desktop_agent.plugins"]
my-handler = "my_package.plugins:MyCustomIntentHandler"
analytics = "my_package.plugins:AnalyticsPlugin"
```

When the FDC3 Desktop Agent starts, it will automatically discover and instantiate these plugins. The entry point value must be a class that inherits from `IntentHandlerPlugin` and can be instantiated with no arguments.

**Controlling Auto-Discovery:**

Auto-discovery is enabled by default. You can disable it:

```python
# Via configuration
config = DesktopAgentConfig(auto_discover_plugins=False)

# Or via environment variable
# FDC3_AUTO_DISCOVER_PLUGINS=false
```

**Listing Available Plugins:**

```python
from fdc3_desktop_agent import list_plugin_entry_points, discover_plugins

# List entry points without loading
entry_points = list_plugin_entry_points()
for ep in entry_points:
    print(f"{ep['name']}: {ep['value']}")

# Discover and instantiate all plugins
plugins = discover_plugins()
for plugin in plugins:
    print(f"{plugin.name}: handles {plugin.handled_intents}")
```

#### At Runtime

Register plugins dynamically through `CoreServices`:

```python
# During lifespan or within your application logic
plugin = MyCustomIntentHandler()
await core_services.register_plugin(plugin)

# Later, if needed
await core_services.unregister_plugin(plugin)
```

### Plugin Lifecycle

Plugins have lifecycle hooks that are called during registration:

```python
class MyPlugin(IntentHandlerPlugin):
    async def on_register(self, core_services) -> None:
        """Called when the plugin is registered.

        Use this to initialize resources, subscribe to events, etc.
        """
        self.db = await self._connect_to_database()
        # Access core services if needed
        self._core = core_services

    async def on_unregister(self) -> None:
        """Called when the plugin is unregistered.

        Use this to clean up resources.
        """
        await self.db.close()
```

### Intent Resolution Order

When an intent is raised:

1. **System intents** (like `fdc3.StartApp`) are handled first by the agent
2. **Plugins** are checked in priority order (highest first)
   - The first plugin returning `handled=True` wins
   - If a plugin returns an error, it's returned to the caller
3. **Standard resolution** proceeds if no plugin handled the intent

### IntentHandlerResult

The result object controls how the intent is processed:

| Field     | Type   | Description                             |
| --------- | ------ | --------------------------------------- | ------------------------------------------------------------ |
| `handled` | `bool` | `True` if the plugin handled the intent |
| `result`  | `dict  | None`                                   | The result to return to the caller (if handled successfully) |
| `error`   | `str   | None`                                   | Error message to return (if handled but failed)              |

```python
# Successfully handled
IntentHandlerResult(handled=True, result={"data": "value"})

# Handled but with error
IntentHandlerResult(handled=True, error="Failed to process")

# Not handled - let another plugin or default resolution try
IntentHandlerResult(handled=False)
```

## External Intent Handlers

External intent handlers are standalone Python processes that connect to the desktop agent via WebSocket and register as intent handlers. Unlike embedded plugins, external handlers run in separate processes and can be written by third parties.

### Overview

External handlers:

- Connect to the agent's WebSocket endpoint (`/ws`)
- Complete the WCP (Web Connection Protocol) handshake using self-registration
- Register handlers for specific intents
- Receive forwarded intent requests and send results back

### Using the Client Library

The `fdc3_client` package provides a simple client for building external handlers (now available as `fdc3.client`):

```python
from fdc3.client import FDC3Client

async with FDC3Client("ws://localhost:8000/ws", handler_id="my-handler") as client:
    # Wait for WCP handshake to complete
    if not await client.wait_for_handshake():
        raise RuntimeError("Handshake failed")

    # Register for specific intents
    handler_uuid = await client.register_handler(
        handler_id="my-handler",
        intents=["ViewChart", "AnalyzeData"],
        priority=10,
    )

    # Handle incoming intents
    async def on_intent(request):
        # request has: request_uuid, intent, context, source
        result = await process_intent(request.intent, request.context)
        await client.send_intent_result(request.request_uuid, result=result)

    client.on_intent(on_intent)
    await client.run_forever()
```

### FDC3Client API

#### Constructor

```python
FDC3Client(
    agent_url: str,            # WebSocket URL (e.g., "ws://localhost:8000/ws")
    handler_id: str = "external-handler",  # Unique handler identifier
    ping_interval: float = 20.0,  # WebSocket ping interval in seconds
)
```

#### Methods

| Method                                                             | Description                                                             |
| ------------------------------------------------------------------ | ----------------------------------------------------------------------- |
| `connect()`                                                        | Connect to the agent and initiate WCP handshake                         |
| `wait_for_handshake(timeout=10.0)`                                 | Wait for WCP handshake to complete; returns `True` if successful        |
| `register_handler(handler_id, intents, priority=0, metadata=None)` | Register as a handler for the specified intents; returns `handler_uuid` |
| `unregister_handler(handler_uuid)`                                 | Unregister a previously registered handler                              |
| `send_intent_result(request_uuid, result=None, error=None)`        | Send the result (or error) for a forwarded intent                       |
| `on_intent(callback)`                                              | Set the callback for forwarded intent events                            |
| `close()`                                                          | Close the WebSocket connection                                          |
| `run_forever()`                                                    | Block until the connection is closed                                    |

### Protocol Messages

External handlers use these message types:

#### registerExternalHandler (client → agent)

```json
{
  "type": "registerExternalHandler",
  "payload": {
    "handler_id": "my-handler",
    "intents": ["ViewChart", "AnalyzeData"],
    "priority": 10,
    "metadata": {}
  },
  "meta": { "requestUuid": "uuid-string" }
}
```

#### registerExternalHandlerResponse (agent → client)

```json
{
  "type": "registerExternalHandlerResponse",
  "payload": { "handler_uuid": "uuid-string" },
  "meta": { "requestUuid": "uuid-string" }
}
```

#### forwardedIntent (agent → client)

```json
{
  "type": "forwardedIntent",
  "payload": {
    "request_uuid": "uuid-string",
    "intent": "ViewChart",
    "context": { "type": "fdc3.chart", "data": {} },
    "source": { "appId": "app-id", "instanceId": "instance-id" },
    "timeout": 30
  }
}
```

#### intentResult (client → agent)

```json
{
  "type": "intentResult",
  "payload": {
    "request_uuid": "uuid-string",
    "result": { "data": "value" },
    "error": null
  }
}
```

### Example External Handler

See [examples/external_handler.py](examples/external_handler.py) for a complete working example. Run it with:

```bash
python -m examples.external_handler --agent-url ws://localhost:8000/ws --handler-id my-handler
```

### Creating an External Handler Package

To package an external handler for distribution:

#### pyproject.toml

```toml
[project]
name = "my-fdc3-handler"
version = "0.1.0"
dependencies = [
    "websockets>=11.0",
]

[project.scripts]
my-fdc3-handler = "my_handler.main:main"
```

#### Handler Implementation

```python
# my_handler/main.py
import asyncio
from fdc3_client import FDC3Client

async def run():
    async with FDC3Client("ws://localhost:8000/ws", handler_id="my-handler") as client:
        await client.wait_for_handshake()
        await client.register_handler("my-handler", ["MyIntent"], priority=5)

        async def on_intent(req):
            # Handle the intent
            await client.send_intent_result(req.request_uuid, result={"handled": True})

        client.on_intent(on_intent)
        await client.run_forever()

def main():
    asyncio.run(run())
```

### Security Considerations

External handlers connect via WebSocket and are trusted once connected. Consider these security measures:

1. **Network access**: Run the agent on `localhost` or behind a firewall to limit who can connect.

2. **Origin checking**: Configure `FDC3_ALLOWED_ORIGINS` to restrict WebSocket connections to known origins.

3. **Handler priority**: External handlers with high priority can intercept intents before other handlers. Monitor what handlers are registered.

4. **Connection monitoring**: The agent logs handler registrations. External handlers are automatically unregistered when their WebSocket connection closes.

5. **Authentication (future)**: For production environments, consider adding API key validation or certificate-based authentication before allowing external handler registration.

### Intent Resolution Order

When an intent is raised, resolution follows this order:

1. **System intents** (`fdc3.StartApp`, etc.)
2. **Embedded plugins** (by priority, highest first)
3. **External handlers** (by priority, highest first)
4. **Standard app resolution** (app directory lookup)
