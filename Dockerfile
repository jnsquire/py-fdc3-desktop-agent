# Minimal Docker image for FDC3 Desktop Agent
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables for Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Copy all necessary files
COPY pyproject.toml ./
COPY fdc3_desktop_agent ./fdc3_desktop_agent
COPY README.md ./

# Install dependencies and the package in one layer
# Using pyproject.toml to avoid version drift
RUN pip install --upgrade pip && \
    pip install "hatchling" && \
    pip install -e .

# Pre-configure the agent with sensible defaults
# NOTE: FDC3_ALLOWED_ORIGINS=* allows all origins for convenience
# Override with specific domains for production deployments
ENV FDC3_HOST=0.0.0.0 \
    FDC3_PORT=8000 \
    FDC3_DB_PATH=/data/fdc3_agent.db \
    FDC3_LOG_LEVEL=INFO \
    FDC3_ALLOWED_ORIGINS=*

# Create data directory for SQLite database
RUN mkdir -p /data

# Expose the agent port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/admin').read()" || exit 1

# Run the agent using environment variables
CMD sh -c "uvicorn fdc3_desktop_agent.server:app --host ${FDC3_HOST} --port ${FDC3_PORT}"
