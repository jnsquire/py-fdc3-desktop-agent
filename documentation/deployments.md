# Deployments

This page outlines the supported deployment paths for the FDC3 Desktop Agent.

## Docker (recommended)

Use Docker when you want quick setup and repeatable environments. See the full guide in [docker.md](docker.md).

### When to use

- Local evaluation
- CI smoke tests
- Reproducible demos

## Local (virtual environment)

Use a local venv when you want to develop or debug the agent. See [configuration.md](configuration.md) for runtime flags and env vars.

### When to use

- Active development
- Debugging with IDE tools
- Running unit tests

## Embedded (advanced)

If you embed the agent in another host application, you can import the FastAPI app directly and manage the lifecycle yourself. See [configuration.md](configuration.md) for runtime settings.

### When to use

- Integrating into a larger Python service
- Custom lifecycle management
- Single‑process deployments

## Next steps

- Configure the agent: see [configuration.md](configuration.md)
- Automate docs screenshots: see [automation.md](automation.md)
