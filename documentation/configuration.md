# Configuration and Running

## Configuration

The agent can be configured via environment variables:

- `FDC3_HOST`: Server host (default: `localhost`)
- `FDC3_PORT`: Server port (default: `8000`)
- `FDC3_DB_PATH`: SQLite database path (default: `fdc3_agent.db`)
- `FDC3_LOG_LEVEL`: Logging level (default: `INFO`)
- `FDC3_ALLOWED_ORIGINS`: Comma-separated list of allowed origins for WebSocket connections

Desktop Agent Bridging (experimental) configuration is documented separately in [bridging.md](bridging.md).

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
