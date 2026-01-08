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
