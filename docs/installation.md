# Installation

## Requirements

- [Docker Desktop](https://www.docker.com/products/docker-desktop) (includes Docker Compose)
- macOS, Linux, or Windows 10/11
- ~2 GB free disk space (for Docker images + audit data)

No Python, Node, or browser installations required — everything runs inside containers.

---

## Quick Install

```bash
git clone https://github.com/venk-hub/Odit.git
cd Odit

# Copy environment file
cp .env.example .env

# Start all containers
./start-auditor.sh        # macOS / Linux
start-auditor.bat         # Windows

# Open the app
open http://localhost:8000
```

The first start downloads ~1.5 GB of Docker images (Playwright/Chromium, PostgreSQL, mitmproxy). Subsequent starts are instant.

---

## What Gets Started

| Container | Role | Port |
|-----------|------|------|
| `app` | FastAPI web UI | 8000 |
| `worker` | Playwright crawler | — |
| `proxy` | mitmproxy traffic interceptor | 8080 |
| `postgres` | PostgreSQL database | 5432 (internal) |

---

## Environment Variables

Edit `.env` to customise behaviour:

```env
DATABASE_URL=postgresql://odit:odit_local_pass@postgres:5432/odit
DATA_DIR=/data
PROXY_HOST=proxy
PROXY_PORT=8080
APP_PORT=8000
ANTHROPIC_API_KEY=        # optional — enables AI features
```

`ANTHROPIC_API_KEY` can also be set via the **Settings** page in the UI — no restart needed.

---

## Stopping & Resetting

```bash
# Stop containers (data preserved)
./stop-auditor.sh

# Stop and wipe all audit data + database
docker compose down -v
rm -rf data/audits data/proxy_flows
```

---

## Updating

```bash
git pull
docker compose up --build -d
```

---

## Running Without Docker (Development)

```bash
# App
cd app
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Worker (separate terminal)
cd worker
pip install -r requirements.txt
playwright install chromium
python worker/main.py

# Database migrations
alembic upgrade head
```

You will also need a local PostgreSQL instance and mitmproxy running separately — see `docker-compose.yml` for connection details.
