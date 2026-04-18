"""
Help chat endpoint — streams Claude responses about how to use Odit.
"""
import json
import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

logger = logging.getLogger("odit.help")

router = APIRouter(prefix="/api/help", tags=["help"])

SYSTEM_PROMPT = """You are **Odit AI** — an agentic AI assistant embedded inside the Odit tracking auditor. You are not just a help bot; you are a professional digital analytics engineer who can both answer questions AND take direct action inside the app.

## CORE PRINCIPLES

**ACT, DON'T INSTRUCT** — When a user asks you to do something you have a tool for, DO IT immediately. Never say "paste the URL and click Start Audit" when you can call `start_audit` yourself.

**NAVIGATE the panel as you act** — The right panel is an iframe you can drive. Use `navigate_to` to show the user what's happening as you work:
- After `start_audit` → always call `navigate_to` with `/audits/{id}` so the user sees live progress
- After `schedule_audit` → navigate to `/` so they see the audit list
- When user asks about a specific audit → navigate to `/audits/{id}`
- When user asks to see issues → navigate to `/audits/{id}/issues`
- When user asks to see exports or downloads → navigate to `/audits/{id}/exports`
- When user asks to see the dashboard or home → navigate to `/`
- When user asks about settings → navigate to `/settings`
- After `compare_audits` → navigate to the newer audit's detail page
- For query-only tools (get_issues, get_vendors, get_pages) → do NOT navigate, just answer in chat

`navigate_to` no longer causes a page reload — it updates the right panel iframe independently. The chat stays alive.

Follow the **ReAct pattern**: Reason about what's needed → Act (call a tool) → Observe the result → Reason again → Act again → … → Deliver a clear answer.

## WHAT YOU CAN DO

**Action tools (you can make things happen):**
- `start_audit` — Start a new website audit crawl (supports auth cookies for logged-in audits).
- `get_audit_progress` — Check live status/progress of a running audit.
- `navigate_to` — Navigate the right panel to any page in the app on the user's behalf.
- `schedule_audit` — Schedule a recurring audit (daily/weekly/monthly).
- `list_schedules` — List all active scheduled audits.
- `cancel_schedule` — Cancel a scheduled audit by ID.
- `compare_audits` — Compare two audits: vendor diff, issue diff, summary.

**Query tools (look up existing data):**
- `list_audits`, `get_audit`, `get_issues`, `get_vendors`, `get_pages`
- `get_network_requests` — Query raw captured network requests. Use this to verify specific tracking fired, inspect POST payloads, check what data a vendor sent, or confirm a beacon fired on the right page. Supports filtering by vendor, URL pattern, page, failed-only.
- `read_report` — Read the full exported markdown or JSON report for a completed audit. Use this for comprehensive breakdowns, "tell me everything", or when you need details beyond what the individual query tools return (e.g. cookie register, data layer events, performance impact, full issue descriptions).

## HOW TO HANDLE COMMON REQUESTS

**"Audit [website]" / "Can you audit X?"**
→ Call `start_audit` immediately with the URL. Then call `navigate_to` with `/audits/{audit_id}` to show them live progress.
→ Respond: "I've started the audit for [url] and navigated you to the live progress page. I'll be scanning up to 50 pages — ask me anything once it's done."

**"What vendors / issues were found?"**
→ Call `list_audits` to find the right audit, then `get_vendors` or `get_issues` for data.
→ Give specific answers from the data — never generic advice.

**"How is my audit going?" / "Is it done?"**
→ Call `get_audit_progress` with the audit ID.

**"Take me to [page]" / "Navigate to..." / "Open the audit" / "Show me the dashboard" / "Show me the issues" / "Show me the exports"**
→ Call `navigate_to` with the appropriate path.
→ App routes: `/` (home/dashboard), `/audits/{id}` (audit detail), `/audits/{id}/issues` (full issues list), `/audits/{id}/exports` (exports & downloads), `/settings` (settings)
→ After navigating, briefly tell the user what they're now looking at.

**"Audit [site] as logged-in user" / "use these cookies..."**
→ Call `start_audit` with the `auth_cookies_json` parameter containing the cookie array.

**"Click [element] and check if [vendor] fires" / "Test the Add to Cart tracking" / "Run a journey audit"**
→ Call `start_audit` with `journey_instructions` as a list of plain-English steps (e.g. `["click the Add to Cart button", "fill the email field with test@example.com"]`). Mode is set automatically to journey_audit.
→ Once complete, call `get_network_requests` filtered by vendor to confirm what fired during the interaction.

**"Did [vendor] fire?" / "What did [vendor] send?" / "Check if GA4 fired on checkout" / "Show me the Adobe Analytics payload"**
→ Call `get_network_requests` with the audit_id and relevant vendor_key or url_pattern.
→ Inspect the post_data field to verify payloads. Explain what the data means in plain English.

**"Schedule an audit of [site] every [day/week/month]"**
→ Call `schedule_audit` immediately. Confirm with: "Done — I've scheduled a [frequency] audit of [url]. [View schedules](/settings)"

**"What are my scheduled audits?" / "Show me my schedules"**
→ Call `list_schedules` and summarise the results.

**"Cancel/stop the [schedule]"**
→ Call `cancel_schedule` with the schedule ID.

**"Compare [audit A] and [audit B]" / "What changed between audits?"**
→ Call `compare_audits` with the two audit IDs. Summarise: new/removed vendors, new/resolved issues.

**General questions about how to use Odit**
→ Answer directly from your knowledge of the app.

## STYLE
- Be direct and conversational. One expert sentence beats three generic ones.
- Use markdown: bullet points, **bold** for key terms, `code` for values/IDs.
- When you start an audit, always include the link as a markdown hyperlink: `[View progress](/audits/{id})`
- After starting an audit, tell the user what to expect (time, pages).

---

Odit crawls websites using a real browser (Playwright), intercepts all network traffic via mitmproxy, detects analytics/martech vendors, flags compliance and implementation issues, and generates detailed reports. It runs entirely on the user's machine via Docker Compose.

---

## CORE CONCEPTS

**Audit** — A crawl job for one website. Each audit produces vendors, issues, pages, a network capture, and reports.

**Audit statuses:**
- **Pending** — queued, waiting for the worker to pick it up
- **Running** — crawler is active right now
- **Completed** — crawl finished successfully
- **Failed** — crawler encountered a fatal error
- **Cancelled** — user cancelled it before or during the run

---

## AUDIT MODES

- **Quick Scan** — BFS crawl up to 50 pages, max depth 3. Good for a fast overview.
- **Full Crawl** — No page limit cap — set as many pages as you need (default 200). Comprehensive but slower. The user sets the page count themselves.
- **Journey Audit** — Follows a specific user journey (e.g. add to cart, checkout) using natural language instructions that get converted to Playwright actions. Use this to test tracking on specific flows.

**Device types:** Desktop or Mobile (changes the browser user-agent and viewport).

**Consent behaviour:** What to do with cookie consent banners:
- No Interaction — ignore banners, see pre-consent state
- Accept All — click the accept button, see post-consent tracking
- Reject All — click reject, verify no tracking fires

---

## CREATING AN AUDIT

The homepage (/) combines the audit form and previous audits list in one place:

1. Paste the website URL into the input bar at the top (must include https://)
2. Choose **Quick Scan** (50 pages, fast) or **Full Crawl** (set your own page count, no cap)
3. Optionally click **"Audit as logged-in user"** — expands a textarea where you paste session cookies exported from your browser as JSON (e.g. via Cookie-Editor extension). The crawler injects these before starting so it sees the site as a logged-in user.
4. Click **Start Audit** — you're redirected to the live audit progress page

Previous audits are listed below the form on the same page.

---

## READING AUDIT RESULTS

### Overview tab
- **Stats cards** — pages discovered, crawled, failed, vendors detected
- **Issue severity counts** — Critical / High / Medium / Low
- **Executive Summary** — risk rating, GDPR/CCPA posture, vendor category breakdown
- **AI Audit Brief** — a Claude-generated structured brief covering: tracking inventory, data flows, data layer variables, issues found, and priority actions
- **Cookie Register** — all cookies set during the crawl with name, domain, path, expiry
- **Performance Impact** — estimated request weight per vendor

### Pages tab
Shows every crawled URL with its individual vendor and issue counts. Click any page to drill in to its specific network requests, console events, vendors, and screenshots.

### Issues tab
Full list of all detected issues, filterable by severity. Each issue has:
- Severity (Critical / High / Medium / Low)
- Category (consent, data_quality, vendor_presence, etc.)
- Title and description
- Likely cause and recommendation (AI-enriched)
- Click **Fix It** to get step-by-step remediation with code examples

---

## VENDORS

Vendors are detected via four signal types:
- **Domain** — network requests to known vendor domains
- **Script** — known script filenames loaded on the page
- **Window global** — JavaScript globals like `window.gtag`, `window.fbq`
- **Cookie** — cookies with known vendor naming patterns

Vendor detection is powered by `worker/detectors/vendors.yaml` — a YAML registry of signatures. It can be extended without code changes.

---

## ISSUES

The rule engine detects 10 categories of issues:
- **Missing consent manager** — no CMP detected at all
- **Tracking before consent** — requests fire before consent is given
- **Broken tracking requests** — domains returning errors (4xx/5xx)
- **PII in URL** — email addresses, phone numbers in page URLs
- **Unexpected vendors** — vendors found that weren't in your expected list
- **Missing expected vendors** — vendors you expected that weren't found
- **High request volume** — unusually large number of tracking requests
- **Unrecognised third-party domains** — unknown external domains (potential data leakage)
- **Missing data layer** — no dataLayer / utag_data / digitalData found
- **Inconsistent vendor presence** — vendor detected on some pages but not others

---

## AI FEATURES (requires ANTHROPIC_API_KEY)

All AI features use **Claude Haiku** and degrade gracefully if no API key is set.

- **AI Audit Brief** — auto-generated after each audit. Can be re-run via the "Re-run AI" button.
- **Issue enrichment** — each issue gets an AI-written description, likely cause, and recommendation (batched, ~1 API call per 20 issues)
- **Fix It / Remediation steps** — per-issue step-by-step fix guide with code snippets
- **Unknown domain inference** — Claude identifies unrecognised third-party domains
- **Vendor suggestions** — before crawling, Claude predicts which vendors to expect based on the URL
- **Journey instructions** — natural language steps converted to Playwright actions for Journey Audit mode

Set `ANTHROPIC_API_KEY` in your `.env` file or Docker environment to enable these.

---

## COMPARISONS

Compare two audits of the same site to see what changed:
1. Go to **New Audit** and select a "Compare with previous audit" option
2. Or use the comparison API directly

Comparisons show: new issues introduced, issues resolved, vendors added/removed, and an AI-written regression summary.

---

## EXPORTS

Each completed audit generates:
- **Excel (.xlsx)** — 9-sheet workbook: summary, vendors, issues, pages, network requests, cookies, data layer, consent analysis, page details
- **HTML report** — standalone file, shareable
- **Markdown report** — plain text summary
- **JSON** — machine-readable full audit data

Download buttons appear in the top-right of the audit detail page once the audit is complete.

---

## SETTINGS

Accessible via the **Settings** link in the nav. Configure:
- Default crawl settings (max pages, depth, device type)
- AI enrichment on/off
- Any app-level preferences

---

## DELETING AUDITS

- **From the homepage** — hover a row in the previous audits list, click the trash icon on the right
- **From the audit detail page** — click the red "Delete" button in the top-right
- Both show a confirmation dialog before deleting
- Deletion removes the database record AND all file artifacts (screenshots, HAR files, reports)

---

## FILE STORAGE

All artifacts are stored in `./data/` on the host machine (mounted at `/data` in containers):
```
data/audits/{audit_id}/
  screenshots/    PNG screenshots per page
  har/            HAR files
  json/           Evidence JSON per page
  reports/        Excel, HTML, Markdown, JSON reports
data/proxy_flows/ JSONL files from mitmproxy
```

---

## CLEARING ALL DATA

To wipe everything and start fresh:
```bash
docker compose down -v                         # removes the database volume
rm -rf ./data/audits/* ./data/proxy_flows/*   # removes file artifacts
docker compose up -d                           # restart
```

---

## ARCHITECTURE

```
postgres   ← shared database
app        ← FastAPI web app (port 8000): UI + API
worker     ← Playwright crawler, vendor detection, rule engine, AI enrichment
proxy      ← mitmproxy (port 8080): intercepts browser traffic
```

The worker polls the database for pending audit jobs, runs the crawler, writes evidence to disk and DB, then runs vendor detection, issue rules, AI enrichment, and export generation.

---

## EXTENDING THE APP

**Add a new vendor** — edit `worker/detectors/vendors.yaml`, add an entry with domain/script/global/cookie signatures. No code change needed.

**Add a new issue rule** — add a function to `worker/rules/rule_engine.py` and register it in `ALL_RULES`.

**Add an export sheet** — edit `worker/exports/excel_exporter.py`.

---

You have access to tools that can query live audit data from the database. Use them when the user asks about specific audits, vendors, issues, or pages — don't guess, look it up. When answering questions about data, always use the tools to get current information.

Answer the user's question based on the above. If they ask something not covered here, say so honestly. Do not make up features that don't exist."""


AGENT_TOOLS = [
    {
        "name": "start_audit",
        "description": "Start a new website audit crawl. Use this whenever the user asks to audit a URL — don't explain how to do it manually, just do it. Returns the audit ID and a link to view live progress.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The website URL to audit. Add https:// if missing.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["quick_scan", "full_crawl"],
                    "description": "quick_scan = up to 50 pages, ~2 minutes. full_crawl = up to max_pages, more comprehensive. Default: quick_scan",
                    "default": "quick_scan",
                },
                "max_pages": {
                    "type": "integer",
                    "description": "Max pages for full_crawl mode (default 200). Ignored for quick_scan.",
                    "default": 200,
                },
                "auth_cookies_json": {
                    "type": "string",
                    "description": "Optional JSON string — array of cookie objects to inject before crawling (for logged-in audits). Each object should have 'name', 'value', 'domain' fields. Paste exactly what the user provides.",
                },
                "consent_behavior": {
                    "type": "string",
                    "enum": ["no_interaction", "accept_consent", "reject_consent"],
                    "description": "How to handle cookie consent banners. no_interaction = ignore banners (default, shows pre-consent state). accept_consent = click accept (shows post-consent tracking). reject_consent = click reject.",
                    "default": "no_interaction",
                },
                "journey_instructions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of natural language interaction steps to perform on the landing page before crawling — e.g. ['click the Add to Cart button', 'fill the search box with trainers', 'click the first search result']. When provided, the audit runs in journey mode: it executes these steps on the seed URL, captures all network traffic fired during the interactions, then continues crawling. Use this to verify that specific user actions (button clicks, form submissions) trigger the expected tracking.",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "get_network_requests",
        "description": "Query captured network requests from a completed audit. Use this to verify whether specific tracking fired, inspect POST payloads, check what data was sent to a vendor, or confirm that a beacon fired on the right page. Returns URL, method, status, vendor, page, and POST body for each matching request.",
        "input_schema": {
            "type": "object",
            "properties": {
                "audit_id": {
                    "type": "string",
                    "description": "The audit ID to query.",
                },
                "vendor_key": {
                    "type": "string",
                    "description": "Filter by vendor key (e.g. 'google_analytics', 'meta_pixel'). Leave blank for all vendors.",
                },
                "url_pattern": {
                    "type": "string",
                    "description": "Filter requests whose URL contains this string (e.g. 'collect', 'analytics.google.com'). Case-insensitive.",
                },
                "page_url": {
                    "type": "string",
                    "description": "Filter requests captured on a specific page URL. Partial match.",
                },
                "tracking_only": {
                    "type": "boolean",
                    "description": "If true (default), return only tracking-related requests. Set to false to include all network requests.",
                    "default": True,
                },
                "failed_only": {
                    "type": "boolean",
                    "description": "If true, return only failed requests (4xx/5xx or network errors).",
                    "default": False,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 40, max 100).",
                    "default": 40,
                },
            },
            "required": ["audit_id"],
        },
    },
    {
        "name": "navigate_to",
        "description": "Navigate the right panel (main app view) to a specific page on behalf of the user. Use this when the user asks to be taken somewhere, or after completing an action where it makes sense to redirect (e.g. after starting an audit, navigate to its progress page).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "App-relative path to navigate to. Examples: '/', '/audits/{id}', '/audits/{id}/issues', '/audits/{id}/exports', '/settings'",
                },
                "label": {
                    "type": "string",
                    "description": "Human-readable description of the destination, e.g. 'audit progress page'",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "schedule_audit",
        "description": "Schedule a recurring audit that runs automatically at the specified frequency.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The website URL to audit on schedule.",
                },
                "frequency": {
                    "type": "string",
                    "enum": ["daily", "weekly", "monthly"],
                    "description": "How often to run the audit.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["quick_scan", "full_crawl"],
                    "default": "quick_scan",
                    "description": "Audit mode for each scheduled run.",
                },
                "label": {
                    "type": "string",
                    "description": "Optional friendly name for this schedule, e.g. 'Weekly CNN check'",
                },
            },
            "required": ["url", "frequency"],
        },
    },
    {
        "name": "list_schedules",
        "description": "List all active scheduled audits.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "cancel_schedule",
        "description": "Cancel (deactivate) a scheduled audit by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "schedule_id": {
                    "type": "string",
                    "description": "UUID of the scheduled audit to cancel.",
                }
            },
            "required": ["schedule_id"],
        },
    },
    {
        "name": "compare_audits",
        "description": "Compare two audits of the same (or different) sites. Returns vendor diff (added/removed), issue diff (new/resolved), and a summary of changes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "audit_id_a": {
                    "type": "string",
                    "description": "UUID of the first (older/baseline) audit.",
                },
                "audit_id_b": {
                    "type": "string",
                    "description": "UUID of the second (newer) audit.",
                },
            },
            "required": ["audit_id_a", "audit_id_b"],
        },
    },
    {
        "name": "get_audit_progress",
        "description": "Check the live status and progress of an audit that is pending or running.",
        "input_schema": {
            "type": "object",
            "properties": {
                "audit_id": {
                    "type": "string",
                    "description": "The UUID of the audit run",
                }
            },
            "required": ["audit_id"],
        },
    },
    {
        "name": "list_audits",
        "description": "List the most recent audits with summary stats. Use this to answer questions like 'what audits do I have', 'show me recent audits', or when you need to find an audit ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of audits to return (default 10, max 20)",
                    "default": 10,
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_audit",
        "description": "Get full details for a specific audit including vendors, issue counts, pages crawled, cookie count, and top issues.",
        "input_schema": {
            "type": "object",
            "properties": {
                "audit_id": {
                    "type": "string",
                    "description": "The UUID of the audit run",
                }
            },
            "required": ["audit_id"],
        },
    },
    {
        "name": "get_issues",
        "description": "Get issues detected in an audit, optionally filtered by severity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "audit_id": {
                    "type": "string",
                    "description": "The UUID of the audit run",
                },
                "severity": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low"],
                    "description": "Filter by severity (optional — omit to get all severities)",
                },
            },
            "required": ["audit_id"],
        },
    },
    {
        "name": "get_vendors",
        "description": "Get all vendors detected in an audit with their category, page count, detection method, and evidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "audit_id": {
                    "type": "string",
                    "description": "The UUID of the audit run",
                }
            },
            "required": ["audit_id"],
        },
    },
    {
        "name": "get_pages",
        "description": "Get pages crawled in an audit with their URL, status code, vendor count, issue count, and load time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "audit_id": {
                    "type": "string",
                    "description": "The UUID of the audit run",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of pages to return (default 20, max 100)",
                    "default": 20,
                },
            },
            "required": ["audit_id"],
        },
    },
    {
        "name": "read_report",
        "description": "Read the full exported report for a completed audit. Returns the complete markdown report including executive summary, all vendors, all issues, cookie register, and data layer. Use this when the user asks for a comprehensive breakdown, wants to understand everything that was found, or asks about specific details that require the full report. Prefer this over multiple individual query tools when the user wants a complete picture.",
        "input_schema": {
            "type": "object",
            "properties": {
                "audit_id": {
                    "type": "string",
                    "description": "The UUID of the audit run",
                },
                "format": {
                    "type": "string",
                    "enum": ["markdown", "json"],
                    "description": "Report format to read. Use 'markdown' for narrative summaries, 'json' for structured data queries. Default: markdown.",
                    "default": "markdown",
                },
            },
            "required": ["audit_id"],
        },
    },
]

TOOL_LABELS = {
    "start_audit":         "Starting audit...",
    "get_audit_progress":  "Checking audit progress...",
    "navigate_to":         "Navigating...",
    "schedule_audit":      "Setting up schedule...",
    "list_schedules":      "Loading schedules...",
    "cancel_schedule":     "Cancelling schedule...",
    "compare_audits":      "Comparing audits...",
    "list_audits":         "Looking up your audits...",
    "get_audit":           "Loading audit details...",
    "get_issues":          "Fetching issues...",
    "read_report":         "Reading audit report...",
    "get_vendors":         "Fetching vendors...",
    "get_pages":           "Loading pages...",
    "get_network_requests": "Querying network requests...",
}


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class HelpChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []
    page_context: Optional[str] = None


async def _get_audit_context(db) -> str:
    """Fetch a read-only summary of recent audits to inject as context."""
    try:
        from sqlalchemy import select, func, desc
        from app.models import AuditRun, Issue, DetectedVendor

        result = await db.execute(
            select(AuditRun).order_by(desc(AuditRun.created_at)).limit(20)
        )
        runs = result.scalars().all()
        if not runs:
            return "No audits have been run yet."

        lines = ["The user has the following audits (most recent first):"]
        for run in runs:
            issue_result = await db.execute(
                select(Issue.severity, func.count(Issue.id))
                .where(Issue.audit_run_id == run.id)
                .group_by(Issue.severity)
            )
            counts = {row[0]: row[1] for row in issue_result}

            vendor_result = await db.execute(
                select(func.count(DetectedVendor.id))
                .where(DetectedVendor.audit_run_id == run.id)
                .where(DetectedVendor.page_visit_id == None)
            )
            vendor_count = vendor_result.scalar() or 0

            top_issues_result = await db.execute(
                select(Issue.title, Issue.severity)
                .where(Issue.audit_run_id == run.id)
                .order_by(
                    Issue.severity.in_(["critical"]).desc(),
                    Issue.severity.in_(["high"]).desc(),
                )
                .limit(5)
            )
            top_issues = top_issues_result.all()

            issue_summary = ", ".join(
                f"{v}{k[0].upper()}" for k, v in sorted(
                    counts.items(),
                    key=lambda x: ["critical","high","medium","low"].index(x[0]) if x[0] in ["critical","high","medium","low"] else 9
                ) if v > 0
            ) or "no issues"

            created = run.created_at.strftime("%b %d, %Y %H:%M") if run.created_at else "unknown"
            lines.append(
                f"\n- ID: {run.id} | URL: {run.base_url} | Mode: {run.mode.value} | "
                f"Status: {run.status.value} | Pages: {run.pages_crawled} | "
                f"Vendors: {vendor_count} | Issues: {issue_summary} | Created: {created}"
            )
            if top_issues:
                for title, sev in top_issues:
                    lines.append(f"    • [{sev.upper()}] {title}")

        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Could not fetch audit context: {e}")
        return ""


async def _get_api_key(db) -> str:
    """Check env first, then the database settings — same priority as the worker."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    try:
        from sqlalchemy import select
        from app.models.setting import AppSetting
        result = await db.execute(select(AppSetting).where(AppSetting.key == "anthropic_api_key"))
        setting = result.scalar_one_or_none()
        if setting and setting.value:
            return setting.value.strip()
    except Exception:
        pass
    return ""


async def _execute_tool(tool_name: str, tool_input: dict, db) -> str:
    """Execute a tool call and return a JSON string result."""
    try:
        from sqlalchemy import select, func, desc
        from app.models import AuditRun, AuditStatus, Issue, DetectedVendor, PageVisit, NetworkRequest

        if tool_name == "start_audit":
            from urllib.parse import urlparse
            from app.models import AuditConfig

            url = tool_input.get("url", "").strip()
            if url and not url.startswith(("http://", "https://")):
                url = "https://" + url
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return json.dumps({"error": "Invalid URL. Please provide a valid website address."})

            journey_instructions = tool_input.get("journey_instructions") or []
            mode = tool_input.get("mode", "quick_scan")
            if journey_instructions:
                mode = "journey_audit"
            elif mode not in ("quick_scan", "full_crawl"):
                mode = "quick_scan"
            max_pages = 50 if mode in ("quick_scan", "journey_audit") else int(tool_input.get("max_pages", 200))

            # Parse auth cookies if provided
            auth_cookies = None
            auth_cookies_json = tool_input.get("auth_cookies_json", "").strip()
            if auth_cookies_json:
                try:
                    auth_cookies = json.loads(auth_cookies_json)
                    if not isinstance(auth_cookies, list):
                        auth_cookies = None
                except Exception:
                    auth_cookies = None

            config = AuditConfig(
                base_url=url,
                mode=mode,
                max_pages=max_pages,
                max_depth=3,
                allowed_domains=[parsed.netloc],
                device_type="desktop",
                consent_behavior=tool_input.get("consent_behavior", "no_interaction"),
                expected_vendors=[],
                include_patterns=[],
                exclude_patterns=[],
                seed_urls=[],
                journey_instructions=journey_instructions,
                auth_cookies=auth_cookies,
            )
            db.add(config)
            await db.flush()

            run = AuditRun(
                base_url=url,
                mode=mode,
                status=AuditStatus.pending,
                config_id=config.id,
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)

            return json.dumps({
                "success": True,
                "audit_id": str(run.id),
                "url": url,
                "mode": mode,
                "max_pages": max_pages,
                "status": "pending",
                "view_url": f"/audits/{run.id}",
                "auth_injected": auth_cookies is not None,
                "journey_steps": len(journey_instructions),
            })

        elif tool_name == "get_audit_progress":
            audit_id = tool_input["audit_id"]
            result = await db.execute(select(AuditRun).where(AuditRun.id == audit_id))
            run = result.scalar_one_or_none()
            if not run:
                return json.dumps({"error": f"Audit {audit_id} not found."})

            issue_count_result = await db.execute(
                select(func.count(Issue.id)).where(Issue.audit_run_id == run.id)
            )
            vendor_count_result = await db.execute(
                select(func.count(DetectedVendor.id))
                .where(DetectedVendor.audit_run_id == run.id)
                .where(DetectedVendor.page_visit_id == None)
            )

            return json.dumps({
                "audit_id": str(run.id),
                "url": run.base_url,
                "status": run.status.value,
                "pages_crawled": run.pages_crawled or 0,
                "pages_discovered": run.pages_discovered or 0,
                "pages_failed": run.pages_failed or 0,
                "issues_found": issue_count_result.scalar() or 0,
                "vendors_found": vendor_count_result.scalar() or 0,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "view_url": f"/audits/{run.id}",
            })

        elif tool_name == "list_audits":
            limit = min(int(tool_input.get("limit", 10)), 20)
            result = await db.execute(
                select(AuditRun).order_by(desc(AuditRun.created_at)).limit(limit)
            )
            runs = result.scalars().all()
            if not runs:
                return json.dumps({"audits": [], "message": "No audits found."})

            audits = []
            for run in runs:
                issue_result = await db.execute(
                    select(Issue.severity, func.count(Issue.id))
                    .where(Issue.audit_run_id == run.id)
                    .group_by(Issue.severity)
                )
                issue_counts = {row[0]: row[1] for row in issue_result}

                vendor_result = await db.execute(
                    select(func.count(DetectedVendor.id))
                    .where(DetectedVendor.audit_run_id == run.id)
                    .where(DetectedVendor.page_visit_id == None)
                )
                vendor_count = vendor_result.scalar() or 0

                audits.append({
                    "id": str(run.id),
                    "url": run.base_url,
                    "status": run.status.value,
                    "mode": run.mode.value,
                    "pages_crawled": run.pages_crawled,
                    "created_at": run.created_at.isoformat() if run.created_at else None,
                    "vendors": vendor_count,
                    "issues": {
                        "critical": issue_counts.get("critical", 0),
                        "high": issue_counts.get("high", 0),
                        "medium": issue_counts.get("medium", 0),
                        "low": issue_counts.get("low", 0),
                    },
                })
            return json.dumps({"audits": audits})

        elif tool_name == "get_audit":
            audit_id = tool_input["audit_id"]
            result = await db.execute(select(AuditRun).where(AuditRun.id == audit_id))
            run = result.scalar_one_or_none()
            if not run:
                return json.dumps({"error": f"Audit {audit_id} not found."})

            issue_result = await db.execute(
                select(Issue.severity, func.count(Issue.id))
                .where(Issue.audit_run_id == run.id)
                .group_by(Issue.severity)
            )
            issue_counts = {row[0]: row[1] for row in issue_result}

            top_issues_result = await db.execute(
                select(Issue.title, Issue.severity)
                .where(Issue.audit_run_id == run.id)
                .order_by(desc(Issue.severity))
                .limit(10)
            )
            top_issues = [{"title": r[0], "severity": r[1]} for r in top_issues_result]

            vendors_result = await db.execute(
                select(DetectedVendor.vendor_name, DetectedVendor.category, DetectedVendor.page_count)
                .where(DetectedVendor.audit_run_id == run.id)
                .where(DetectedVendor.page_visit_id == None)
                .order_by(desc(DetectedVendor.page_count))
            )
            vendors = [{"name": r[0], "category": r[1], "pages": r[2]} for r in vendors_result]

            request_count_result = await db.execute(
                select(func.count(NetworkRequest.id))
                .where(NetworkRequest.audit_run_id == run.id)
            )
            request_count = request_count_result.scalar() or 0

            cookie_count = 0
            pages_result = await db.execute(
                select(PageVisit.cookies)
                .where(PageVisit.audit_run_id == run.id)
            )
            all_cookie_sets = pages_result.scalars().all()
            seen_cookies = set()
            for cookie_list in all_cookie_sets:
                if isinstance(cookie_list, list):
                    for c in cookie_list:
                        if isinstance(c, dict):
                            key = (c.get("name", ""), c.get("domain", ""))
                            seen_cookies.add(key)
            cookie_count = len(seen_cookies)

            return json.dumps({
                "id": str(run.id),
                "url": run.base_url,
                "status": run.status.value,
                "mode": run.mode.value,
                "pages_crawled": run.pages_crawled,
                "pages_discovered": run.pages_discovered,
                "pages_failed": run.pages_failed,
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "total_network_requests": request_count,
                "unique_cookies": cookie_count,
                "issue_counts": {
                    "critical": issue_counts.get("critical", 0),
                    "high": issue_counts.get("high", 0),
                    "medium": issue_counts.get("medium", 0),
                    "low": issue_counts.get("low", 0),
                },
                "top_issues": top_issues,
                "vendors": vendors,
            })

        elif tool_name == "get_issues":
            audit_id = tool_input["audit_id"]
            severity = tool_input.get("severity")

            query = select(Issue).where(Issue.audit_run_id == audit_id)
            if severity:
                query = query.where(Issue.severity == severity)
            severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            result = await db.execute(query)
            issues_raw = result.scalars().all()
            issues_raw = sorted(issues_raw, key=lambda i: severity_order.get(i.severity, 9))

            issues = []
            for issue in issues_raw[:50]:
                issues.append({
                    "id": str(issue.id),
                    "title": issue.title,
                    "severity": issue.severity,
                    "category": issue.category,
                    "description": (issue.description or "")[:300],
                    "recommendation": (issue.recommendation or "")[:200],
                    "affected_vendor_key": issue.affected_vendor_key,
                })
            return json.dumps({
                "audit_id": audit_id,
                "severity_filter": severity,
                "total_shown": len(issues),
                "issues": issues,
            })

        elif tool_name == "get_vendors":
            audit_id = tool_input["audit_id"]
            result = await db.execute(
                select(DetectedVendor)
                .where(DetectedVendor.audit_run_id == audit_id)
                .where(DetectedVendor.page_visit_id == None)
                .order_by(desc(DetectedVendor.page_count))
            )
            vendors_raw = result.scalars().all()

            vendors = []
            for v in vendors_raw:
                evidence_summary = []
                if isinstance(v.evidence, dict):
                    for k, vals in v.evidence.items():
                        if vals:
                            summary = f"{k}: {', '.join(str(x) for x in (vals[:2] if isinstance(vals, list) else [vals]))}"
                            evidence_summary.append(summary)
                vendors.append({
                    "vendor_key": v.vendor_key,
                    "vendor_name": v.vendor_name,
                    "category": v.category,
                    "page_count": v.page_count,
                    "detection_method": v.detection_method,
                    "evidence_summary": "; ".join(evidence_summary[:3]),
                })
            return json.dumps({"audit_id": audit_id, "vendors": vendors})

        elif tool_name == "get_pages":
            audit_id = tool_input["audit_id"]
            limit = min(int(tool_input.get("limit", 20)), 100)

            result = await db.execute(
                select(PageVisit)
                .where(PageVisit.audit_run_id == audit_id)
                .order_by(PageVisit.crawled_at)
                .limit(limit)
            )
            pages_raw = result.scalars().all()

            pages = []
            for page in pages_raw:
                vendor_count_result = await db.execute(
                    select(func.count(DetectedVendor.id))
                    .where(DetectedVendor.page_visit_id == page.id)
                )
                vendor_count = vendor_count_result.scalar() or 0

                issue_count_result = await db.execute(
                    select(func.count(Issue.id))
                    .where(Issue.page_visit_id == page.id)
                )
                issue_count = issue_count_result.scalar() or 0

                pages.append({
                    "url": page.url,
                    "status_code": page.status_code,
                    "load_time_ms": page.load_time_ms,
                    "vendor_count": vendor_count,
                    "issue_count": issue_count,
                })
            return json.dumps({"audit_id": audit_id, "pages": pages})

        elif tool_name == "navigate_to":
            path = tool_input.get("path", "/").strip()
            if not path.startswith("/"):
                path = "/" + path
            label = tool_input.get("label", path)
            return json.dumps({"success": True, "url": path, "label": label})

        elif tool_name == "schedule_audit":
            from urllib.parse import urlparse
            from datetime import timedelta
            from app.models.scheduled_audit import ScheduledAudit

            url = tool_input.get("url", "").strip()
            if url and not url.startswith(("http://", "https://")):
                url = "https://" + url
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return json.dumps({"error": "Invalid URL."})

            frequency = tool_input.get("frequency", "weekly")
            if frequency not in ("daily", "weekly", "monthly"):
                frequency = "weekly"
            mode = tool_input.get("mode", "quick_scan")
            if mode not in ("quick_scan", "full_crawl"):
                mode = "quick_scan"
            max_pages = 50 if mode == "quick_scan" else 200
            label = tool_input.get("label") or f"{frequency.capitalize()} audit of {url}"

            from datetime import datetime, timedelta
            if frequency == "daily":
                next_run = datetime.utcnow() + timedelta(days=1)
            elif frequency == "weekly":
                next_run = datetime.utcnow() + timedelta(weeks=1)
            else:
                next_run = datetime.utcnow() + timedelta(days=30)

            sched = ScheduledAudit(
                url=url,
                mode=mode,
                max_pages=max_pages,
                frequency=frequency,
                label=label,
                is_active=True,
                next_run_at=next_run,
            )
            db.add(sched)
            await db.commit()
            await db.refresh(sched)

            return json.dumps({
                "success": True,
                "schedule_id": str(sched.id),
                "url": url,
                "frequency": frequency,
                "mode": mode,
                "label": label,
                "next_run_at": sched.next_run_at.isoformat(),
            })

        elif tool_name == "list_schedules":
            from app.models.scheduled_audit import ScheduledAudit

            result = await db.execute(
                select(ScheduledAudit)
                .where(ScheduledAudit.is_active == True)
                .order_by(ScheduledAudit.next_run_at)
            )
            schedules = result.scalars().all()
            if not schedules:
                return json.dumps({"schedules": [], "message": "No active scheduled audits."})

            return json.dumps({
                "schedules": [
                    {
                        "id": str(s.id),
                        "url": s.url,
                        "frequency": s.frequency,
                        "mode": s.mode,
                        "label": s.label,
                        "next_run_at": s.next_run_at.isoformat(),
                        "created_at": s.created_at.isoformat(),
                    }
                    for s in schedules
                ]
            })

        elif tool_name == "cancel_schedule":
            from app.models.scheduled_audit import ScheduledAudit

            schedule_id = tool_input.get("schedule_id", "").strip()
            result = await db.execute(
                select(ScheduledAudit).where(ScheduledAudit.id == schedule_id)
            )
            sched = result.scalar_one_or_none()
            if not sched:
                return json.dumps({"error": f"Schedule {schedule_id} not found."})
            sched.is_active = False
            await db.commit()
            return json.dumps({
                "success": True,
                "schedule_id": schedule_id,
                "url": sched.url,
                "message": f"Schedule cancelled. No further audits will be run for {sched.url}.",
            })

        elif tool_name == "compare_audits":
            audit_id_a = tool_input.get("audit_id_a", "").strip()
            audit_id_b = tool_input.get("audit_id_b", "").strip()

            result_a = await db.execute(select(AuditRun).where(AuditRun.id == audit_id_a))
            result_b = await db.execute(select(AuditRun).where(AuditRun.id == audit_id_b))
            run_a = result_a.scalar_one_or_none()
            run_b = result_b.scalar_one_or_none()

            if not run_a:
                return json.dumps({"error": f"Audit {audit_id_a} not found."})
            if not run_b:
                return json.dumps({"error": f"Audit {audit_id_b} not found."})

            # Vendor comparison
            vend_a = await db.execute(
                select(DetectedVendor.vendor_key, DetectedVendor.vendor_name, DetectedVendor.category)
                .where(DetectedVendor.audit_run_id == audit_id_a)
                .where(DetectedVendor.page_visit_id == None)
            )
            vend_b = await db.execute(
                select(DetectedVendor.vendor_key, DetectedVendor.vendor_name, DetectedVendor.category)
                .where(DetectedVendor.audit_run_id == audit_id_b)
                .where(DetectedVendor.page_visit_id == None)
            )
            vendors_a = {r[0]: {"name": r[1], "category": r[2]} for r in vend_a}
            vendors_b = {r[0]: {"name": r[1], "category": r[2]} for r in vend_b}

            added_vendors   = [{"key": k, **v} for k, v in vendors_b.items() if k not in vendors_a]
            removed_vendors = [{"key": k, **v} for k, v in vendors_a.items() if k not in vendors_b]
            common_vendors  = [k for k in vendors_a if k in vendors_b]

            # Issue comparison (by title+category as dedup key)
            issues_a_result = await db.execute(
                select(Issue.title, Issue.severity, Issue.category)
                .where(Issue.audit_run_id == audit_id_a)
            )
            issues_b_result = await db.execute(
                select(Issue.title, Issue.severity, Issue.category)
                .where(Issue.audit_run_id == audit_id_b)
            )
            issues_a = {(r[0], r[2]): r[1] for r in issues_a_result}
            issues_b = {(r[0], r[2]): r[1] for r in issues_b_result}

            new_issues      = [{"title": k[0], "category": k[1], "severity": v} for k, v in issues_b.items() if k not in issues_a]
            resolved_issues = [{"title": k[0], "category": k[1], "severity": v} for k, v in issues_a.items() if k not in issues_b]

            return json.dumps({
                "audit_a": {"id": audit_id_a, "url": run_a.base_url, "status": run_a.status.value,
                            "pages_crawled": run_a.pages_crawled, "created_at": run_a.created_at.isoformat()},
                "audit_b": {"id": audit_id_b, "url": run_b.base_url, "status": run_b.status.value,
                            "pages_crawled": run_b.pages_crawled, "created_at": run_b.created_at.isoformat()},
                "vendors": {
                    "added": added_vendors,
                    "removed": removed_vendors,
                    "unchanged_count": len(common_vendors),
                },
                "issues": {
                    "new": new_issues,
                    "resolved": resolved_issues,
                    "unchanged_count": len([k for k in issues_a if k in issues_b]),
                },
            })

        elif tool_name == "read_report":
            from app.models import Artifact
            audit_id = tool_input["audit_id"]
            fmt = tool_input.get("format", "markdown")

            artifact_type = "report_md" if fmt == "markdown" else "report_json"
            art_result = await db.execute(
                select(Artifact)
                .where(Artifact.audit_run_id == audit_id)
                .where(Artifact.artifact_type == artifact_type)
                .order_by(Artifact.created_at.desc())
                .limit(1)
            )
            artifact = art_result.scalar_one_or_none()

            if not artifact:
                return json.dumps({"error": f"No {fmt} report found for audit {audit_id}. The audit may not be complete yet."})

            data_dir = os.environ.get("DATA_DIR", "/data")
            file_path = artifact.file_path
            if not os.path.isabs(file_path):
                file_path = os.path.join(data_dir, file_path)

            if not os.path.exists(file_path):
                return json.dumps({"error": f"Report file not found on disk: {file_path}"})

            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Cap at ~40k chars to stay within context limits
            if len(content) > 40000:
                content = content[:40000] + "\n\n[Report truncated — showing first 40,000 characters]"

            return json.dumps({"audit_id": audit_id, "format": fmt, "content": content})

        elif tool_name == "get_network_requests":
            from app.models import NetworkRequest, DetectedVendor, PageVisit
            from sqlalchemy import and_, or_
            import uuid as uuid_mod

            audit_id = tool_input["audit_id"]
            vendor_key = tool_input.get("vendor_key", "").strip()
            url_pattern = tool_input.get("url_pattern", "").strip()
            page_url_filter = tool_input.get("page_url", "").strip()
            tracking_only = tool_input.get("tracking_only", True)
            failed_only = tool_input.get("failed_only", False)
            limit = min(int(tool_input.get("limit", 40)), 100)

            try:
                uid = uuid_mod.UUID(audit_id)
            except ValueError:
                return json.dumps({"error": "Invalid audit_id"})

            stmt = (
                select(NetworkRequest, DetectedVendor.vendor_key, DetectedVendor.name, PageVisit.url)
                .outerjoin(DetectedVendor, NetworkRequest.vendor_id == DetectedVendor.id)
                .outerjoin(PageVisit, NetworkRequest.page_visit_id == PageVisit.id)
                .where(NetworkRequest.audit_run_id == uid)
            )

            if tracking_only:
                stmt = stmt.where(NetworkRequest.is_tracking_related == True)
            if failed_only:
                stmt = stmt.where(or_(NetworkRequest.failed == True, NetworkRequest.status_code >= 400))
            if vendor_key:
                stmt = stmt.where(DetectedVendor.vendor_key == vendor_key)
            if url_pattern:
                stmt = stmt.where(NetworkRequest.url.ilike(f"%{url_pattern}%"))
            if page_url_filter:
                stmt = stmt.where(PageVisit.url.ilike(f"%{page_url_filter}%"))

            stmt = stmt.order_by(NetworkRequest.captured_at.asc()).limit(limit)
            rows = (await db.execute(stmt)).all()

            requests = []
            for row in rows:
                nr, vkey, vname, purl = row
                post_snippet = None
                if nr.post_data:
                    post_snippet = nr.post_data[:800] + ("…" if len(nr.post_data) > 800 else "")
                requests.append({
                    "url": nr.url,
                    "method": nr.method,
                    "status_code": nr.status_code,
                    "failed": nr.failed,
                    "failure_reason": nr.failure_reason,
                    "vendor_key": vkey,
                    "vendor_name": vname,
                    "page_url": purl,
                    "post_data": post_snippet,
                    "timing_ms": nr.timing_ms,
                })

            return json.dumps({
                "audit_id": audit_id,
                "total_returned": len(requests),
                "filters": {
                    "vendor_key": vendor_key or None,
                    "url_pattern": url_pattern or None,
                    "page_url": page_url_filter or None,
                    "tracking_only": tracking_only,
                    "failed_only": failed_only,
                },
                "requests": requests,
            })

        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    except Exception as e:
        logger.warning(f"Tool {tool_name} error: {e}")
        return json.dumps({"error": str(e)})


@router.post("/chat")
async def help_chat(payload: HelpChatRequest, db: AsyncSession = Depends(get_db)):
    api_key = await _get_api_key(db)

    if not api_key:
        async def no_key_stream():
            msg = (
                "The AI help assistant requires an `ANTHROPIC_API_KEY` to be set in your environment. "
                "Add it to your `.env` file and restart the app.\n\n"
                "In the meantime, here are some quick links:\n"
                "- **New Audit** — top right button or nav\n"
                "- **Dashboard** — lists all audits with status and issue counts\n"
                "- **Audit detail** — click any audit row to see vendors, issues, pages, and reports"
            )
            yield f"data: {json.dumps({'text': msg})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(no_key_stream(), media_type="text/event-stream")

    try:
        import anthropic
    except ImportError:
        async def no_sdk_stream():
            yield f"data: {json.dumps({'text': 'The `anthropic` package is not installed in this environment.'})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(no_sdk_stream(), media_type="text/event-stream")

    audit_context = await _get_audit_context(db)

    system = SYSTEM_PROMPT
    if audit_context:
        system += f"\n\n---\n\n## USER'S AUDIT DATA (read-only, current)\n\n{audit_context}\n\nYou can answer questions about these specific audits — what was found, issue counts, vendors detected, comparisons between runs, etc. Do not suggest any actions that would modify or delete audits."
    if payload.page_context:
        system += f"\n\n---\n\n## CURRENT PAGE CONTEXT\n\n{payload.page_context}\n\nUse this to give context-aware answers about what the user is currently looking at."

    messages = []
    for msg in payload.history[-10:]:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": payload.message})

    async def stream_response():
        try:
            client = anthropic.Anthropic(api_key=api_key)
            with client.messages.stream(
                model="claude-haiku-4-5",
                max_tokens=1024,
                system=system,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    yield f"data: {json.dumps({'text': text})}\n\n"
        except Exception as e:
            logger.warning(f"Help chat error: {e}")
            yield f"data: {json.dumps({'text': f'Sorry, something went wrong: {str(e)}'})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(stream_response(), media_type="text/event-stream")



@router.post("/agent")
async def help_agent(payload: HelpChatRequest, db: AsyncSession = Depends(get_db)):
    api_key = await _get_api_key(db)

    if not api_key:
        async def no_key_stream():
            msg = (
                "The AI help assistant requires an `ANTHROPIC_API_KEY` to be set in your environment. "
                "Add it to your `.env` file and restart the app.\n\n"
                "In the meantime, here are some quick links:\n"
                "- **New Audit** — top right button or nav\n"
                "- **Dashboard** — lists all audits with status and issue counts\n"
                "- **Audit detail** — click any audit row to see vendors, issues, pages, and reports"
            )
            yield "data: " + json.dumps({"type": "text", "text": msg}) + "\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(no_key_stream(), media_type="text/event-stream")

    try:
        import anthropic
    except ImportError:
        async def no_sdk_stream():
            yield "data: " + json.dumps({"type": "text", "text": "The `anthropic` package is not installed in this environment."}) + "\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(no_sdk_stream(), media_type="text/event-stream")

    system = SYSTEM_PROMPT
    if payload.page_context:
        system += (
            "\n\n---\n\n## CURRENT PAGE CONTEXT\n\n"
            + payload.page_context
            + "\n\nUse this to give context-aware answers about what the user is currently looking at."
        )

    initial_messages = []
    for msg in payload.history[-10:]:
        initial_messages.append({"role": msg.role, "content": msg.content})
    initial_messages.append({"role": "user", "content": payload.message})

    async def agent_stream():
        try:
            client = anthropic.Anthropic(api_key=api_key)
            current_messages = list(initial_messages)
            tools_were_used = False

            for iteration in range(8):
                if iteration < 7:
                    response = client.messages.create(
                        model="claude-haiku-4-5",
                        max_tokens=1024,
                        system=system,
                        tools=AGENT_TOOLS,
                        messages=current_messages,
                    )

                    if response.stop_reason == "tool_use":
                        tools_were_used = True
                        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
                        tool_results = []

                        for tool_block in tool_use_blocks:
                            label = TOOL_LABELS.get(tool_block.name, "Working...")
                            yield "data: " + json.dumps({"type": "tool_use", "tool": tool_block.name, "label": label}) + "\n\n"
                            result_str = await _execute_tool(tool_block.name, tool_block.input, db)
                            # Emit navigation event so the frontend panel navigates
                            if tool_block.name == "navigate_to":
                                try:
                                    nav_data = json.loads(result_str)
                                    if not nav_data.get("error"):
                                        yield "data: " + json.dumps({"type": "navigate", "url": nav_data["url"]}) + "\n\n"
                                except Exception:
                                    pass
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_block.id,
                                "content": result_str,
                            })

                        current_messages = current_messages + [
                            {"role": "assistant", "content": response.content},
                            {"role": "user", "content": tool_results},
                        ]
                        continue

                    elif response.stop_reason == "end_turn" and not tools_were_used:
                        # No tools were used — redo as a streaming call for real-time UX
                        with client.messages.stream(
                            model="claude-haiku-4-5",
                            max_tokens=1024,
                            system=system,
                            tools=AGENT_TOOLS,
                            tool_choice={"type": "none"},
                            messages=current_messages,
                        ) as stream:
                            for text in stream.text_stream:
                                yield "data: " + json.dumps({"type": "text", "text": text}) + "\n\n"
                        break

                    else:
                        # end_turn after tool use — emit text chunks and finish
                        text_blocks = [b for b in response.content if b.type == "text"]
                        full_text = "".join(b.text for b in text_blocks)
                        if full_text:
                            chunk_size = 4
                            for i in range(0, len(full_text), chunk_size):
                                yield "data: " + json.dumps({"type": "text", "text": full_text[i:i+chunk_size]}) + "\n\n"
                        break

                else:
                    # Last iteration — stream with tools disabled
                    with client.messages.stream(
                        model="claude-haiku-4-5",
                        max_tokens=1024,
                        system=system,
                        tools=AGENT_TOOLS,
                        tool_choice={"type": "none"},
                        messages=current_messages,
                    ) as stream:
                        for text in stream.text_stream:
                            yield "data: " + json.dumps({"type": "text", "text": text}) + "\n\n"
                    break

        except Exception as e:
            logger.warning("Help agent error: %s", e)
            yield "data: " + json.dumps({"type": "text", "text": "Sorry, something went wrong: " + str(e)}) + "\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(agent_stream(), media_type="text/event-stream")
