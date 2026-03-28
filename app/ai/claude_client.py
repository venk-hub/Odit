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
MAX_TOKENS_SUMMARY = 3000  # structured 5-section brief needs more room

# Haiku pricing (per 1M tokens)
_PRICE_INPUT_PER_M = 1.00
_PRICE_OUTPUT_PER_M = 5.00

# Session-level token accumulator — reset before each audit enrichment run
_session_tokens: dict = {"input": 0, "output": 0, "calls": 0}


def reset_session_tokens() -> None:
    """Reset the session token counter. Call before each enrichment run."""
    _session_tokens["input"] = 0
    _session_tokens["output"] = 0
    _session_tokens["calls"] = 0


def get_session_tokens() -> dict:
    """Return current session token totals and estimated cost."""
    inp = _session_tokens["input"]
    out = _session_tokens["output"]
    cost = (inp * _PRICE_INPUT_PER_M + out * _PRICE_OUTPUT_PER_M) / 1_000_000
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "total_tokens": inp + out,
        "calls": _session_tokens["calls"],
        "estimated_cost_usd": round(cost, 6),
    }


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


def _call(client, prompt: str, system: str = "", label: str = "call",
          max_tokens: int = MAX_TOKENS) -> Optional[str]:
    """Make a single Haiku call. Returns text or None on failure."""
    try:
        kwargs = {
            "model": MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        response = client.messages.create(**kwargs)

        # Log and accumulate token usage
        usage = response.usage
        inp, out = usage.input_tokens, usage.output_tokens
        _session_tokens["input"] += inp
        _session_tokens["output"] += out
        _session_tokens["calls"] += 1
        call_cost = (inp * _PRICE_INPUT_PER_M + out * _PRICE_OUTPUT_PER_M) / 1_000_000
        logger.info(f"[AI tokens] {label}: {inp} in + {out} out = {inp + out} tokens (~${call_cost:.5f})")

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

    result = _call(client, prompt, system=ISSUE_SYSTEM, label="enrich_issue")
    if not result:
        return None

    try:
        # Strip any accidental markdown fencing
        cleaned = result.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to parse AI issue enrichment response: {e}")
        return None


def batch_enrich_issues(issues_data: list, chunk_size: int = 20) -> list:
    """
    Batch-enrich a list of issue dicts in chunks.
    Returns a list of enriched dicts (same order as input), each with keys:
      description, likely_cause, recommendation, remediation_steps (list of str)
    Falls back to empty dicts on failure.
    """
    client = _get_client()
    if not client or not issues_data:
        return [{} for _ in issues_data]

    results = [{} for _ in issues_data]

    for chunk_start in range(0, len(issues_data), chunk_size):
        chunk = issues_data[chunk_start:chunk_start + chunk_size]
        issues_json = json.dumps([
            {
                "index": i,
                "title": iss.get("title", ""),
                "category": iss.get("category", ""),
                "severity": iss.get("severity", ""),
                "affected_vendor_key": iss.get("affected_vendor_key") or "",
                "description": iss.get("description") or "",
            }
            for i, iss in enumerate(chunk)
        ], indent=2)

        prompt = f"""You are a web analytics and privacy compliance expert. Enrich these {len(chunk)} tracking audit issues.

Issues:
{issues_json}

For EACH issue return exactly:
- description: 2-3 sentences explaining what is wrong and why it matters (mention GDPR/CCPA where relevant)
- likely_cause: 1-2 sentence specific root cause diagnosis
- recommendation: 1-3 sentence concrete fix a developer can act on
- remediation_steps: array of 2-4 short imperative step strings

Respond ONLY with a JSON array in input order. Each element: {{index, description, likely_cause, recommendation, remediation_steps}}.
No markdown, no extra text."""

        raw = _call(
            client, prompt, system=ISSUE_SYSTEM,
            label=f"batch_enrich[{chunk_start}:{chunk_start + len(chunk)}]",
            max_tokens=min(4000, len(chunk) * 250),
        )
        if not raw:
            continue
        try:
            cleaned = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            enriched = json.loads(cleaned)
            for item in enriched:
                idx = item.get("index")
                if idx is not None and 0 <= idx < len(chunk):
                    results[chunk_start + idx] = item
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse batch enrichment response (chunk {chunk_start}): {e}")

    return results


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

    result = _call(client, prompt, system=VENDOR_SYSTEM, label="infer_unknown_domains")
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
    "You are a senior analytics implementation consultant auditing a website's tracking setup. "
    "Your output is a structured audit brief — not a narrative essay. "
    "Use short, punchy bullet points. Be specific: name actual domains, variable names, cookie names, and vendor names. "
    "Never pad with filler phrases like 'overall the implementation is healthy'. "
    "If something is wrong or unknown, say so directly. Auditors will act on this."
)


def generate_narrative_summary(audit_data: dict) -> Optional[str]:
    """
    Given a dict of audit stats and evidence, return a 3-5 paragraph natural
    language executive summary or None on failure.
    """
    client = _get_client()
    if not client:
        return None

    vendors_list = audit_data.get("vendors", [])
    vendor_evidence = audit_data.get("vendor_evidence", [])
    top_issues_list = audit_data.get("top_issues", [])
    counts = audit_data.get("issue_counts", {})
    pages_crawled = audit_data.get("pages_crawled", 0)
    top_domains = audit_data.get("top_request_domains", [])   # list of (domain, count)
    total_requests = audit_data.get("total_requests", 0)
    sample_beacons = audit_data.get("sample_beacons", [])
    data_layers = audit_data.get("data_layers", {})
    cookie_names = audit_data.get("cookie_names", [])

    # ── Format each evidence block ──────────────────────────────────

    vendors_str = ", ".join(vendors_list[:15]) or "None detected"

    # Vendor evidence detail
    vendor_detail_lines = []
    for v in vendor_evidence[:12]:
        signals = []
        if v.get("domains"):   signals.append("domains: " + ", ".join(v["domains"]))
        if v.get("scripts"):   signals.append("scripts: " + ", ".join(v["scripts"]))
        if v.get("globals"):   signals.append("globals: " + ", ".join(v["globals"]))
        if v.get("cookies"):   signals.append("cookies: " + ", ".join(v["cookies"]))
        sig_str = "; ".join(signals) or "no signal detail"
        vendor_detail_lines.append(
            f"  {v['name']} [{v['category']}] — found on {v.get('pages',0)} page(s) via {v.get('method','?')}: {sig_str}"
        )
    vendor_detail_str = "\n".join(vendor_detail_lines) or "  (none)"

    # Network requests
    domain_lines = "\n".join(f"  {d}: {c} requests" for d, c in top_domains[:15]) or "  (none)"

    # Beacon payloads
    beacon_lines = []
    for b in sample_beacons[:5]:
        beacon_lines.append(f"  POST {b['url']}\n    payload: {b['body'][:200]}")
    beacon_str = "\n".join(beacon_lines) or "  (none)"

    # Data layers
    if data_layers:
        dl_lines = []
        for name, keys in data_layers.items():
            dl_lines.append(f"  {name}: {', '.join(keys[:20])}")
        dl_str = "\n".join(dl_lines)
    else:
        dl_str = "  (none found)"

    # Cookies
    cookie_str = ", ".join(cookie_names[:30]) or "None detected"

    # Issues
    top_issues_str = "\n".join(f"- {i}" for i in top_issues_list[:8]) or "  None detected"
    broken_str = ", ".join(audit_data.get("broken_domains", [])[:8]) or "None"

    # Guard: zero vendors is a critical finding
    no_tracking_note = ""
    if not vendors_list and pages_crawled > 0:
        no_tracking_note = (
            "\n\nCRITICAL CONTEXT: Zero tracking vendors were detected across all crawled pages. "
            "This is a critical finding. Do NOT write a positive or neutral health assessment. "
            "The summary MUST clearly state that no tracking technology was found and explain "
            "the business impact. Avoid any language suggesting the site is healthy or clean."
        )

    prompt = f"""Produce a structured audit brief for this website tracking audit. Use ONLY the evidence provided — no assumptions.

=== AUDIT METADATA ===
Site: {audit_data.get('base_url', '')}
Mode: {audit_data.get('mode', '')}
Pages crawled: {pages_crawled}
Total network requests captured: {total_requests}

=== VENDORS DETECTED ===
{vendors_str}

Vendor detection evidence:
{vendor_detail_str}

=== ISSUES FOUND ===
{counts.get('critical', 0)} critical, {counts.get('high', 0)} high, {counts.get('medium', 0)} medium, {counts.get('low', 0)} low
Top issues:
{top_issues_str}
Broken/failing domains: {broken_str}

=== NETWORK EVIDENCE ===
Top third-party request domains:
{domain_lines}

Sample tracking beacon payloads (POST requests):
{beacon_str}

=== DATA LAYER EVIDENCE ===
{dl_str}

=== COOKIE EVIDENCE ===
Cookies set: {cookie_str}{no_tracking_note}

Output the following sections using EXACTLY these headings. Use bullet points throughout. Be specific — use actual names from the evidence above.

## TRACKING INVENTORY
What tools are installed on this site and how they were confirmed. One bullet per tool. Format: "• [Vendor] — [how detected: domain/global/cookie/script] — [pages: N]"

## DATA FLOWS
Where data is being sent. One bullet per notable third-party domain. Format: "• [domain] → [vendor/purpose] — [N requests, N POSTs]"
If POST payloads were captured, note what's in them (e.g. page URL, user ID, event name).

## DATA LAYER
What variables are being pushed into dataLayer / utag_data / digitalData / _satellite. List the key variable names. Flag any that look like personal data (email, user ID, name, etc.) with ⚠.
If nothing was found, say so.

## ISSUES
Only real problems — not observations. One bullet per issue. Format: "• [SEVERITY] [title] — [what is actually wrong and where]"
If no issues, say "No issues detected."

## PRIORITY ACTIONS
3–5 specific next steps, ordered by impact. Each must reference a specific finding from above.

Keep each section tight. No filler. No prose paragraphs."""

    return _call(client, prompt, system=SUMMARY_SYSTEM, label="generate_narrative_summary",
                 max_tokens=MAX_TOKENS_SUMMARY)


# ─────────────────────────────────────────────────────────────────
# Feature 4: Comparison diff narration
# ─────────────────────────────────────────────────────────────────

COMPARISON_SYSTEM = (
    "You are a senior analytics consultant who specialises in tracking regression analysis. "
    "You write clear, concise summaries of changes between two website tracking audits. "
    "Be specific about business impact and what needs urgent attention."
)


def explain_audit_comparison(comparison_data: dict) -> Optional[str]:
    """
    Given a dict of comparison stats, return a short prose summary of what changed
    between two audits and what it means.

    comparison_data keys: base_url, new_issues (list of {title, severity}),
                          resolved_issues (list of {title, severity}),
                          vendor_changes ({added, removed, unchanged}),
                          page_count_change (int)
    """
    client = _get_client()
    if not client:
        return None

    new_issues = comparison_data.get("new_issues", [])
    resolved = comparison_data.get("resolved_issues", [])
    vc = comparison_data.get("vendor_changes", {})
    page_delta = comparison_data.get("page_count_change", 0)
    base_url = comparison_data.get("base_url", "")

    new_str = "\n".join(f"  [{i['severity']}] {i['title']}" for i in new_issues[:10]) or "  None"
    resolved_str = "\n".join(f"  [{i['severity']}] {i['title']}" for i in resolved[:10]) or "  None"
    added_str = ", ".join(vc.get("added", [])) or "none"
    removed_str = ", ".join(vc.get("removed", [])) or "none"

    prompt = f"""Write a brief regression analysis summary comparing two tracking audits for {base_url}.

New issues introduced:
{new_str}

Issues resolved:
{resolved_str}

Vendors added: {added_str}
Vendors removed: {removed_str}
Page count change: {page_delta:+d}

Write 2-3 short paragraphs covering:
1. Overall direction of change (better, worse, or mixed)
2. Most notable new risks or improvements
3. One key action to take next

Keep it under 150 words. No bullet points — prose only."""

    return _call(client, prompt, system=COMPARISON_SYSTEM, label="explain_audit_comparison")


# ─────────────────────────────────────────────────────────────────
# Feature 5: Suggest expected vendors from URL
# ─────────────────────────────────────────────────────────────────

SUGGESTION_SYSTEM = (
    "You are an expert in web analytics and martech stacks. "
    "You predict which tracking and analytics vendors a website is likely to use based on the domain."
)

KNOWN_VENDOR_KEYS = [
    "google_analytics", "google_tag_manager", "adobe_launch", "adobe_analytics",
    "tealium", "segment", "rudderstack", "mixpanel", "amplitude", "heap",
    "meta_pixel", "linkedin_insight", "tiktok_pixel", "optimizely", "vwo",
    "adobe_target", "launchdarkly", "dynamic_yield", "onetrust", "cookiebot", "trustarc",
]


def suggest_vendors_for_url(url: str) -> list:
    """
    Given a website URL, return a list of vendor keys (from KNOWN_VENDOR_KEYS)
    that are likely deployed on that site.

    Returns [] on failure or if no API key.
    """
    client = _get_client()
    if not client:
        return []

    keys_str = ", ".join(KNOWN_VENDOR_KEYS)
    prompt = f"""Based on the website URL below, which tracking/analytics vendors is this site most likely to use?

URL: {url}

Choose only from this list of vendor keys:
{keys_str}

Consider the industry, company type, and typical martech stacks.
Return ONLY a JSON array of vendor key strings from the list above.
Include 3-8 vendors you are fairly confident about.

Example: ["google_analytics", "google_tag_manager", "meta_pixel"]

Respond only with the JSON array, no extra text."""

    result = _call(client, prompt, system=SUGGESTION_SYSTEM, label="suggest_vendors_for_url")
    if not result:
        return []

    try:
        cleaned = result.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        candidates = json.loads(cleaned)
        if isinstance(candidates, list):
            return [v for v in candidates if v in KNOWN_VENDOR_KEYS]
        return []
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to parse AI vendor suggestion response: {e}")
        return []


# ─────────────────────────────────────────────────────────────────
# Feature 6: Remediation steps with code snippets
# ─────────────────────────────────────────────────────────────────

REMEDIATION_SYSTEM = (
    "You are a senior web analytics and tag management engineer. "
    "You write actionable, developer-friendly remediation guides with concrete code examples. "
    "Be specific. Use actual code snippets, not pseudocode."
)


def generate_remediation_steps(issue_data: dict) -> Optional[str]:
    """
    Given an issue dict, return a structured JSON string with remediation steps
    including code snippets.

    Returns a JSON string like:
    {
      "summary": "...",
      "steps": [
        {"title": "Step 1: ...", "detail": "...", "code": "...", "language": "javascript"},
        ...
      ]
    }
    or None on failure.
    """
    client = _get_client()
    if not client:
        return None

    prompt = f"""Write detailed remediation steps for this tracking audit issue.

Issue title: {issue_data.get('title', '')}
Category: {issue_data.get('category', '')}
Severity: {issue_data.get('severity', '')}
Affected vendor: {issue_data.get('affected_vendor_key', 'N/A')}
Description: {issue_data.get('description', '')}
Recommendation: {issue_data.get('recommendation', '')}

Respond with ONLY a JSON object with this structure:
{{
  "summary": "One sentence overview of the fix",
  "steps": [
    {{
      "title": "Short step title",
      "detail": "Explanation of what to do and why",
      "code": "Actual code snippet or empty string if not applicable",
      "language": "javascript|html|python|gtm|css or empty string"
    }}
  ]
}}

Include 2-4 steps. Include real code snippets where relevant (GTM custom HTML, JavaScript, etc.).
Respond only with the JSON object, no extra text."""

    result = _call(client, prompt, system=REMEDIATION_SYSTEM, label="generate_remediation_steps")
    if not result:
        return None

    try:
        cleaned = result.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        # Validate it parses
        json.loads(cleaned)
        return cleaned
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to parse AI remediation response: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# Feature 7: Journey audit — NL instruction → Playwright selectors
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

    result = _call(client, prompt, system=SELECTOR_SYSTEM, label="nl_to_playwright_actions")
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
