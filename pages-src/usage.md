# Usage Guide

## Running Your First Audit

1. Open **http://localhost:8000**
2. Paste a URL into the audit form (e.g. `https://example.com`)
3. Choose a mode:
   - **Quick Scan** — up to 50 pages, ~2 minutes
   - **Full Crawl** — up to 200 pages (configurable), deeper coverage
4. Click **Start Audit**

The live crawl view shows screenshots as each page is visited. Results appear automatically when the crawl finishes.

---

## Audit Options

| Option | Description |
|--------|-------------|
| **Max pages** | How many pages the BFS crawler will visit |
| **Consent behaviour** | `No Interaction` (default) or `Accept Consent Banners` — clicks cookie banners before crawling |
| **Logged-in user** | Paste exported browser cookies to crawl the authenticated experience |

### GDPR/CCPA Testing

Run two audits of the same site:

1. **Without consent** — reveals what fires before the user accepts the cookie banner
2. **With consent** (Accept Consent Banners) — clicks the banner, then crawls

Use the **Comparison** tab to diff both runs and see exactly what changes.

---

## Reading Results

### Executive Summary
The top section of every audit shows:
- **Risk rating** — Critical / High / Medium / Low based on issue severity
- **GDPR/CCPA posture** — Verified (consent mode used) or Unverified
- **Vendor count** — total unique vendors detected
- **Issue count** — total issues flagged, broken down by severity

### Issues Tab
Each issue includes:
- Severity (Critical / High / Medium / Low)
- Category (consent, PII, broken script, etc.)
- Affected pages
- AI-generated description, likely cause, and fix recommendation (if API key configured)

### Vendors Tab
Every detected vendor shows:
- Category (analytics, tag manager, consent, pixel, etc.)
- Detection method (domain, script, JS global, cookie)
- Pages it appeared on
- AI payload analysis — what data it collects, identifiers it assigns, PII detected in requests

### Pages Tab
Per-page breakdown of vendors detected, issues found, and network requests made.

---

## AI Features

AI features require an Anthropic API key. Set it in **Settings** (top-right nav).

### AI Assistant
Click the chat icon in the top-right to open the sidebar assistant. It can:

- Start audits: *"Audit theguardian.com with consent accepted"*
- Explain results: *"What vendors were found? Any critical issues?"*
- Read full reports: *"Read the full report and tell me the top risks"*
- Compare audits: *"Compare my last two audits of this site"*
- Schedule recurring audits: *"Schedule a weekly audit of example.com"*
- Navigate the UI: *"Show me the issues tab"*

### AI Audit Brief
Each completed audit includes an auto-generated brief covering tracking inventory, data flows, flagged issues, and priority actions. Visible in the Executive Summary section.

### Fix It
On any issue card, click **Fix It** to get step-by-step remediation guidance with code examples.

---

## Exports

Download buttons appear at the top of every completed audit:

| Format | Best for |
|--------|----------|
| **Excel (.xlsx)** | Stakeholder review — 9 sheets covering all audit data |
| **HTML report** | Sharing with clients or legal teams |
| **Markdown** | Confluence, Notion, GitHub Issues |
| **JSON** | CI/CD pipelines, automated processing |

Screenshots (PNG per page) and HAR files (full network archive) are also available under the **Exports** tab.

---

## Adding Custom Vendors

Edit `worker/detectors/vendors.yaml` — no code changes needed:

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

Restart the worker to pick up changes: `docker compose restart worker`

---

## Troubleshooting

```bash
# View logs
docker compose logs -f app
docker compose logs -f worker

# Worker stuck on a job
docker compose restart worker

# Wipe all data and start fresh
docker compose down -v && rm -rf data/audits data/proxy_flows && docker compose up -d
```

More troubleshooting help is available in the in-app **Help** page at `/help`.
