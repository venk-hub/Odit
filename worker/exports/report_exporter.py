"""
Report exporter: generates Markdown, HTML, and JSON summary reports.
"""
import os
import json
import logging
from datetime import datetime
from typing import List
from sqlalchemy.orm import Session

logger = logging.getLogger("odit.worker.report_exporter")


def generate_json_summary(db: Session, audit_run, output_path: str) -> str:
    from app.models import PageVisit, DetectedVendor, Issue, AuditConfig, Artifact

    audit_id = audit_run.id
    config = db.query(AuditConfig).filter(AuditConfig.id == audit_run.config_id).first()

    pages = db.query(PageVisit).filter(PageVisit.audit_run_id == audit_id).all()
    vendors = (
        db.query(DetectedVendor)
        .filter(DetectedVendor.audit_run_id == audit_id, DetectedVendor.page_visit_id == None)
        .all()
    )
    issues = db.query(Issue).filter(Issue.audit_run_id == audit_id).all()

    issue_counts = {
        "critical": sum(1 for i in issues if i.severity == "critical"),
        "high": sum(1 for i in issues if i.severity == "high"),
        "medium": sum(1 for i in issues if i.severity == "medium"),
        "low": sum(1 for i in issues if i.severity == "low"),
    }

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
        "issue_counts": issue_counts,
        "total_issues": sum(issue_counts.values()),
        "vendors": [
            {
                "key": v.vendor_key,
                "name": v.vendor_name,
                "category": v.category,
                "detection_method": v.detection_method,
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
                "recommendation": i.recommendation,
            }
            for i in sorted(issues, key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(x.severity, 99))
        ],
        "generated_at": datetime.utcnow().isoformat(),
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

    logger.info(f"JSON summary saved: {output_path}")
    return output_path


def generate_markdown_report(db: Session, audit_run, output_path: str) -> str:
    from app.models import PageVisit, DetectedVendor, Issue, AuditConfig

    audit_id = audit_run.id
    config = db.query(AuditConfig).filter(AuditConfig.id == audit_run.config_id).first()
    vendors = (
        db.query(DetectedVendor)
        .filter(DetectedVendor.audit_run_id == audit_id, DetectedVendor.page_visit_id == None)
        .all()
    )
    issues = db.query(Issue).filter(Issue.audit_run_id == audit_id).all()
    issues_sorted = sorted(issues, key=lambda i: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(i.severity, 99))

    issue_counts = {
        "critical": sum(1 for i in issues if i.severity == "critical"),
        "high": sum(1 for i in issues if i.severity == "high"),
        "medium": sum(1 for i in issues if i.severity == "medium"),
        "low": sum(1 for i in issues if i.severity == "low"),
    }

    mode_val = audit_run.mode if isinstance(audit_run.mode, str) else audit_run.mode.value
    status_val = audit_run.status if isinstance(audit_run.status, str) else audit_run.status.value

    lines = [
        f"# Odit Tracking Audit Report",
        f"",
        f"**URL:** {audit_run.base_url}  ",
        f"**Mode:** {mode_val}  ",
        f"**Status:** {status_val}  ",
        f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}  ",
        f"",
        f"---",
        f"",
        f"## Summary",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Pages Crawled | {audit_run.pages_crawled} |",
        f"| Pages Failed | {audit_run.pages_failed} |",
        f"| Vendors Detected | {len(vendors)} |",
        f"| Total Issues | {len(issues)} |",
        f"| Critical | {issue_counts['critical']} |",
        f"| High | {issue_counts['high']} |",
        f"| Medium | {issue_counts['medium']} |",
        f"| Low | {issue_counts['low']} |",
        f"",
        f"---",
        f"",
        f"## Detected Vendors",
        f"",
    ]

    if vendors:
        lines.append("| Vendor | Category | Detection Method | Pages |")
        lines.append("|--------|----------|------------------|-------|")
        for v in vendors:
            lines.append(f"| {v.vendor_name} | {v.category} | {v.detection_method} | {v.page_count} |")
    else:
        lines.append("_No vendors detected._")

    lines.extend([
        f"",
        f"---",
        f"",
        f"## Issues",
        f"",
    ])

    if issues_sorted:
        for issue in issues_sorted:
            sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(issue.severity, "⚪")
            lines.append(f"### {sev_icon} [{issue.severity.upper()}] {issue.title}")
            lines.append(f"")
            lines.append(f"**Category:** {issue.category}  ")
            if issue.affected_vendor_key:
                lines.append(f"**Vendor:** `{issue.affected_vendor_key}`  ")
            if issue.affected_url:
                lines.append(f"**URL:** `{issue.affected_url[:200]}`  ")
            lines.append(f"")
            lines.append(f"{issue.description}")
            lines.append(f"")
            if issue.likely_cause:
                lines.append(f"**Likely Cause:** {issue.likely_cause}")
                lines.append(f"")
            if issue.recommendation:
                lines.append(f"**Recommendation:** {issue.recommendation}")
                lines.append(f"")
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


def generate_html_report(db: Session, audit_run, output_path: str) -> str:
    from app.models import PageVisit, DetectedVendor, Issue, AuditConfig

    audit_id = audit_run.id
    vendors = (
        db.query(DetectedVendor)
        .filter(DetectedVendor.audit_run_id == audit_id, DetectedVendor.page_visit_id == None)
        .all()
    )
    issues = db.query(Issue).filter(Issue.audit_run_id == audit_id).all()
    issues_sorted = sorted(issues, key=lambda i: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(i.severity, 99))

    issue_counts = {
        "critical": sum(1 for i in issues if i.severity == "critical"),
        "high": sum(1 for i in issues if i.severity == "high"),
        "medium": sum(1 for i in issues if i.severity == "medium"),
        "low": sum(1 for i in issues if i.severity == "low"),
    }

    sev_colors = {"critical": "#dc2626", "high": "#ea580c", "medium": "#ca8a04", "low": "#2563eb"}
    sev_bgs = {"critical": "#fef2f2", "high": "#fff7ed", "medium": "#fefce8", "low": "#eff6ff"}

    mode_val = audit_run.mode if isinstance(audit_run.mode, str) else audit_run.mode.value
    status_val = audit_run.status if isinstance(audit_run.status, str) else audit_run.status.value

    vendor_rows = ""
    for v in vendors:
        vendor_rows += f"""
        <tr>
            <td>{v.vendor_name}</td>
            <td><span class="badge">{v.category}</span></td>
            <td>{v.detection_method}</td>
            <td>{v.page_count}</td>
        </tr>"""

    issue_sections = ""
    for issue in issues_sorted:
        bg = sev_bgs.get(issue.severity, "#f9fafb")
        color = sev_colors.get(issue.severity, "#374151")
        vendor_str = f"<br><small><strong>Vendor:</strong> <code>{issue.affected_vendor_key}</code></small>" if issue.affected_vendor_key else ""
        url_str = f"<br><small><strong>URL:</strong> <code>{issue.affected_url[:150]}</code></small>" if issue.affected_url else ""
        cause_str = f"<p><strong>Likely Cause:</strong> {issue.likely_cause}</p>" if issue.likely_cause else ""
        rec_str = f"<p><strong>Recommendation:</strong> {issue.recommendation}</p>" if issue.recommendation else ""
        issue_sections += f"""
        <div style="background:{bg};border-left:4px solid {color};padding:12px 16px;margin-bottom:12px;border-radius:4px;">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                <span style="background:{color};color:white;font-size:11px;font-weight:bold;padding:2px 8px;border-radius:12px;text-transform:uppercase;">{issue.severity}</span>
                <strong style="font-size:14px;">{issue.title}</strong>
            </div>
            <small style="color:#6b7280;">{issue.category}{vendor_str}{url_str}</small>
            <p style="margin-top:8px;font-size:13px;">{issue.description}</p>
            {cause_str}
            {rec_str}
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>Odit Audit Report — {audit_run.base_url}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; color: #1f2937; }}
  h1 {{ color: #1e3a5f; border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; }}
  h2 {{ color: #374151; margin-top: 32px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 13px; }}
  th {{ background: #1e3a5f; color: white; padding: 8px 12px; text-align: left; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #e5e7eb; }}
  tr:hover td {{ background: #f9fafb; }}
  .badge {{ background: #e5e7eb; padding: 2px 8px; border-radius: 12px; font-size: 11px; }}
  .stat-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 24px 0; }}
  .stat-card {{ border-radius: 8px; padding: 16px; text-align: center; }}
  .stat-card .number {{ font-size: 32px; font-weight: bold; }}
  .stat-card .label {{ font-size: 12px; margin-top: 4px; }}
  code {{ background: #f3f4f6; padding: 2px 6px; border-radius: 4px; font-size: 12px; }}
</style>
</head>
<body>
<h1>Odit Tracking Audit Report</h1>
<p>
  <strong>URL:</strong> {audit_run.base_url}<br>
  <strong>Mode:</strong> {mode_val}<br>
  <strong>Status:</strong> {status_val}<br>
  <strong>Generated:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}<br>
  <strong>Pages Crawled:</strong> {audit_run.pages_crawled}
</p>

<h2>Issue Summary</h2>
<div class="stat-grid">
  <div class="stat-card" style="background:#fef2f2;">
    <div class="number" style="color:#dc2626;">{issue_counts['critical']}</div>
    <div class="label" style="color:#dc2626;">Critical</div>
  </div>
  <div class="stat-card" style="background:#fff7ed;">
    <div class="number" style="color:#ea580c;">{issue_counts['high']}</div>
    <div class="label" style="color:#ea580c;">High</div>
  </div>
  <div class="stat-card" style="background:#fefce8;">
    <div class="number" style="color:#ca8a04;">{issue_counts['medium']}</div>
    <div class="label" style="color:#ca8a04;">Medium</div>
  </div>
  <div class="stat-card" style="background:#eff6ff;">
    <div class="number" style="color:#2563eb;">{issue_counts['low']}</div>
    <div class="label" style="color:#2563eb;">Low</div>
  </div>
</div>

<h2>Detected Vendors ({len(vendors)})</h2>
{"<table><thead><tr><th>Vendor</th><th>Category</th><th>Detection Method</th><th>Pages</th></tr></thead><tbody>" + vendor_rows + "</tbody></table>" if vendors else "<p><em>No vendors detected.</em></p>"}

<h2>Issues ({len(issues)})</h2>
{issue_sections if issue_sections else "<p><em>No issues detected.</em></p>"}

<hr style="margin-top:40px;">
<p style="font-size:12px;color:#9ca3af;text-align:center;">Generated by Odit v1.0 — Local-first tracking auditor</p>
</body>
</html>"""

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"HTML report saved: {output_path}")
    return output_path
