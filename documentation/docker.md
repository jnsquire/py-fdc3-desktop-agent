# Docker Deployment

The FDC3 Desktop Agent can be deployed as a Docker container for easy distribution and deployment.

## Building the Docker Image

```bash
docker build -t fdc3-desktop-agent:latest .
```

## Running with Docker

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

For a quick Docker compose start, see [getting-started.md](getting-started.md).

## Docker Configuration

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

## Persistent Data

The Docker image stores the SQLite database in `/data/fdc3_agent.db`. Mount a volume to persist data:

```bash
docker run -p 8000:8000 -v fdc3-data:/data fdc3-desktop-agent:latest
```

## Health Check

The Docker image includes a built-in health check that verifies the admin interface is accessible. Check container health with:

```bash
docker ps
docker inspect --format='{{json .State.Health}}' <container-id>
```
