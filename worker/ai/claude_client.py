"""
AI enrichment layer using Claude Haiku.

All functions degrade gracefully: if ANTHROPIC_API_KEY is not set or any API
call fails, the function logs a warning and returns None / empty results so
the rest of the audit pipeline continues unaffected.
"""
import json
import logging
import os
from typing import Optional

logger = logging.getLogger("odit.worker.ai")

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 1024


def _get_client():
    """Return an Anthropic client, or None if no API key is configured."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        logger.warning("anthropic package not installed — AI features disabled")
        return None


def _call(client, prompt: str, system: str = "") -> Optional[str]:
    """Make a single Haiku call. Returns text or None on failure."""
    try:
        kwargs = {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        response = client.messages.create(**kwargs)
        for block in response.content:
            if block.type == "text":
                return block.text.strip()
        return None
    except Exception as e:
        logger.warning(f"Claude API call failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# Feature 1: Issue enrichment
# ─────────────────────────────────────────────────────────────────

ISSUE_SYSTEM = (
    "You are an expert in web analytics, tag management, and martech implementations. "
    "You help auditors understand and fix tracking issues on websites. "
    "Be concise, practical, and specific. Avoid generic advice."
)


def enrich_issue(issue_data: dict) -> Optional[dict]:
    """
    Given a dict with issue fields, return an enriched dict with
    {description, likely_cause, recommendation} or None on failure.

    issue_data keys: category, title, severity, affected_url,
                     affected_vendor_key, evidence_refs, description,
                     likely_cause, recommendation
    """
    client = _get_client()
    if not client:
        return None

    evidence_str = json.dumps(issue_data.get("evidence_refs", []), indent=2)[:800]
    prompt = f"""You are reviewing a tracking audit issue. Enrich it with better explanations.

Issue title: {issue_data.get('title', '')}
Category: {issue_data.get('category', '')}
Severity: {issue_data.get('severity', '')}
Affected URL: {issue_data.get('affected_url', 'N/A')}
Affected vendor: {issue_data.get('affected_vendor_key', 'N/A')}
Current description: {issue_data.get('description', '')}
Evidence (truncated): {evidence_str}

Respond with ONLY a JSON object with these three keys:
- "description": A clear 2-3 sentence explanation of what is wrong and why it matters.
- "likely_cause": A specific 1-2 sentence diagnosis of the probable root cause.
- "recommendation": A concrete, actionable fix (1-3 sentences) that a developer can act on.

Respond only with the JSON object, no markdown, no extra text."""

    result = _call(client, prompt, system=ISSUE_SYSTEM)
    if not result:
        return None

    try:
        # Strip any accidental markdown fencing
        cleaned = result.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to parse AI issue enrichment response: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# Feature 2: Unknown vendor / domain inference
# ─────────────────────────────────────────────────────────────────

VENDOR_SYSTEM = (
    "You are an expert in web tracking, advertising technology, and third-party scripts. "
    "You identify services and vendors from their domain names."
)


def infer_unknown_domains(domains: list[str]) -> dict[str, dict]:
    """
    Given a list of unrecognised third-party domains, return a dict mapping
    domain → {name, category, description} for any that look like tracking/martech.

    category is one of: analytics, tag_manager, ab_testing, consent, pixel,
                        cdn, error_monitoring, session_replay, other_tracking, skip
    Returns {} on failure or if no API key.
    """
    client = _get_client()
    if not client or not domains:
        return {}

    domains_str = "\n".join(f"- {d}" for d in domains[:40])
    prompt = f"""You are reviewing third-party network requests from a website audit.

For each domain below, identify if it is a tracking, analytics, advertising, or martech service.
Only include domains that are clearly tracking/martech related. Skip CDNs, fonts, and generic infrastructure.

Domains:
{domains_str}

Respond with ONLY a JSON object mapping domain → object with keys:
- "name": human-readable service name (e.g. "Hotjar")
- "category": one of analytics|tag_manager|ab_testing|consent|pixel|session_replay|error_monitoring|other_tracking
- "description": one sentence describing what this service does

Example:
{{"cdn.hotjar.com": {{"name": "Hotjar", "category": "session_replay", "description": "Session recording and heatmap analytics service."}}}}

Only include domains you are confident about. Omit unknown or infrastructure domains.
Respond only with the JSON object, no extra text."""

    result = _call(client, prompt, system=VENDOR_SYSTEM)
    if not result:
        return {}

    try:
        cleaned = result.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to parse AI vendor inference response: {e}")
        return {}


# ─────────────────────────────────────────────────────────────────
# Feature 3: AI audit narrative summary
# ─────────────────────────────────────────────────────────────────

SUMMARY_SYSTEM = (
    "You are a senior analytics implementation consultant writing an executive summary "
    "of a website tracking audit for a client. Write clearly, concisely, and professionally. "
    "Focus on what matters to the business and what needs to be fixed first."
)


def generate_narrative_summary(audit_data: dict) -> Optional[str]:
    """
    Given a dict of audit stats, return a 3-5 paragraph natural language
    executive summary or None on failure.

    audit_data keys: base_url, mode, pages_crawled, vendors (list of names),
                     issue_counts (dict by severity), top_issues (list of titles),
                     broken_domains (list)
    """
    client = _get_client()
    if not client:
        return None

    top_issues_str = "\n".join(f"- {i}" for i in audit_data.get("top_issues", [])[:8])
    vendors_str = ", ".join(audit_data.get("vendors", [])[:15]) or "None detected"
    broken_str = ", ".join(audit_data.get("broken_domains", [])[:8]) or "None"
    counts = audit_data.get("issue_counts", {})

    prompt = f"""Write an executive summary for this website tracking audit.

Site: {audit_data.get('base_url', '')}
Audit mode: {audit_data.get('mode', '')}
Pages crawled: {audit_data.get('pages_crawled', 0)}
Vendors detected: {vendors_str}
Issues found: {counts.get('critical', 0)} critical, {counts.get('high', 0)} high, {counts.get('medium', 0)} medium, {counts.get('low', 0)} low
Top issues:
{top_issues_str}
Broken/failing domains: {broken_str}

Write 3-5 paragraphs covering:
1. Overall health of the tracking implementation
2. Key vendors present and any notable gaps
3. Most important issues and their business impact
4. Prioritised recommendations

Keep it professional and actionable. No bullet points — prose only."""

    return _call(client, prompt, system=SUMMARY_SYSTEM)


# ─────────────────────────────────────────────────────────────────
# Feature 4: Journey audit — NL instruction → Playwright selectors
# ─────────────────────────────────────────────────────────────────

SELECTOR_SYSTEM = (
    "You are an expert in Playwright browser automation and HTML/CSS selectors. "
    "You convert natural language instructions into safe, precise Playwright actions. "
    "You only generate observation/navigation actions — never form submissions, "
    "login attempts, or destructive actions."
)


def nl_to_playwright_actions(instruction: str, page_html_snippet: str = "") -> Optional[list[dict]]:
    """
    Convert a natural language journey instruction to a list of Playwright action dicts.

    Returns a list like:
      [{"action": "click", "selector": "text=Add to cart"},
       {"action": "wait_for_selector", "selector": ".cart-count"}]

    or None on failure.

    Supported actions: click, fill, wait_for_selector, wait_for_timeout, goto, scroll
    """
    client = _get_client()
    if not client:
        return None

    html_context = ""
    if page_html_snippet:
        html_context = f"\nPage HTML snippet (truncated):\n{page_html_snippet[:1500]}\n"

    prompt = f"""Convert this user journey instruction into Playwright actions for a tracking audit.

Instruction: "{instruction}"{html_context}

Rules:
- Only safe, read-only navigation actions (click links/buttons, scroll, wait)
- Do NOT generate: form logins, password fields, payment actions, destructive operations
- Use robust selectors: prefer text=, role=, data-testid= over brittle CSS paths
- Keep it minimal — only what's needed to complete the navigation step

Respond with ONLY a JSON array of action objects. Each object must have:
- "action": one of click|fill|wait_for_selector|wait_for_timeout|goto|scroll
- "selector": CSS/text selector (for click, fill, wait_for_selector)
- "value": value to fill (for fill action only)
- "url": URL to navigate to (for goto action only)
- "timeout": ms to wait (for wait_for_timeout only)
- "description": one short sentence explaining this step

Example:
[
  {{"action": "click", "selector": "text=Products", "description": "Navigate to the products page"}},
  {{"action": "wait_for_selector", "selector": ".product-grid", "description": "Wait for product grid to load"}}
]

Respond only with the JSON array, no extra text."""

    result = _call(client, prompt, system=SELECTOR_SYSTEM)
    if not result:
        return None

    try:
        cleaned = result.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        actions = json.loads(cleaned)
        if isinstance(actions, list):
            return actions
        return None
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to parse AI selector response: {e}")
        return None
