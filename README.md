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
uv run uvicorn src.fdc3_desktop_agent.server:app --host localhost --port 8000 --reload --log-level info
```

### Production Mode (multi-worker)
```bash
uv run uvicorn src.fdc3_desktop_agent.server:app --host 0.0.0.0 --port 8000 --workers 4 --log-level warning
```

### Debug Mode (verbose logging)
```bash
uv run uvicorn src.fdc3_desktop_agent.server:app --host localhost --port 8000 --reload --log-level debug
```

### Running Tests
```bash
uv run python -m pytest tests/ -v
```

### Quick Development Start
```bash
uv run uvicorn src.fdc3_desktop_agent.server:app --reload
```
