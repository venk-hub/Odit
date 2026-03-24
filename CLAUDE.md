# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

**Odit** is a local-first tracking auditor — a multi-container Docker Compose appliance that crawls websites using a real browser, captures martech/analytics evidence, detects vendors, flags issues, and generates reports.

## Quick Start

```bash
./start-auditor.sh        # macOS/Linux
start-auditor.bat         # Windows
```

Then open http://localhost:8000.

## Development Commands

### Running locally (no Docker)

```bash
# App (FastAPI)
cd app && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Worker
cd worker && pip install -r worker/requirements.txt
playwright install chromium
python worker/main.py

# DB migrations
alembic upgrade head
alembic revision --autogenerate -m "description"
```

### Docker

```bash
docker compose up --build          # Start all services
docker compose up --build app      # Rebuild and restart one service
docker compose logs -f worker      # Tail worker logs
docker compose down                # Stop
docker compose down -v             # Stop and remove volumes (wipes DB)
```

### Tests

```bash
pip install pytest openpyxl pyyaml
pytest tests/ -v
pytest tests/test_vendor_detection.py  # Run one test file
```

## Architecture

```
postgres   ← shared DB (SQLAlchemy models, Alembic migrations)
   ↕
app        ← FastAPI web app (port 8000): API routes + Jinja2/HTMX UI
   ↕
worker     ← crawler process: polls DB for pending jobs, runs Playwright
   ↕
proxy      ← mitmproxy (port 8080): intercepts browser traffic from worker
```

**Data flow:**
1. User submits audit form → `POST /api/audits` → creates `AuditRun` (status=pending)
2. Worker polls `AuditRun` table, picks up pending job
3. Worker runs Playwright browser routed through mitmproxy
4. Evidence written to `/data/audits/{audit_id}/` and normalized into DB
5. Vendor detection and rule engine run after crawl
6. Exports generated, artifacts registered in DB
7. UI polls `/api/audits/{id}/progress` every 3s via HTMX

## Key Files

| File | Purpose |
|------|---------|
| `app/models/` | All SQLAlchemy models (audit, page, vendor, issue, artifact, comparison) |
| `app/api/` | REST API routes (audits, pages, issues, vendors, exports, comparisons) |
| `app/web/routes.py` | Jinja2 template routes for the browser UI |
| `app/templates/` | HTMX + Tailwind templates; partials loaded dynamically |
| `worker/main.py` | Worker entrypoint — polls for pending jobs |
| `worker/crawler/engine.py` | Playwright BFS crawler |
| `worker/detectors/vendors.yaml` | Vendor signature registry (YAML, easily extended) |
| `worker/detectors/vendor_detector.py` | Matches requests/scripts/globals/cookies against signatures |
| `worker/rules/rule_engine.py` | 10 issue detection rules |
| `worker/exports/excel_exporter.py` | 9-sheet Excel workbook |
| `worker/exports/report_exporter.py` | HTML, Markdown, JSON reports |
| `proxy/mitm_addon.py` | mitmproxy addon — writes JSONL flow records to disk |
| `alembic/versions/001_initial_schema.py` | Full DB schema migration |

## Extending Vendor Detection

Add entries to `worker/detectors/vendors.yaml`:

```yaml
vendors:
  - key: my_vendor
    name: My Vendor
    category: analytics   # analytics|tag_manager|ab_testing|consent|pixel|other
    signatures:
      domains: [cdn.myvendor.com]
      script_patterns: [myvendor.js]
      window_globals: [window.myVendor]
      cookie_patterns: [_mv_]
```

No code changes needed — the detector loads this file at startup.

## Adding Issue Detection Rules

Add a function to `worker/rules/rule_engine.py`:

```python
def rule_my_check(audit_run, pages, requests, events, vendors, config):
    issues = []
    # ... logic ...
    issues.append(Issue(severity="high", category="my_category", ...))
    return issues
```

Then register it in the `ALL_RULES` list at the bottom of that file.

## Artifact Storage

Artifacts are stored under `./data/` (mounted as `/data` in containers):

```
data/audits/{audit_id}/
  screenshots/     PNG screenshots per page
  har/             HAR files per page
  json/            JSON evidence per page
  reports/         audit_report.xlsx, audit_summary.md/html/json
  proxy/           (reserved for per-audit proxy flow filtering)
data/proxy_flows/  JSONL files written by mitmproxy addon
```

## Environment Variables

See `.env.example`. Key vars:
- `DATABASE_URL` — postgres connection string
- `DATA_DIR` — artifact root (default `/data`)
- `PROXY_HOST` / `PROXY_PORT` — mitmproxy address (default `proxy:8080`)

## DB Schema Notes

- All PKs are UUID4
- `AuditRun.status`: `pending | running | completed | failed | cancelled`
- Worker uses `SELECT ... FOR UPDATE SKIP LOCKED` to safely dequeue jobs
- `AuditConfig` stores all crawl parameters as JSON columns where appropriate
- `DetectedVendor` exists at both page level (page_visit_id set) and audit level (null page_visit_id)
