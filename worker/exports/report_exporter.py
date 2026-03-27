"""
Report exporter: generates Markdown, HTML, and JSON summary reports.
"""
import os
import json
import logging
from datetime import datetime
from typing import List
from sqlalchemy.orm import Session

from worker.exports.report_helpers import (
    build_cookie_register,
    build_tag_attribution,
    build_performance_stats,
    compute_executive_metrics,
)

logger = logging.getLogger("odit.worker.report_exporter")

SEV_ICON  = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}
SEV_COLOR = {"critical": "#dc2626", "high": "#ea580c", "medium": "#ca8a04", "low": "#2563eb"}
SEV_BG    = {"critical": "#fef2f2", "high": "#fff7ed", "medium": "#fefce8", "low": "#eff6ff"}

CAT_BADGE_STYLE = {
    "analytics":  "background:#ede9fe;color:#5b21b6",
    "marketing":  "background:#fee2e2;color:#991b1b",
    "consent":    "background:#d1fae5;color:#065f46",
    "functional": "background:#dbeafe;color:#1e40af",
    "security":   "background:#fef3c7;color:#92400e",
    "unknown":    "background:#f3f4f6;color:#374151",
}


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _load_all(db, audit_run):
    """Load all DB objects needed by all report formats."""
    from app.models import PageVisit, DetectedVendor, Issue, AuditConfig, NetworkRequest

    audit_id = audit_run.id
    config = db.query(AuditConfig).filter(AuditConfig.id == audit_run.config_id).first()
    pages = db.query(PageVisit).filter(PageVisit.audit_run_id == audit_id).all()
    vendors = (
        db.query(DetectedVendor)
        .filter(DetectedVendor.audit_run_id == audit_id, DetectedVendor.page_visit_id == None)
        .all()
    )
    page_vendors = (
        db.query(DetectedVendor)
        .filter(DetectedVendor.audit_run_id == audit_id, DetectedVendor.page_visit_id != None)
        .all()
    )
    issues = db.query(Issue).filter(Issue.audit_run_id == audit_id).all()
    requests = db.query(NetworkRequest).filter(NetworkRequest.audit_run_id == audit_id).all()

    issues_sorted = sorted(
        issues,
        key=lambda i: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(i.severity, 99)
    )

    exec_metrics = compute_executive_metrics(vendors, issues, config, pages)
    cookie_reg   = build_cookie_register(pages)
    attributions = build_tag_attribution(vendors, pages, requests)
    perf_stats   = build_performance_stats(vendors, requests, page_vendors)

    return dict(
        config=config, pages=pages, vendors=vendors, issues=issues,
        issues_sorted=issues_sorted, requests=requests,
        exec_metrics=exec_metrics, cookie_reg=cookie_reg,
        attributions=attributions, perf_stats=perf_stats,
    )


# ─────────────────────────────────────────────────────────────────────────────
# JSON Summary
# ─────────────────────────────────────────────────────────────────────────────

def generate_json_summary(db: Session, audit_run, output_path: str) -> str:
    d = _load_all(db, audit_run)
    config, vendors, issues, exec_metrics = d["config"], d["vendors"], d["issues"], d["exec_metrics"]

    issue_counts = exec_metrics["issue_counts"]

    data = {
        "audit": {
            "id": str(audit_run.id),
            "base_url": audit_run.base_url,
            "mode": audit_run.mode if isinstance(audit_run.mode, str) else audit_run.mode.value,
            "status": audit_run.status if isinstance(audit_run.status, str) else audit_run.status.value,
            "created_at": str(audit_run.created_at),
            "started_at": str(audit_run.started_at) if audit_run.started_at else None,
            "completed_at": str(audit_run.completed_at) if audit_run.completed_at else None,
            "pages_discovered": audit_run.pages_discovered,
            "pages_crawled": audit_run.pages_crawled,
            "pages_failed": audit_run.pages_failed,
        },
        "config": {
            "max_pages": config.max_pages if config else None,
            "max_depth": config.max_depth if config else None,
            "device_type": config.device_type if config else None,
            "consent_behavior": config.consent_behavior if config else None,
        } if config else {},
        "executive": {
            "risk_rating": exec_metrics["risk_rating"],
            "risk_score": exec_metrics["risk_score"],
            "gdpr_posture": exec_metrics["gdpr_posture"],
            "ccpa_posture": exec_metrics["ccpa_posture"],
        },
        "issue_counts": issue_counts,
        "total_issues": sum(issue_counts.values()),
        "vendors": [
            {
                "key": v.vendor_key,
                "name": v.vendor_name,
                "category": v.category,
                "detection_method": v.detection_method,
                "load_source": d["attributions"].get(v.vendor_key, "Unknown"),
                "page_count": v.page_count,
            }
            for v in vendors
        ],
        "issues": [
            {
                "id": str(i.id),
                "severity": i.severity,
                "category": i.category,
                "title": i.title,
                "description": i.description,
                "affected_url": i.affected_url,
                "affected_vendor_key": i.affected_vendor_key,
                "likely_cause": i.likely_cause,
                "recommendation": i.recommendation,
                "remediation_steps": i.remediation_steps,
                "evidence_refs": i.evidence_refs,
            }
            for i in d["issues_sorted"]
        ],
        "cookie_register": d["cookie_reg"],
        "generated_at": datetime.utcnow().isoformat(),
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

    logger.info(f"JSON summary saved: {output_path}")
    return output_path


# ─────────────────────────────────────────────────────────────────────────────
# Markdown Report
# ─────────────────────────────────────────────────────────────────────────────

def generate_markdown_report(db: Session, audit_run, output_path: str) -> str:
    d = _load_all(db, audit_run)
    vendors, issues_sorted, exec_metrics = d["vendors"], d["issues_sorted"], d["exec_metrics"]
    cookie_reg, attributions, perf_stats = d["cookie_reg"], d["attributions"], d["perf_stats"]

    mode_val   = audit_run.mode if isinstance(audit_run.mode, str) else audit_run.mode.value
    status_val = audit_run.status if isinstance(audit_run.status, str) else audit_run.status.value
    ic = exec_metrics["issue_counts"]

    lines = [
        "# Odit Tracking Audit Report",
        "",
        f"**URL:** {audit_run.base_url}  ",
        f"**Mode:** {mode_val}  ",
        f"**Status:** {status_val}  ",
        f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}  ",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
        f"| | |",
        f"|---|---|",
        f"| **Risk Rating** | **{exec_metrics['risk_rating']}** |",
        f"| GDPR / ePrivacy | {exec_metrics['gdpr_posture']} |",
        f"| CCPA / CPRA | {exec_metrics['ccpa_posture']} |",
        f"| Vendors Detected | {exec_metrics['vendor_count']} |",
        f"| Total Issues | {exec_metrics['total_issues']} — Critical: {ic['critical']}, High: {ic['high']}, Medium: {ic['medium']}, Low: {ic['low']} |",
        "",
    ]

    if exec_metrics["top_issues"]:
        lines.append("**Top Findings:**")
        lines.append("")
        for issue in exec_metrics["top_issues"]:
            icon = SEV_ICON.get(issue.severity, "⚪")
            lines.append(f"- {icon} **{issue.title}** — {issue.description[:120]}{'...' if len(issue.description) > 120 else ''}")
        lines.append("")

    lines.extend([
        "---",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Pages Crawled | {audit_run.pages_crawled} |",
        f"| Pages Failed | {audit_run.pages_failed} |",
        f"| Vendors Detected | {len(vendors)} |",
        f"| Total Issues | {len(issues_sorted)} |",
        f"| Critical | {ic['critical']} |",
        f"| High | {ic['high']} |",
        f"| Medium | {ic['medium']} |",
        f"| Low | {ic['low']} |",
        "",
        "---",
        "",
        "## Detected Vendors",
        "",
    ])

    if vendors:
        lines.append("| Vendor | Category | Detection Method | Load Source | Pages |")
        lines.append("|--------|----------|-----------------|-------------|-------|")
        for v in vendors:
            src = attributions.get(v.vendor_key, "Unknown")
            lines.append(f"| {v.vendor_name} | {v.category} | {v.detection_method} | {src} | {v.page_count} |")
    else:
        lines.append("_No vendors detected._")

    # Cookie Register
    lines.extend(["", "---", "", "## Cookie Register", ""])
    if cookie_reg:
        lines.append("| Cookie | Domain | Party | Expiry | Category | Vendor |")
        lines.append("|--------|--------|-------|--------|----------|--------|")
        for c in cookie_reg:
            lines.append(
                f"| `{c['name']}` | {c['domain']} | {c['party']} | {c['expiry']} | {c['purpose_category']} | {c['vendor'] or '—'} |"
            )
    else:
        lines.append("_No cookies captured._")

    # Performance
    lines.extend(["", "---", "", "## Third-Party Performance Impact", ""])
    perf_with_data = [s for s in perf_stats if s["has_data"]]
    if perf_with_data:
        lines.append("| Vendor | Category | Requests | Avg Load (ms) | Max Load (ms) | Pages |")
        lines.append("|--------|----------|----------|--------------|--------------|-------|")
        for s in perf_with_data:
            lines.append(
                f"| {s['vendor_name']} | {s['category']} | {s['request_count']} "
                f"| {s['avg_timing_ms']} | {s['max_timing_ms']} | {s['pages_affected']} |"
            )
    else:
        lines.append("_No timing data captured._")

    # Issues
    lines.extend(["", "---", "", "## Issues", ""])
    if issues_sorted:
        for issue in issues_sorted:
            icon = SEV_ICON.get(issue.severity, "⚪")
            lines.append(f"### {icon} [{issue.severity.upper()}] {issue.title}")
            lines.append("")
            lines.append(f"**Category:** {issue.category}  ")
            if issue.affected_vendor_key:
                lines.append(f"**Vendor:** `{issue.affected_vendor_key}`  ")
            if issue.affected_url:
                lines.append(f"**URL:** `{issue.affected_url[:200]}`  ")
            lines.append("")
            lines.append(issue.description)
            lines.append("")
            if issue.likely_cause:
                lines.append(f"**Likely Cause:** {issue.likely_cause}")
                lines.append("")
            if issue.recommendation:
                lines.append(f"**Recommendation:** {issue.recommendation}")
                lines.append("")
            if issue.remediation_steps:
                lines.append(f"**Remediation Steps:**")
                lines.append("")
                lines.append(issue.remediation_steps)
                lines.append("")
            if issue.evidence_refs:
                lines.append("**Evidence:**")
                for ref in (issue.evidence_refs or [])[:5]:
                    if isinstance(ref, str):
                        lines.append(f"- `{ref[:200]}`")
                    elif isinstance(ref, dict):
                        url = ref.get("url", ref.get("request_url", ""))
                        if url:
                            lines.append(f"- `{url[:200]}`")
                lines.append("")
            lines.append("---")
            lines.append("")
    else:
        lines.append("_No issues detected._")

    content = "\n".join(lines)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"Markdown report saved: {output_path}")
    return output_path


# ─────────────────────────────────────────────────────────────────────────────
# HTML Report
# ─────────────────────────────────────────────────────────────────────────────

def generate_html_report(db: Session, audit_run, output_path: str) -> str:
    d = _load_all(db, audit_run)
    vendors, issues_sorted, exec_metrics = d["vendors"], d["issues_sorted"], d["exec_metrics"]
    cookie_reg, attributions, perf_stats = d["cookie_reg"], d["attributions"], d["perf_stats"]

    mode_val   = audit_run.mode if isinstance(audit_run.mode, str) else audit_run.mode.value
    status_val = audit_run.status if isinstance(audit_run.status, str) else audit_run.status.value
    ic = exec_metrics["issue_counts"]

    risk_color = exec_metrics["risk_color"]

    # ── Executive Summary block ──────────────────────────────────────────
    top_findings_html = ""
    for issue in exec_metrics["top_issues"]:
        icon = SEV_ICON.get(issue.severity, "⚪")
        clr  = SEV_COLOR.get(issue.severity, "#374151")
        top_findings_html += f"""
        <div style="display:flex;gap:8px;margin-bottom:6px;align-items:flex-start;">
            <span style="font-size:14px;flex-shrink:0;">{icon}</span>
            <div>
                <strong style="color:{clr};">{_esc(issue.title)}</strong>
                <p style="margin:2px 0 0;font-size:12px;color:#6b7280;">{_esc(issue.description[:150])}{'...' if len(issue.description) > 150 else ''}</p>
            </div>
        </div>"""

    risk_bg = {
        "Low": "#f0fdf4", "Medium": "#fefce8", "High": "#fff7ed", "Critical": "#fef2f2"
    }.get(exec_metrics["risk_rating"], "#f9fafb")

    exec_html = f"""
<section style="background:{risk_bg};border:2px solid {risk_color};border-radius:8px;padding:24px;margin-bottom:32px;">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:16px;">
        <div>
            <h2 style="margin:0 0 4px;color:#1f2937;font-size:18px;">Executive Summary</h2>
            <p style="margin:0;font-size:13px;color:#6b7280;">
                {_esc(audit_run.base_url)} &nbsp;·&nbsp; {_esc(mode_val)} &nbsp;·&nbsp;
                {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
            </p>
        </div>
        <div style="text-align:right;">
            <div style="font-size:12px;color:#6b7280;margin-bottom:2px;">Risk Rating</div>
            <div style="background:{risk_color};color:white;font-weight:bold;font-size:18px;
                         padding:6px 20px;border-radius:20px;display:inline-block;">
                {_esc(exec_metrics["risk_rating"])}
            </div>
        </div>
    </div>

    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:20px 0 16px;">
        <div style="background:white;border-radius:6px;padding:12px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.08);">
            <div style="font-size:28px;font-weight:bold;color:#dc2626;">{ic['critical']}</div>
            <div style="font-size:11px;color:#6b7280;margin-top:2px;">Critical</div>
        </div>
        <div style="background:white;border-radius:6px;padding:12px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.08);">
            <div style="font-size:28px;font-weight:bold;color:#ea580c;">{ic['high']}</div>
            <div style="font-size:11px;color:#6b7280;margin-top:2px;">High</div>
        </div>
        <div style="background:white;border-radius:6px;padding:12px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.08);">
            <div style="font-size:28px;font-weight:bold;color:#ca8a04;">{ic['medium']}</div>
            <div style="font-size:11px;color:#6b7280;margin-top:2px;">Medium</div>
        </div>
        <div style="background:white;border-radius:6px;padding:12px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.08);">
            <div style="font-size:28px;font-weight:bold;color:#2563eb;">{ic['low']}</div>
            <div style="font-size:11px;color:#6b7280;margin-top:2px;">Low</div>
        </div>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;">
        <div style="background:white;border-radius:6px;padding:12px;box-shadow:0 1px 3px rgba(0,0,0,.08);">
            <div style="font-size:11px;font-weight:bold;text-transform:uppercase;color:#6b7280;margin-bottom:6px;">Compliance Posture</div>
            <div style="margin-bottom:4px;font-size:13px;"><strong>GDPR:</strong> {_esc(exec_metrics["gdpr_posture"])}</div>
            <div style="font-size:13px;"><strong>CCPA:</strong> {_esc(exec_metrics["ccpa_posture"])}</div>
        </div>
        <div style="background:white;border-radius:6px;padding:12px;box-shadow:0 1px 3px rgba(0,0,0,.08);">
            <div style="font-size:11px;font-weight:bold;text-transform:uppercase;color:#6b7280;margin-bottom:6px;">Scope</div>
            <div style="font-size:13px;margin-bottom:2px;">{exec_metrics['pages_crawled']} pages crawled &nbsp;·&nbsp; {exec_metrics['vendor_count']} vendors found</div>
            <div style="font-size:13px;">Consent mode: <code style="background:#f3f4f6;padding:1px 5px;border-radius:3px;">{_esc(exec_metrics['consent_mode'])}</code></div>
        </div>
    </div>

    {"<div style='background:white;border-radius:6px;padding:12px;box-shadow:0 1px 3px rgba(0,0,0,.08);'><div style='font-size:11px;font-weight:bold;text-transform:uppercase;color:#6b7280;margin-bottom:8px;'>Top Findings</div>" + top_findings_html + "</div>" if top_findings_html else ""}
</section>"""

    # ── Vendor table ─────────────────────────────────────────────────────
    vendor_rows = ""
    for v in vendors:
        cat_style = CAT_BADGE_STYLE.get(v.category, CAT_BADGE_STYLE["unknown"])
        src = _esc(attributions.get(v.vendor_key, "Unknown"))
        src_color = "#374151"
        if "GTM" in src:
            src_color = "#1d4ed8"
        elif "Direct" in src:
            src_color = "#065f46"
        elif "Pixel" in src or "API" in src:
            src_color = "#7c3aed"
        vendor_rows += f"""
        <tr>
            <td><strong>{_esc(v.vendor_name)}</strong><br><small style="color:#9ca3af;">{_esc(v.vendor_key)}</small></td>
            <td><span style="font-size:11px;padding:2px 8px;border-radius:10px;{cat_style};">{_esc(v.category)}</span></td>
            <td style="font-size:12px;color:#6b7280;">{_esc(v.detection_method)}</td>
            <td style="font-size:12px;font-weight:500;color:{src_color};">{src}</td>
            <td style="text-align:center;">{v.page_count}</td>
        </tr>"""

    # ── Cookie Register table ─────────────────────────────────────────────
    cookie_rows = ""
    for c in cookie_reg:
        cat_style = CAT_BADGE_STYLE.get(c["purpose_category"], CAT_BADGE_STYLE["unknown"])
        party_color = "#065f46" if c["party"] == "1st" else ("#991b1b" if c["party"] == "3rd" else "#374151")
        cookie_rows += f"""
        <tr>
            <td><code style="font-size:11px;">{_esc(c['name'])}</code></td>
            <td style="font-size:12px;color:#6b7280;">{_esc(c['domain'])}</td>
            <td style="font-size:12px;font-weight:600;color:{party_color};">{_esc(c['party'])}</td>
            <td style="font-size:12px;">{_esc(c['expiry'])}</td>
            <td><span style="font-size:11px;padding:2px 8px;border-radius:10px;{cat_style};">{_esc(c['purpose_category'])}</span></td>
            <td style="font-size:12px;">{_esc(c['vendor'])}</td>
            <td style="font-size:11px;color:#6b7280;">{_esc(c['description'])}</td>
            <td style="text-align:center;font-size:12px;">{c['page_count']}</td>
        </tr>"""

    # ── Performance table ─────────────────────────────────────────────────
    perf_rows = ""
    perf_with_data = [s for s in perf_stats if s["has_data"]]
    for s in perf_with_data:
        avg = s["avg_timing_ms"] or 0
        bar_width = min(int(avg / 10), 100)  # cap at 1000ms = 100%
        bar_color = "#dc2626" if avg > 500 else ("#ea580c" if avg > 200 else "#16a34a")
        cat_style = CAT_BADGE_STYLE.get(s["category"], CAT_BADGE_STYLE["unknown"])
        perf_rows += f"""
        <tr>
            <td><strong style="font-size:13px;">{_esc(s['vendor_name'])}</strong></td>
            <td><span style="font-size:11px;padding:2px 8px;border-radius:10px;{cat_style};">{_esc(s['category'])}</span></td>
            <td style="text-align:center;">{s['request_count']}</td>
            <td>
                <div style="display:flex;align-items:center;gap:8px;">
                    <div style="flex:1;background:#f3f4f6;border-radius:4px;height:8px;overflow:hidden;">
                        <div style="width:{bar_width}%;height:100%;background:{bar_color};border-radius:4px;"></div>
                    </div>
                    <span style="font-size:12px;font-weight:600;color:{bar_color};min-width:40px;">{int(avg)}ms</span>
                </div>
            </td>
            <td style="text-align:center;font-size:12px;color:#6b7280;">{int(s['max_timing_ms'] or 0)}ms</td>
            <td style="text-align:center;">{s['pages_affected']}</td>
        </tr>"""

    # ── Issue sections ────────────────────────────────────────────────────
    issue_sections = ""
    for issue in issues_sorted:
        bg    = SEV_BG.get(issue.severity, "#f9fafb")
        color = SEV_COLOR.get(issue.severity, "#374151")
        icon  = SEV_ICON.get(issue.severity, "⚪")

        vendor_str = (
            f'<span style="background:#f3f4f6;padding:1px 6px;border-radius:4px;font-size:11px;margin-left:4px;">'
            f'{_esc(issue.affected_vendor_key)}</span>'
        ) if issue.affected_vendor_key else ""

        url_str = (
            f'<div style="margin-top:4px;font-size:11px;color:#6b7280;">'
            f'URL: <code>{_esc(issue.affected_url[:200])}</code></div>'
        ) if issue.affected_url else ""

        cause_str = (
            f'<p style="margin:8px 0 0;font-size:13px;"><strong>Likely Cause:</strong> {_esc(issue.likely_cause)}</p>'
        ) if issue.likely_cause else ""

        rec_str = (
            f'<p style="margin:8px 0 0;font-size:13px;"><strong>Recommendation:</strong> {_esc(issue.recommendation)}</p>'
        ) if issue.recommendation else ""

        remediation_str = ""
        if issue.remediation_steps:
            remediation_str = (
                f'<div style="margin-top:10px;background:rgba(0,0,0,.04);padding:10px 12px;border-radius:4px;">'
                f'<strong style="font-size:12px;">Remediation Steps:</strong>'
                f'<p style="margin:4px 0 0;font-size:12px;white-space:pre-line;">{_esc(issue.remediation_steps)}</p>'
                f'</div>'
            )

        evidence_str = ""
        if issue.evidence_refs:
            ev_items = ""
            for ref in (issue.evidence_refs or [])[:5]:
                url = ref if isinstance(ref, str) else ref.get("url", ref.get("request_url", "")) if isinstance(ref, dict) else ""
                if url:
                    ev_items += f'<li style="margin:2px 0;"><code style="font-size:11px;word-break:break-all;">{_esc(str(url)[:200])}</code></li>'
            if ev_items:
                evidence_str = (
                    f'<div style="margin-top:10px;">'
                    f'<strong style="font-size:12px;">Evidence:</strong>'
                    f'<ul style="margin:4px 0 0;padding-left:20px;">{ev_items}</ul>'
                    f'</div>'
                )

        issue_sections += f"""
        <div style="background:{bg};border-left:4px solid {color};padding:14px 16px;margin-bottom:14px;border-radius:4px;">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                <span style="font-size:14px;">{icon}</span>
                <span style="background:{color};color:white;font-size:11px;font-weight:bold;
                              padding:2px 8px;border-radius:12px;text-transform:uppercase;">{_esc(issue.severity)}</span>
                <strong style="font-size:14px;">{_esc(issue.title)}</strong>
                {vendor_str}
            </div>
            <small style="color:#6b7280;">{_esc(issue.category)}</small>
            {url_str}
            <p style="margin-top:8px;font-size:13px;">{_esc(issue.description)}</p>
            {cause_str}
            {rec_str}
            {remediation_str}
            {evidence_str}
        </div>"""

    cookie_section = f"""
<h2>Cookie Register ({len(cookie_reg)})</h2>
<p style="font-size:13px;color:#6b7280;margin-bottom:12px;">
    All cookies observed during the crawl, deduplicated and classified by purpose.
    Use this as the basis for your cookie policy and CMP category configuration.
</p>
{"<table><thead><tr><th>Cookie</th><th>Domain</th><th>Party</th><th>Expiry</th><th>Category</th><th>Vendor</th><th>Description</th><th>Pages</th></tr></thead><tbody>" + cookie_rows + "</tbody></table>" if cookie_rows else "<p><em>No cookies captured.</em></p>"}
"""

    perf_section = f"""
<h2>Third-Party Performance Impact</h2>
<p style="font-size:13px;color:#6b7280;margin-bottom:12px;">
    Load times captured per vendor request. Vendors above 200ms avg warrant investigation.
</p>
{"<table><thead><tr><th>Vendor</th><th>Category</th><th>Requests</th><th>Avg Load Time</th><th>Max Load Time</th><th>Pages</th></tr></thead><tbody>" + perf_rows + "</tbody></table>" if perf_rows else "<p><em>No timing data available.</em></p>"}
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Odit Audit Report — {_esc(audit_run.base_url)}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          max-width: 960px; margin: 40px auto; padding: 0 20px; color: #1f2937; }}
  h1   {{ color: #1e3a5f; border-bottom: 2px solid #e5e7eb; padding-bottom: 10px; margin-bottom: 8px; }}
  h2   {{ color: #1e3a5f; margin-top: 36px; margin-bottom: 4px; font-size: 18px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 13px; }}
  th    {{ background: #1e3a5f; color: white; padding: 8px 12px; text-align: left; font-size:12px; }}
  td    {{ padding: 8px 12px; border-bottom: 1px solid #e5e7eb; vertical-align: top; }}
  tr:hover td {{ background: #f9fafb; }}
  code  {{ background: #f3f4f6; padding: 2px 5px; border-radius: 3px; font-size: 12px; }}
  @media print {{
    body {{ max-width: 100%; margin: 0; padding: 10px; }}
    section {{ break-inside: avoid; }}
  }}
</style>
</head>
<body>
<h1>Odit Tracking Audit Report</h1>
<p style="color:#6b7280;font-size:13px;margin-top:0;">
    {_esc(audit_run.base_url)} &nbsp;·&nbsp; {_esc(mode_val)} &nbsp;·&nbsp;
    {_esc(status_val)} &nbsp;·&nbsp; {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
</p>

{exec_html}

<h2>Detected Vendors ({len(vendors)})</h2>
{"<table><thead><tr><th>Vendor</th><th>Category</th><th>Detection Method</th><th>Load Source</th><th>Pages</th></tr></thead><tbody>" + vendor_rows + "</tbody></table>" if vendor_rows else "<p><em>No vendors detected.</em></p>"}

{cookie_section}

{perf_section}

<h2>Issues ({len(issues_sorted)})</h2>
{issue_sections if issue_sections else "<p><em>No issues detected.</em></p>"}

<hr style="margin-top:48px;border:none;border-top:1px solid #e5e7eb;">
<p style="font-size:11px;color:#9ca3af;text-align:center;margin-bottom:32px;">
    Generated by Odit — Local-first tracking auditor &nbsp;·&nbsp;
    {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
</p>
</body>
</html>"""

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"HTML report saved: {output_path}")
    return output_path
