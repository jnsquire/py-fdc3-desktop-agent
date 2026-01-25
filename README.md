# FDC3 Desktop Agent (Python)

[![CI](https://github.com/jnsquire/py-fdc3-desktop-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/jnsquire/py-fdc3-desktop-agent/actions/workflows/ci.yml)
[![Docs](https://github.com/jnsquire/py-fdc3-desktop-agent/actions/workflows/docs.yml/badge.svg)](https://github.com/jnsquire/py-fdc3-desktop-agent/actions/workflows/docs.yml)

A production‑ready FDC3 Desktop Agent for Python that exposes WebSocket (WCP/DACP), GraphQL, and Admin UI
endpoints for browser‑based applications.

## Who is this for?

- FDC3‑enabled web apps that need a local Desktop Agent.
- Developers embedding FDC3 into desktop shells or internal tooling.
- Teams evaluating Desktop Agent Bridging (BCP/BMP) for multi‑agent setups.

## What’s included

- WCP over WebSocket with DACP request/response and event routing.
- FastAPI server with Admin UI and GraphQL endpoint.
- Optional distributed adapters (etcd, Consul) for channel fan‑out.
- MkDocs‑powered documentation site.

## Requirements

- Python 3.11+ (see supported versions in CI).
- Docker (optional, recommended for quick start).
- SQLite (default storage via aiosqlite).
- Optional: etcd/Consul for distributed adapters.

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

### 5‑minute demo

1) Start the agent:

```bash
docker-compose up
```

2) In another terminal, run a sample client:

```bash
python examples/tui_chat_client.py --name Alice --channel demo
```

3) Open the Admin UI at: `http://localhost:8000/admin`

### Admin UI preview

![Admin UI preview](documentation/assets/admin-ui-preview.svg)

## Architecture overview

- WebSocket endpoint for WCP handshake + DACP messages.
- GraphQL endpoint for management/observability.
- Optional bridge client for BCP/BMP.

See the [system flowchart](documentation/system_flowchart.md) and [implementation notes](IMPLEMENTATION.md)
for deeper details.

## Documentation

Documentation overview:

- Published site: <https://jnsquire.github.io/py-fdc3-desktop-agent/>
- API Reference (generated): <https://jnsquire.github.io/py-fdc3-desktop-agent/api/>

- Configuration & running: [documentation/configuration.md](documentation/configuration.md) (published: https://jnsquire.github.io/py-fdc3-desktop-agent/configuration/)
- Desktop Agent Bridging (experimental): [documentation/bridging.md](documentation/bridging.md) (published: https://jnsquire.github.io/py-fdc3-desktop-agent/bridging/)
- Embedding API: [documentation/embedding-api.md](documentation/embedding-api.md) (published: https://jnsquire.github.io/py-fdc3-desktop-agent/embedding-api/)
- Docker deployment: [documentation/docker.md](documentation/docker.md) (published: https://jnsquire.github.io/py-fdc3-desktop-agent/docker/)
- Plugin API: [documentation/plugins.md](documentation/plugins.md) (published: https://jnsquire.github.io/py-fdc3-desktop-agent/plugins/)
- External intent handlers: [documentation/external-intent-handlers.md](documentation/external-intent-handlers.md) (published: https://jnsquire.github.io/py-fdc3-desktop-agent/external-intent-handlers/)

Additional references:

- Implementation notes: [IMPLEMENTATION.md](IMPLEMENTATION.md) (published: https://jnsquire.github.io/py-fdc3-desktop-agent/IMPLEMENTATION/)
- System flowchart: [documentation/system_flowchart.md](documentation/system_flowchart.md) (published: https://jnsquire.github.io/py-fdc3-desktop-agent/system_flowchart/)
- FDC3 spec gap checklist: [documentation/fdc3-spec-gap-checklist.md](documentation/fdc3-spec-gap-checklist.md) (published: https://jnsquire.github.io/py-fdc3-desktop-agent/fdc3-spec-gap-checklist/)

The documentation site is powered by MkDocs. Use `mkdocs build` to rebuild the HTML output and `mkdocs serve` to preview changes locally. The `hatch build` command runs `mkdocs build` first so release artifacts always include a fresh site.

## Support & roadmap

- Issues and feature requests: <https://github.com/jnsquire/py-fdc3-desktop-agent/issues>
- Roadmap discussions happen via issues and milestones.

## Security

Please report security issues via GitHub Security Advisories or open an issue if private disclosure is not required.

## Release & versioning

Releases follow semantic versioning. See GitHub Releases for published artifacts and notes.

## License

Licensed under the Apache License, Version 2.0 (matching FDC3 reference implementations). See [LICENSE](LICENSE).
