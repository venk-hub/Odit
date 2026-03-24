FROM python:3.11-slim

WORKDIR /odit

# Install system dependencies including mitmproxy CA trust and Playwright deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    ca-certificates \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY worker/requirements.txt /odit/worker/requirements.txt
RUN pip install --no-cache-dir -r worker/requirements.txt

# Install Playwright browsers
RUN playwright install chromium

# Copy application and worker code
COPY app/ /odit/app/
COPY worker/ /odit/worker/

# Create data directory
RUN mkdir -p /data/audits /data/proxy_flows /data/certs

# Entrypoint script
COPY docker/entrypoint-worker.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
