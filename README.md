# FDC3 Desktop Agent (Python)

A Python implementation of an FDC3 Desktop Agent with WebSocket support for browser app connections.

## Quick Start

### Using Docker (Recommended)

```bash
# Using docker-compose
docker-compose up

# Or build and run manually
docker build -t fdc3-desktop-agent .
docker run -p 8000:8000 fdc3-desktop-agent
```

The agent will be available at:
- WebSocket: `ws://localhost:8000/ws`
- Admin UI: `http://localhost:8000/admin`
- GraphQL: `http://localhost:8000/graphql`

### Local Development

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
uv run uvicorn fdc3_desktop_agent.server:app --host localhost --port 8000 --reload --log-level info
```

### Production Mode (multi-worker)

```bash
uv run uvicorn fdc3_desktop_agent.server:app --host 0.0.0.0 --port 8000 --workers 4 --log-level warning
```

### Debug Mode (verbose logging)

```bash
uv run uvicorn fdc3_desktop_agent.server:app --host localhost --port 8000 --reload --log-level debug
```

### Running Tests

```bash
uv run python -m pytest tests/ -v
```

### Quick Development Start

```bash
uv run uvicorn fdc3_desktop_agent.server:app --reload
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
from fdc3_desktop_agent import create_app, DesktopAgentConfig

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
from fdc3_desktop_agent import create_app, DesktopAgentConfig

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

| Option                | Type                    | Default              | Description                                                                             |
| --------------------- | ----------------------- | -------------------- | --------------------------------------------------------------------------------------- |
| `host`                | `str`                   | `"localhost"`        | Server bind host (also from `FDC3_HOST` env var)                                        |
| `port`                | `int`                   | `8000`               | Server bind port (also from `FDC3_PORT` env var)                                        |
| `db_path`             | `str`                   | `"fdc3_agent.db"`    | SQLite database path; use `":memory:"` for in-memory (also from `FDC3_DB_PATH` env var) |
| `log_level`           | `str`                   | `"INFO"`             | Logging level (also from `FDC3_LOG_LEVEL` env var)                                      |
| `allowed_origins`     | `List[str]`             | `["localhost", ...]` | Origins allowed to connect via WebSocket                                                |
| `agent_url`           | `str`                   | `None`               | WebSocket URL for launched apps; if `None`, computed from host/port                     |
| `storage`             | `Storage`               | `None`               | Custom storage implementation; if `None`, uses `SqliteStorage`                          |
| `launcher`            | `ProcessLauncher`       | `None`               | Custom process launcher; if `None`, uses `SubprocessLauncher`                           |
| `distributed_adapter` | `DistributedLogAdapter` | `None`               | Custom distributed adapter; if `None`, uses factory based on env var                    |

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
from fdc3_desktop_agent import (
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
)
```

## Docker Deployment

The FDC3 Desktop Agent can be deployed as a Docker container for easy distribution and deployment.

### Building the Docker Image

```bash
docker build -t fdc3-desktop-agent:latest .
```

### Running with Docker

```bash
# Run with default configuration
docker run -p 8000:8000 fdc3-desktop-agent:latest

# Run with custom configuration
docker run -p 9000:9000 \
  -e FDC3_PORT=9000 \
  -e FDC3_LOG_LEVEL=DEBUG \
  -e FDC3_ALLOWED_ORIGINS="example.com,app.example.com" \
  -v ./data:/data \
  fdc3-desktop-agent:latest

# Run with docker-compose
docker-compose up -d
```

### Docker Configuration

The Docker image is pre-configured with the following defaults:

- **Host**: `0.0.0.0` (listens on all interfaces)
- **Port**: `8000`
- **Database**: `/data/fdc3_agent.db` (persisted in volume)
- **Log Level**: `INFO`
- **Allowed Origins**: `*` (all origins - override for production)

You can override any configuration using environment variables:

```yaml
# docker-compose.yml example
version: '3.8'
services:
  fdc3-agent:
    image: fdc3-desktop-agent:latest
    ports:
      - "8000:8000"
    environment:
      - FDC3_LOG_LEVEL=DEBUG
      - FDC3_ALLOWED_ORIGINS=localhost,example.com
    volumes:
      - ./data:/data
```

### Persistent Data

The Docker image stores the SQLite database in `/data/fdc3_agent.db`. Mount a volume to persist data:

```bash
docker run -p 8000:8000 -v fdc3-data:/data fdc3-desktop-agent:latest
```

### Health Check

The Docker image includes a built-in health check that verifies the admin interface is accessible. Check container health with:

```bash
docker ps
docker inspect --format='{{json .State.Health}}' <container-id>
```
