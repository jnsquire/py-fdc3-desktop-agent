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

## Production Hardening

For production deployments, ensure the following configurations are set:

1.  **Transport Security**: Use a reverse proxy (e.g., Nginx) to terminate TLS for WebSocket (`wss://`) traffic.
2.  **Allowed Origins**: Set `FDC3_ALLOWED_ORIGINS` to your specific UI domains to prevent unauthorized site connections.
3.  **Persistence**: Configure a persistent SQLite file via `FDC3_DB_PATH` rather than the default `:memory:` storage.
4.  **Process Management**: Use a process manager like `systemd` or `pm2` to ensure the agent restarts on failure.

## Running the Agent

Start the server with `python -m uvicorn fdc3.desktop_agent.server:app` (the `uv` shim shown below is optional and simply invokes the same command).

### Development mode (with auto-reload)

```bash
python -m uvicorn fdc3.desktop_agent.server:app --host localhost --port 8000 --reload --log-level info
```

### Production mode (multi-worker)

```bash
python -m uvicorn fdc3.desktop_agent.server:app --host 0.0.0.0 --port 8000 --workers 4 --log-level warning
```

### Debug mode (verbose logging)

```bash
python -m uvicorn fdc3.desktop_agent.server:app --host localhost --port 8000 --reload --log-level debug
```

For quick iterations you can rerun the development command above with `--reload` enabled to receive instant restarts.

For running tests and development workflows, see the [contributing guide](https://github.com/jnsquire/py-fdc3-desktop-agent/blob/main/CONTRIBUTING.md).

## Distributed Adapters (optional)

If you need to relay channel events across multiple agent instances, set `FDC3_DISTRIBUTED_ADAPTER` to one of the supported backends:

- `etcd` — publishes events to an etcd cluster (requires either `etcd3` or `etcd3gw`).
- `consul` — stores events in Consul KV (requires `aiohttp`).
- any other value, or omitting the variable, keeps the agent in local-only mode.

Install the corresponding optional extras from the repository root:

```bash
pip install .[etcd]
# or
pip install .[consul]
```

To install both adapters simultaneously:

```bash
pip install .[distributed]
```

Adapters operate on a best-effort basis, so publish/subscribe failures do not stop local delivery. The `etcd` and `consul` adapters are experimental prototypes; verify their stability and ensure the backend service is running before relying on them in production.
