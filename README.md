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

## Documentation

The README is intentionally kept short; the more detailed guides live in the repository documentation:

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
