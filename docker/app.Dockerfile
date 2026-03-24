FROM python:3.11-slim

WORKDIR /odit

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY app/requirements.txt /odit/app/requirements.txt
RUN pip install --no-cache-dir -r app/requirements.txt

# Copy application code
COPY app/ /odit/app/
COPY alembic/ /odit/alembic/
COPY alembic.ini /odit/alembic.ini

# Create data directory
RUN mkdir -p /data/audits /data/proxy_flows /data/certs

# Entrypoint: run migrations then start uvicorn
COPY docker/entrypoint-app.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
