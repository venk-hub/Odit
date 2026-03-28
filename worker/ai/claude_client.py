# Re-export everything from the shared app-level AI client.
# The worker container has the full codebase; the app container only has app/.
# Keeping the authoritative implementation in app/ai/ makes it accessible to both.
from app.ai.claude_client import (  # noqa: F401
    reset_session_tokens,
    get_session_tokens,
    enrich_issue,
    batch_enrich_issues,
    infer_unknown_domains,
    generate_narrative_summary,
    explain_audit_comparison,
    suggest_vendors_for_url,
    generate_remediation_steps,
    nl_to_playwright_actions,
)
