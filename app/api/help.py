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

SYSTEM_PROMPT = """You are the built-in help assistant for **Odit** — a local-first website tracking auditor.

Odit crawls websites using a real browser (Playwright), intercepts all network traffic via mitmproxy, detects analytics/martech vendors, flags compliance and implementation issues, and generates detailed reports. It runs entirely on the user's machine via Docker Compose.

Answer questions clearly and concisely. Use markdown formatting — bullet points, bold text, short code blocks where helpful. Keep answers focused and practical.

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
]

TOOL_LABELS = {
    "list_audits": "Looking up your audits...",
    "get_audit": "Loading audit details...",
    "get_issues": "Fetching issues...",
    "get_vendors": "Fetching vendor list...",
    "get_pages": "Loading pages...",
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
        from app.models import AuditRun, Issue, DetectedVendor, PageVisit, NetworkRequest

        if tool_name == "list_audits":
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
