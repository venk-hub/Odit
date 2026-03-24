# Odit - Tracking Auditor

A local-first web application that audits a website's client-side tracking and analytics implementation quality. Odit crawls your site using a real browser, captures network traffic through a transparent proxy, detects analytics vendors, and flags implementation issues with detailed recommendations.

## What Odit Does

- Crawls websites using Playwright (real Chromium browser)
- Captures all network requests via mitmproxy
- Detects 21+ analytics, tag management, A/B testing, and consent vendors
- Flags 10 categories of tracking issues (broken scripts, missing vendors, consent violations, duplicates, etc.)
- Shows live crawl progress with HTMX-powered UI
- Exports findings as Excel workbook, HTML report, Markdown, and JSON

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop) (includes Docker Compose)
- macOS, Linux, or Windows

## Quick Start

```bash
# Clone or download the project
cd /path/to/odit

# Start everything
./start-auditor.sh          # macOS/Linux
start-auditor.bat           # Windows

# Open the app
open http://localhost:8000
```

## Running Your First Audit

1. Open http://localhost:8000
2. Click **New Audit**
3. Enter the website URL (e.g. `https://example.com`)
4. Choose an audit mode:
   - **Quick Scan** — Fast scan of the homepage and a few pages (recommended for first run)
   - **Full Crawl** — BFS crawl up to your configured page limit
   - **Journey Audit** — Crawl specific seed URLs you define
   - **Regression Compare** — Compare this audit against a previous one
5. Configure optional settings (device type, consent behavior, expected vendors)
6. Click **Run Audit**
7. Watch the live progress on the audit detail page
8. View results in the Summary, Issues, Vendors, Pages, and Exports tabs

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  User Browser                                            │
│  http://localhost:8000                                   │
└───────────────────┬─────────────────────────────────────┘
                    │ HTTP
┌───────────────────▼─────────────────────────────────────┐
│  FastAPI App Container                                   │
│  - Jinja2 + HTMX UI                                     │
│  - REST API (/api/*)                                     │
│  - Async SQLAlchemy                                      │
│  - Alembic migrations                                    │
└──────────┬──────────────────────────────────────────────┘
           │ PostgreSQL
┌──────────▼──────────────────────────────────────────────┐
│  PostgreSQL Container                                    │
│  - All audit data                                       │
│  - Job queue (pending/running/completed)                 │
└──────────┬──────────────────────────────────────────────┘
           │ SQL polling
┌──────────▼──────────────────────────────────────────────┐
│  Worker Container                                        │
│  - Playwright (headless Chromium)                       │
│  - Vendor detection (YAML signatures)                   │
│  - Issue rule engine (10 rules)                         │
│  - Export generators (Excel, HTML, MD, JSON)            │
└──────────┬──────────────────────────────────────────────┘
           │ HTTP Proxy
┌──────────▼──────────────────────────────────────────────┐
│  mitmproxy Container (port 8080)                        │
│  - Intercepts all HTTPS traffic                         │
│  - Writes flow records to /data/proxy_flows/            │
└─────────────────────────────────────────────────────────┘
```

## Folder Structure

```
odit/
├── app/                    # FastAPI application
│   ├── api/                # REST API route modules
│   ├── web/                # Jinja2 template routes
│   ├── models/             # SQLAlchemy models
│   ├── templates/          # HTML templates (Jinja2)
│   ├── static/             # Static assets
│   ├── main.py             # FastAPI app entrypoint
│   ├── config.py           # Settings (pydantic-settings)
│   ├── database.py         # DB engine + session
│   └── requirements.txt
├── worker/                 # Background crawl worker
│   ├── crawler/            # Playwright crawl engine
│   ├── detectors/          # Vendor detection (vendors.yaml)
│   ├── rules/              # Issue detection rules
│   ├── exports/            # Excel/HTML/MD/JSON exporters
│   ├── main.py             # Worker entrypoint (DB polling loop)
│   ├── config.py
│   └── requirements.txt
├── proxy/                  # mitmproxy container
│   ├── mitm_addon.py       # Intercept + logging addon
│   └── Dockerfile
├── alembic/                # DB migrations
│   ├── versions/
│   └── env.py
├── docker/                 # Dockerfiles + entrypoints
├── tests/                  # Unit tests
├── docs/                   # Documentation
├── data/                   # Artifact storage (gitignored)
│   ├── audits/{id}/        # Per-audit artifacts
│   │   ├── screenshots/    # PNG screenshots
│   │   ├── har/            # HAR network archives
│   │   └── reports/        # Excel, HTML, MD, JSON exports
│   └── proxy_flows/        # mitmproxy JSONL flow records
├── docker-compose.yml
├── .env.example
├── start-auditor.sh
└── stop-auditor.sh
```

## Exports

After an audit completes, the following exports are automatically generated:

| Export | File | Description |
|--------|------|-------------|
| Excel Workbook | `audit_report.xlsx` | 9 sheets: Summary, Pages, Vendors, Issues, Broken Requests, Console Errors, Scripts, Cookies/Storage, Recommendations |
| HTML Report | `audit_summary.html` | Styled standalone HTML — share with stakeholders |
| Markdown Report | `audit_summary.md` | Plain text for Confluence/Notion/GitHub Issues |
| JSON Summary | `audit_summary.json` | Machine-readable for CI/CD integration |
| Screenshots | `screenshots/*.png` | Full-page screenshots of each crawled page |
| HAR Files | `har/*.har` | Complete network traffic archives (open in Chrome DevTools) |

All exports are available via the **Exports** tab in the audit detail view.

## Vendor Detection

Odit detects 21 vendors across 5 categories:

**Analytics:** Google Analytics/GA4, Adobe Analytics, Tealium, Segment, RudderStack, Mixpanel, Amplitude, Heap

**Tag Management:** Google Tag Manager, Adobe Launch

**A/B Testing:** Optimizely, VWO, Adobe Target, LaunchDarkly, Dynamic Yield

**Consent (CMP):** OneTrust, Cookiebot, TrustArc

**Pixels:** Meta Pixel, LinkedIn Insight Tag, TikTok Pixel

Detection uses four methods (in priority order):
1. Network request domain matching
2. Script src URL pattern matching
3. Window global variable detection (`window.gtag`, `window.OneTrust`, etc.)
4. Cookie name pattern matching

## Issue Detection Rules

| Rule | Severity | Description |
|------|----------|-------------|
| Broken tracking request | High | 4xx/5xx responses from tracking endpoints |
| Failed script load | Critical | Tracking JS files fail to load |
| Console JS errors | High/Medium | Pages with 3+ JS errors |
| Missing expected vendor | High | Configured vendor not detected anywhere |
| Inconsistent vendor coverage | Medium | Vendor present on some pages in a template group but not others |
| Duplicate pageview signal | Medium | Same vendor endpoint hit 3+ times on one page |
| Consent issue (no interaction) | High | Tracking fires before consent when CMP is present |
| A/B vendor broken | High | A/B testing vendor has >50% request failure rate |
| Redirect tracking loss | Low | Redirected pages may lose attribution data |
| Template inconsistency | Medium | Same URL group has different vendor sets |

## Audit Modes

| Mode | Description |
|------|-------------|
| Quick Scan | Crawls homepage + linked pages, low page limit |
| Full Crawl | BFS crawl up to max_pages (default: 50) |
| Journey Audit | Crawls only specific seed URLs you provide |
| Regression Compare | Runs audit then compares to a previous audit |

## Configuration

Copy `.env.example` to `.env` and adjust as needed:

```env
POSTGRES_DB=odit
POSTGRES_USER=odit
POSTGRES_PASSWORD=odit_local_pass
DATABASE_URL=postgresql://odit:odit_local_pass@postgres:5432/odit
DATA_DIR=/data
PROXY_HOST=proxy
PROXY_PORT=8080
APP_PORT=8000
LOG_LEVEL=INFO
```

## Troubleshooting

**App won't start:**
```bash
docker compose logs app
docker compose logs postgres
```

**Worker not picking up jobs:**
```bash
docker compose logs worker
```
Check that `DATABASE_URL` is correct and Playwright installed successfully.

**Proxy cert issues (sites not crawling):**
```bash
docker compose logs proxy
ls data/certs/
```
The worker waits up to 60s for the mitmproxy CA cert to appear in `data/certs/`.

**No vendor detected despite it being present:**
- Some vendors only fire on user interaction (click, scroll). Odit currently captures page load traffic only.
- Ad blockers in the network may block vendor scripts — Odit crawls without ad blockers.

**Audit stuck in "running" state:**
```bash
docker compose restart worker
```
The worker will pick up pending/running audits on restart.

**Reset all data:**
```bash
./stop-auditor.sh
docker volume rm odit_postgres_data
rm -rf data/audits data/proxy_flows
./start-auditor.sh
```

## Running Tests

```bash
# From the project root (with Python + dependencies installed)
pip install -r worker/requirements.txt
pip install pytest
pytest tests/ -v
```

## Stopping Odit

```bash
./stop-auditor.sh
```

Or to stop and remove volumes (deletes all audit data):
```bash
docker compose down -v
```
