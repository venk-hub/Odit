#!/bin/bash
set -e

echo ""
echo "╔════════════════════════════════════════╗"
echo "║        Odit - Tracking Auditor         ║"
echo "╚════════════════════════════════════════╝"
echo ""

# Check dependencies
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker is not installed or not in PATH."
    echo "Please install Docker Desktop: https://www.docker.com/products/docker-desktop"
    exit 1
fi

if ! docker info &> /dev/null; then
    echo "ERROR: Docker daemon is not running. Please start Docker Desktop."
    exit 1
fi

if ! command -v docker compose &> /dev/null && ! command -v docker-compose &> /dev/null; then
    echo "ERROR: Docker Compose is not available."
    exit 1
fi

# Determine compose command
if command -v docker compose &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

# Create directories
echo "Creating data directories..."
mkdir -p data/audits data/proxy_flows data/certs

# Copy .env if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
fi

# Build and start containers
echo ""
echo "Building and starting Odit containers..."
$COMPOSE_CMD up -d --build

echo ""
echo "Waiting for services to be ready..."

# Wait for the app to be healthy
MAX_WAIT=120
ELAPSED=0
while [ $ELAPSED -lt $MAX_WAIT ]; do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "App is ready!"
        break
    fi
    echo "  Waiting for app... ($ELAPSED/${MAX_WAIT}s)"
    sleep 5
    ELAPSED=$((ELAPSED + 5))
done

if [ $ELAPSED -ge $MAX_WAIT ]; then
    echo ""
    echo "WARNING: App did not become healthy within ${MAX_WAIT}s."
    echo "Check logs with: $COMPOSE_CMD logs app"
fi

echo ""
echo "╔════════════════════════════════════════════════════╗"
echo "║  Odit is running at:  http://localhost:8000        ║"
echo "║  Proxy intercept:     http://localhost:8080        ║"
echo "╚════════════════════════════════════════════════════╝"
echo ""
echo "To view logs:   $COMPOSE_CMD logs -f"
echo "To stop:        ./stop-auditor.sh"
echo ""
