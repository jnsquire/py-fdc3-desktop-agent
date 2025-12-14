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
# Using specific versions from pyproject.toml
RUN pip install --upgrade pip && \
    pip install \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.30" \
    "pydantic>=2.7" \
    "strawberry-graphql>=0.250" \
    "aiosqlite>=0.20" \
    "hatchling" && \
    pip install --no-deps -e .

# Pre-configure the agent with sensible defaults
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

# Run the agent
CMD ["uvicorn", "fdc3_desktop_agent.server:app", "--host", "0.0.0.0", "--port", "8000"]
