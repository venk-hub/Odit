# Odit Implementation Plan

## Overview

Odit is a local-first tracking auditor that crawls websites using a real browser (Playwright),
captures network traffic, detects analytics/marketing vendors, and flags implementation issues.

## Architecture

```
Browser (User) ──► FastAPI App (port 8000)
                       │
                       ├── Jinja2 + HTMX UI
                       ├── REST API
                       └── PostgreSQL DB
                              │
                              └── Worker (Playwright crawler)
                                     │
                                     └── mitmproxy (port 8080)
```

## Component Breakdown

### 1. FastAPI App (`app/`)
- Handles the web UI (Jinja2 templates + HTMX for live updates)
- Exposes REST API for all operations
- Uses async SQLAlchemy for DB access
- Alembic for schema migrations

### 2. PostgreSQL Database
- Stores all audit runs, configs, page visits, network requests, console events,
  detected vendors, issues, artifacts, and comparisons
- Used as the job queue (no Redis needed)

### 3. Worker (`worker/`)
- Polls DB for pending jobs using SELECT ... FOR UPDATE SKIP LOCKED
- Crawls sites using Playwright (Chromium headless)
- Routes traffic through mitmproxy for network capture
- Runs vendor detection (YAML-driven signatures)
- Runs rule engine to generate issues
- Generates export artifacts (Excel, HTML, Markdown, JSON)

### 4. mitmproxy Container
- Transparent HTTPS proxy for all browser traffic
- Addon script writes structured JSONL records to disk
- CA cert exported to shared volume so Playwright trusts it

## Data Flow

1. User submits audit form → POST /api/audits
2. App creates AuditConfig + AuditRun (status=pending) in DB
3. Worker polls DB, picks up pending run
4. Worker sets status=running, starts Playwright browser
5. Browser connects through mitmproxy proxy
6. BFS crawl: navigate each URL, capture:
   - Network requests/responses
   - Console events
   - Page metadata (title, canonical, meta description)
   - Storage (localStorage, sessionStorage, cookies)
   - Script src URLs
   - Screenshots (PNG)
   - HAR archives
7. Per-page vendor detection via YAML signatures
8. After crawl: aggregate vendors at audit level
9. Run all 10 detection rules → create Issue records
10. Generate exports: Excel (9 sheets), HTML, Markdown, JSON
11. Register artifacts in DB
12. Set status=completed
13. UI polls /api/audits/{id}/progress every 3s via HTMX

## Vendor Detection Strategy

Detection checks (in priority order):
1. **Domain match**: Does any network request go to a known tracking domain?
2. **Script src match**: Does any loaded script URL match a known pattern?
3. **Window global**: Is a known tracking global (e.g. `window.gtag`) present?
4. **Cookie match**: Is a known tracking cookie present?

## Issue Detection Rules

1. `broken_tracking_request` — 4xx/5xx on tracking endpoints
2. `failed_script_load` — Failed JS resources from tracking domains
3. `console_js_errors` — Pages with 3+ JS errors
4. `missing_expected_vendor` — Configured vendor not found anywhere
5. `inconsistent_vendor_coverage` — Vendor on some but not all pages in same group
6. `duplicate_pageview_signal` — Same domain receives 3+ requests per page
7. `consent_issue_no_interaction` — Tracking fires before consent interaction when CMP is present
8. `ab_vendor_broken` — A/B vendor has >50% request failure rate
9. `redirect_tracking_loss` — Pages with redirects may lose attribution data
10. `template_inconsistency` — Pages in same group have different vendor sets

## Export Formats

| Format | File | Contents |
|--------|------|----------|
| Excel | `audit_report.xlsx` | 9 sheets: Summary, Pages, Vendors, Issues, Broken Requests, Console Errors, Scripts, Cookies/Storage, Recommendations |
| HTML Report | `audit_summary.html` | Styled standalone HTML for sharing |
| Markdown | `audit_summary.md` | Plain text for docs/tickets |
| JSON | `audit_summary.json` | Machine-readable full audit data |
| Screenshots | `screenshots/*.png` | Per-page full-page screenshots |
| HAR files | `har/*.har` | Network traffic archives |

## Phased Delivery

1. **Core infrastructure**: DB schema, Alembic migrations, Docker Compose
2. **Crawl engine**: Playwright BFS crawler, page analyzer, proxy integration
3. **Detection layer**: Vendor YAML signatures, detection logic
4. **Rules engine**: All 10 issue detection rules
5. **UI**: Dashboard, audit detail, issue/vendor/page views
6. **Exports**: Excel, HTML, Markdown, JSON
7. **Tests**: Unit tests for detection and exports
