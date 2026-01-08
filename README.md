# FDC3 Desktop Agent (Python)

The Python FDC3 Desktop Agent implements the FDC3 Desktop Agent API and exposes managed WebSocket, GraphQL,
and admin endpoints for browser-based applications.

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

## Documentation

Documentation overview:

- Published site: https://jnsquire.github.io/py-fdc3-desktop-agent/
- API Reference (generated): https://jnsquire.github.io/py-fdc3-desktop-agent/api/

- Configuration & running: [documentation/configuration.md](documentation/configuration.md)
- Desktop Agent Bridging (experimental): [documentation/bridging.md](documentation/bridging.md)
- Embedding API: [documentation/embedding-api.md](documentation/embedding-api.md)
- Docker deployment: [documentation/docker.md](documentation/docker.md)
- Plugin API: [documentation/plugins.md](documentation/plugins.md)
- External intent handlers: [documentation/external-intent-handlers.md](documentation/external-intent-handlers.md)

Additional references:

- Implementation notes: [IMPLEMENTATION.md](IMPLEMENTATION.md)
- System flowchart: [documentation/system_flowchart.md](documentation/system_flowchart.md)
- FDC3 spec gap checklist: [documentation/fdc3-spec-gap-checklist.md](documentation/fdc3-spec-gap-checklist.md)

The documentation site is powered by MkDocs. Rebuild the HTML output with `mkdocs build` and preview changes with `mkdocs serve`. `hatch build` now runs `mkdocs build` first so release artifacts always include a fresh site.
