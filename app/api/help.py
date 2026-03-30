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

Answer the user's question based on the above. If they ask something not covered here, say so honestly. Do not make up features that don't exist."""


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
            # Issue counts
            issue_result = await db.execute(
                select(Issue.severity, func.count(Issue.id))
                .where(Issue.audit_run_id == run.id)
                .group_by(Issue.severity)
            )
            counts = {row[0]: row[1] for row in issue_result}

            # Vendor count
            vendor_result = await db.execute(
                select(func.count(DetectedVendor.id))
                .where(DetectedVendor.audit_run_id == run.id)
                .where(DetectedVendor.page_visit_id == None)
            )
            vendor_count = vendor_result.scalar() or 0

            # Top issues
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


@router.post("/chat")
async def help_chat(payload: HelpChatRequest, db: AsyncSession = Depends(get_db)):
    api_key = await _get_api_key(db)

    if not api_key:
        # Return a helpful static response if no API key
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

    # Fetch live audit context
    audit_context = await _get_audit_context(db)

    system = SYSTEM_PROMPT
    if audit_context:
        system += f"\n\n---\n\n## USER'S AUDIT DATA (read-only, current)\n\n{audit_context}\n\nYou can answer questions about these specific audits — what was found, issue counts, vendors detected, comparisons between runs, etc. Do not suggest any actions that would modify or delete audits."
    if payload.page_context:
        system += f"\n\n---\n\n## CURRENT PAGE CONTEXT\n\n{payload.page_context}\n\nUse this to give context-aware answers about what the user is currently looking at."

    # Build messages list from history + new message
    messages = []
    for msg in payload.history[-10:]:  # cap context at last 10 turns
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
