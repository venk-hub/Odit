<div align="center">
  <img src="app/static/odit.svg" alt="Odit" height="72" />
  <br /><br />
  <strong>Local-first website tracking auditor</strong>
  <br />
  Crawl any site with a real browser, capture every network request, detect martech vendors, flag compliance issues — all on your own machine.
  <br /><br />

  ![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
  ![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
  ![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi&logoColor=white)
  ![Playwright](https://img.shields.io/badge/Playwright-Chromium-45BA4B?logo=playwright&logoColor=white)
  ![License](https://img.shields.io/badge/License-AGPL_v3-blue)
</div>

---

## What is Odit?

Odit is a four-container Docker Compose appliance that turns any website into a complete tracking audit — vendors detected, issues flagged, cookies catalogued, consent behaviour verified, and a full network capture ready to download. No cloud, no subscription, no data leaving your machine.

---

## Features

### Core Auditing
- **Real browser crawl** — Playwright (headless Chromium) with BFS page discovery
- **Full network capture** — every request intercepted by mitmproxy, including HTTPS
- **Vendor detection** — 40+ vendors matched by domain, script, JS global, and cookie signatures
- **10 issue rules** — broken scripts, consent violations, PII in URLs, duplicate signals, missing vendors, and more
- **Logged-in user audits** — inject session cookies so the crawler sees the authenticated experience
- **Consent banner acceptance** — automatically click cookie consent banners before crawling to verify post-consent tracking behaviour (supports OneTrust, Cookiebot, Didomi, TrustArc, Quantcast, CookieYes, Osano, Borlabs, Klaro, Termly, Civic, and a text-content fallback for any other CMP)

### Results & Reports
- **Executive summary** — risk rating, GDPR/CCPA posture, vendor category breakdown
- **Consent mode badge** — each audit shows whether it ran with or without consent interaction
- **Vendor tag attribution** — each vendor tagged as Via GTM / Via Adobe Launch / Direct / Beacon / Pixel
- **Performance impact** — estimated request weight and timing per vendor
- **Cookie register** — every cookie set during the crawl with full metadata
- **9-sheet Excel export** — summary, vendors, issues, pages, network requests, cookies, data layer, consent analysis, recommendations
- **HTML, Markdown, JSON reports** — shareable and CI-ready
- **One-click export buttons** — Excel / HTML / MD / JSON download buttons in the audit detail header
- **Live crawl view** — crossfading screenshot stream while the audit is running

### AI Features *(requires Anthropic API key — set in Settings)*
- **Agentic AI assistant** — sidebar chat that can take direct action: start audits, check progress, navigate the UI, schedule recurring audits, compare two audits
- **AI Audit Brief** — auto-generated structured brief covering tracking inventory, data flows, issues, and priority actions
- **Issue enrichment** — each issue gets an AI-written description, likely cause, and recommendation
- **Fix It** — per-issue step-by-step remediation guide with code examples
- **Read report tool** — the AI can read your full markdown or JSON audit report from disk to answer detailed questions
- **Live panel navigation** — the AI drives the right panel as it works, showing you exactly what it's doing

### UI
- **Live progress** — HTMX-powered real-time crawl updates (no refresh needed)
- **Dark mode** — full dark/light toggle, persisted across sessions
- **Resizable AI chat panel** — collapsible sidebar, width saved per session
- **Rich markdown rendering** — AI responses render tables, code blocks, headings, and lists correctly via marked.js (GFM)
- **Multi-conversation history** — persistent chat sessions with full history
- **Contextual `i` triggers** — clickable info buttons that pre-fire relevant chat questions
- **Help page** — full in-app documentation at `/help` covering quick start, example use case, result interpretation, troubleshooting FAQ, and legal notices
- **GitHub link & license** — nav bar links to source and AGPL-3.0 licence

---

## Quick Start

**Requirements:** [Docker Desktop](https://www.docker.com/products/docker-desktop)

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

---

## Enabling AI Features

AI features use the Anthropic API (Claude). To enable them:

1. Open the app at `http://localhost:8000`
2. Go to **Settings** (top-right nav)
3. Enter your Anthropic API key under **AI Configuration**
4. Click **Save** — the key is stored in the local database and never leaves your machine

> Get a key at [console.anthropic.com](https://console.anthropic.com).

Alternatively, set `ANTHROPIC_API_KEY` in your `.env` file before starting — this takes priority over the Settings value and makes the field read-only in the UI.

---

## Audit Modes & Options

| Option | Values | Description |
|--------|--------|-------------|
| **Mode** | Quick Scan / Full Crawl | Quick Scan: up to 50 pages (~2 min). Full Crawl: configurable depth (default 200 pages). |
| **Consent behaviour** | No Interaction / Accept Consent Banners | Accept Consent clicks cookie banners before crawling — use this to verify post-consent tracking and get a verified GDPR/CCPA posture. |
| **Logged-in user** | Off / On | Inject exported browser cookies so the crawler audits the authenticated experience. |

### Consent Mode — GDPR/CCPA Testing

Run two audits of the same site:

1. **Without consent** (default) — reveals what fires before the user interacts with the banner. GDPR/CCPA posture shows as *Unverified*.
2. **With consent** (Accept Consent Banners) — clicks the banner, then crawls. Shows what fires after consent. Use the **Comparison** tab to diff the two runs.

The `_try_accept_consent` function covers 30+ CSS selectors for major CMPs, plus a text-content fallback that clicks any visible button matching phrases like "Accept all", "I agree", "Allow cookies", etc.

---

## AI Agent Capabilities

The sidebar assistant is fully agentic — it takes action, not just answers questions.

| What you say | What it does |
|---|---|
| "Audit theguardian.com" | Starts the audit immediately, navigates you to the live progress page |
| "Audit it with consent accepted" | Starts with `consent_behavior: accept_consent` |
| "Audit as logged-in user — here are my cookies: [...]" | Injects your session cookies before crawling |
| "What vendors were found?" | Queries the database and gives you specific results |
| "Any critical issues?" | Fetches and explains the issues directly |
| "Read the full report and tell me the top risks" | Reads the markdown audit report from disk |
| "Compare my last two audits" | Diffs vendors and issues, summarises what changed |
| "Schedule a weekly audit of example.com" | Creates a recurring schedule |
| "Show me the issues page" | Navigates the right panel for you |

---

## Architecture

```
postgres   ← shared DB (SQLAlchemy models, Alembic migrations)
   ↕
app        ← FastAPI + Jinja2/HTMX UI (port 8000)
   ↕
worker     ← Playwright crawler, vendor detection, rule engine, AI enrichment
   ↕
proxy      ← mitmproxy (port 8080) — intercepts all browser traffic
```

**Data flow:**
1. Paste URL → click Start Audit → `AuditRun` created (status: pending)
2. Worker picks up the job, launches Playwright routed through mitmproxy
3. If consent mode is `accept_consent`, crawler clicks the banner before crawling
4. Evidence written to `/data/audits/{id}/` and normalised into Postgres
5. Vendor detection + rule engine run after crawl
6. AI enrichment runs (if API key configured)
7. Exports generated — Excel, HTML, Markdown, JSON
8. UI polls progress every 3s via HTMX; reloads to results view on completion

---

## Vendor Detection

Vendors are detected via four signal types matched against `worker/detectors/vendors.yaml`:

| Signal | Example |
|--------|---------|
| Domain | requests to `analytics.google.com` |
| Script | `gtm.js`, `analytics.js` loaded on page |
| JS global | `window.gtag`, `window.fbq`, `window._satellite` |
| Cookie | `_ga`, `_fbp`, `OptanonConsent` |

**To add a vendor** — edit `vendors.yaml`, no code change needed:

```yaml
vendors:
  - key: my_vendor
    name: My Vendor
    category: analytics
    signatures:
      domains: [cdn.myvendor.com]
      script_patterns: [myvendor.js]
      window_globals: [window.myVendor]
      cookie_patterns: [_mv_]
```

---

## Issue Detection

| Rule | Severity |
|------|----------|
| Tracking script failed to load | Critical |
| Broken tracking request (4xx/5xx) | High |
| Tracking fires before consent | High |
| Missing consent manager | High |
| PII detected in page URL | High |
| Unexpected vendor detected | Medium |
| Missing expected vendor | Medium |
| Duplicate tracking signals | Medium |
| Inconsistent vendor coverage | Medium |
| High request volume | Low |

> The "Tracking fires before consent" rule is automatically skipped when the audit runs with `consent_behavior: accept_consent` — pre-consent state is not observable in that mode.

---

## Exports

| Format | Contents |
|--------|----------|
| **Excel (.xlsx)** | 9 sheets — summary, vendors, issues, pages, network, cookies, data layer, consent, recommendations |
| **HTML report** | Styled standalone file — shareable with stakeholders |
| **Markdown** | Plain text for Confluence, Notion, or GitHub Issues |
| **JSON** | Machine-readable — CI/CD integration ready |
| **Screenshots** | Full-page PNG per crawled page |
| **HAR files** | Full network archive, openable in Chrome DevTools |

Download buttons for all formats appear at the top of the audit detail page once the crawl completes. All exports are also available under the **Exports** tab.

---

## Pages & Navigation

| URL | Description |
|-----|-------------|
| `/` | Dashboard — new audit form + previous audits list |
| `/audits/{id}` | Audit detail — summary, export buttons, per-page breakdown |
| `/audits/{id}/issues` | Full issues list with severity and category filters |
| `/audits/{id}/exports` | All generated report artifacts with download links |
| `/audits/{id}/vendors` | Vendor inventory with categories and attribution |
| `/audits/{id}/pages` | Per-page crawl results |
| `/audits/{id}/comparison` | Side-by-side diff of two audits of the same domain |
| `/settings` | Anthropic API key configuration and crawl defaults |
| `/help` | Full in-app documentation, use cases, troubleshooting, legal notices |

---

## Configuration

```env
# .env
DATABASE_URL=postgresql://odit:odit_local_pass@postgres:5432/odit
DATA_DIR=/data
PROXY_HOST=proxy
PROXY_PORT=8080
APP_PORT=8000
ANTHROPIC_API_KEY=        # optional — can also be set in the app Settings UI
```

---

## License & Privacy

Odit is released under the **GNU Affero General Public License v3.0 (AGPL-3.0)**. See [LICENSE](LICENSE).

**Data privacy:** Everything runs locally in Docker. The only outbound connections are browser traffic to the site you are auditing, and Anthropic API calls if you have configured a key. Audit data never leaves your machine via Odit.

**Responsible use:** Only audit websites you own or have explicit permission to test. Repeated automated crawling may be detected and blocked by site owners or CDN rate-limiting systems.

---

## Troubleshooting

```bash
# View logs
docker compose logs -f app
docker compose logs -f worker
docker compose logs -f proxy

# Worker stuck — restart it
docker compose restart worker

# Wipe everything and start fresh
docker compose down -v
rm -rf data/audits data/proxy_flows
docker compose up -d
```

Common issues and solutions are also covered in the in-app **Help** page at `/help`.

---

## Development

```bash
# Run app locally (no Docker)
cd app && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Run worker locally
cd worker && pip install -r requirements.txt
playwright install chromium
python worker/main.py

# DB migrations
alembic upgrade head
alembic revision --autogenerate -m "description"

# Tests
pytest tests/ -v
```

---

<div align="center">
  <a href="https://github.com/venk-hub/Odit">GitHub</a> &nbsp;&middot;&nbsp;
  <a href="https://www.gnu.org/licenses/agpl-3.0.html">AGPL-3.0</a>
  <br /><br />
  <sub>Odit — local-first tracking auditor</sub>
</div>
