"""
Excel exporter: generates a comprehensive Excel workbook using openpyxl.
"""
import os
import logging
from datetime import datetime
from typing import List
from sqlalchemy.orm import Session
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger("odit.worker.excel_exporter")

SEVERITY_COLORS = {
    "critical": "FFCCCC",
    "high": "FFE0CC",
    "medium": "FFFACC",
    "low": "CCE5FF",
}

HEADER_FILL = PatternFill(start_color="1E3A5F", end_color="1E3A5F", fill_type="solid")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
SUBHEADER_FILL = PatternFill(start_color="D9E8F5", end_color="D9E8F5", fill_type="solid")
SUBHEADER_FONT = Font(bold=True, size=10)


def _write_header_row(ws, headers: List[str]) -> None:
    row = ws.max_row + 1 if ws.max_row > 1 else 1
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=row, column=col, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="left", vertical="center")


def _auto_size_columns(ws, max_width: int = 60) -> None:
    for col in ws.columns:
        max_length = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = min(max_length + 4, max_width)


def generate_excel(db: Session, audit_run, output_path: str) -> str:
    from app.models import (
        PageVisit, NetworkRequest, ConsoleEvent, DetectedVendor, Issue, AuditConfig
    )

    audit_id = audit_run.id
    config = db.query(AuditConfig).filter(AuditConfig.id == audit_run.config_id).first()

    pages = db.query(PageVisit).filter(PageVisit.audit_run_id == audit_id).all()
    requests = db.query(NetworkRequest).filter(NetworkRequest.audit_run_id == audit_id).all()
    console_events = db.query(ConsoleEvent).filter(ConsoleEvent.audit_run_id == audit_id).all()
    vendors = (
        db.query(DetectedVendor)
        .filter(DetectedVendor.audit_run_id == audit_id, DetectedVendor.page_visit_id == None)
        .all()
    )
    issues = db.query(Issue).filter(Issue.audit_run_id == audit_id).all()
    issues_sorted = sorted(issues, key=lambda i: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(i.severity, 99))

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    # ---- Sheet 1: Summary ----
    ws_summary = wb.create_sheet("Summary")
    ws_summary.column_dimensions["A"].width = 30
    ws_summary.column_dimensions["B"].width = 50

    summary_data = [
        ("Audit ID", str(audit_run.id)),
        ("Base URL", audit_run.base_url),
        ("Mode", audit_run.mode if isinstance(audit_run.mode, str) else audit_run.mode.value),
        ("Status", audit_run.status if isinstance(audit_run.status, str) else audit_run.status.value),
        ("Created At", str(audit_run.created_at)),
        ("Started At", str(audit_run.started_at) if audit_run.started_at else "—"),
        ("Completed At", str(audit_run.completed_at) if audit_run.completed_at else "—"),
        ("", ""),
        ("Pages Discovered", audit_run.pages_discovered),
        ("Pages Crawled", audit_run.pages_crawled),
        ("Pages Failed", audit_run.pages_failed),
        ("", ""),
        ("Vendors Detected", len(vendors)),
        ("Total Issues", len(issues)),
        ("Critical Issues", sum(1 for i in issues if i.severity == "critical")),
        ("High Issues", sum(1 for i in issues if i.severity == "high")),
        ("Medium Issues", sum(1 for i in issues if i.severity == "medium")),
        ("Low Issues", sum(1 for i in issues if i.severity == "low")),
    ]

    ws_summary.cell(row=1, column=1, value="Odit Tracking Audit Summary").font = Font(bold=True, size=14)
    ws_summary.cell(row=2, column=1, value=f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}").font = Font(italic=True, size=10)

    for i, (key, val) in enumerate(summary_data, start=4):
        ws_summary.cell(row=i, column=1, value=key).font = Font(bold=True)
        ws_summary.cell(row=i, column=2, value=val)

    # ---- Sheet 2: Pages ----
    ws_pages = wb.create_sheet("Pages")
    _write_header_row(ws_pages, [
        "URL", "Final URL", "Status Code", "Title", "Group",
        "Load Time (ms)", "Console Errors", "Failed Requests",
        "Vendor Count", "Crawled At", "Error"
    ])

    from collections import defaultdict
    page_vendor_counts = defaultdict(int)
    for pv in db.query(DetectedVendor).filter(
        DetectedVendor.audit_run_id == audit_id,
        DetectedVendor.page_visit_id != None
    ).all():
        page_vendor_counts[str(pv.page_visit_id)] += 1

    for page in pages:
        ws_pages.append([
            page.url,
            page.final_url,
            page.status_code,
            page.page_title,
            page.page_group,
            round(page.load_time_ms, 1) if page.load_time_ms else None,
            page.console_error_count,
            page.failed_request_count,
            page_vendor_counts.get(str(page.id), 0),
            str(page.crawled_at) if page.crawled_at else None,
            page.error_message,
        ])
    _auto_size_columns(ws_pages)

    # ---- Sheet 3: Vendors ----
    ws_vendors = wb.create_sheet("Vendors")
    _write_header_row(ws_vendors, [
        "Vendor Key", "Vendor Name", "Category", "Detection Method", "Page Count", "Evidence"
    ])
    for v in vendors:
        ws_vendors.append([
            v.vendor_key,
            v.vendor_name,
            v.category,
            v.detection_method,
            v.page_count,
            str(v.evidence) if v.evidence else "",
        ])
    _auto_size_columns(ws_vendors)

    # ---- Sheet 4: Issues ----
    ws_issues = wb.create_sheet("Issues")
    _write_header_row(ws_issues, [
        "Severity", "Category", "Title", "Description",
        "Affected URL", "Affected Vendor", "Likely Cause", "Recommendation"
    ])
    for issue in issues_sorted:
        row_idx = ws_issues.max_row + 1
        ws_issues.append([
            issue.severity,
            issue.category,
            issue.title,
            issue.description,
            issue.affected_url or "",
            issue.affected_vendor_key or "",
            issue.likely_cause or "",
            issue.recommendation or "",
        ])
        # Color code by severity
        if issue.severity in SEVERITY_COLORS:
            fill = PatternFill(
                start_color=SEVERITY_COLORS[issue.severity],
                end_color=SEVERITY_COLORS[issue.severity],
                fill_type="solid"
            )
            for col in range(1, 9):
                ws_issues.cell(row=row_idx, column=col).fill = fill
    _auto_size_columns(ws_issues)

    # ---- Sheet 5: Broken_Requests ----
    ws_broken = wb.create_sheet("Broken_Requests")
    _write_header_row(ws_broken, [
        "URL", "Method", "Status Code", "Resource Type",
        "Is Tracking", "Failed", "Failure Reason", "Page Visit ID"
    ])
    broken_reqs = [r for r in requests if r.failed or (r.status_code and r.status_code >= 400)]
    for req in broken_reqs[:500]:
        ws_broken.append([
            req.url[:200],
            req.method,
            req.status_code,
            req.resource_type,
            req.is_tracking_related,
            req.failed,
            req.failure_reason or "",
            str(req.page_visit_id),
        ])
    _auto_size_columns(ws_broken)

    # ---- Sheet 6: Console_Errors ----
    ws_console = wb.create_sheet("Console_Errors")
    _write_header_row(ws_console, [
        "Level", "Message", "Source URL", "Line", "Column", "Page Visit ID", "Captured At"
    ])
    error_events = [e for e in console_events if e.level == "error"]
    for evt in error_events[:500]:
        ws_console.append([
            evt.level,
            evt.message[:300],
            evt.source_url or "",
            evt.line_number,
            evt.column_number,
            str(evt.page_visit_id),
            str(evt.captured_at),
        ])
    _auto_size_columns(ws_console)

    # ---- Sheet 7: Scripts ----
    ws_scripts = wb.create_sheet("Scripts")
    _write_header_row(ws_scripts, ["Page URL", "Script Src", "Is Tracking"])
    script_entries = []
    from worker.detectors.vendor_detector import is_tracking_url
    for page in pages:
        for src in (page.script_srcs or []):
            script_entries.append([page.url, src, is_tracking_url(src)])
    for entry in script_entries[:1000]:
        ws_scripts.append(entry)
    _auto_size_columns(ws_scripts, max_width=80)

    # ---- Sheet 8: Cookies_Storage ----
    ws_cookies = wb.create_sheet("Cookies_Storage")
    _write_header_row(ws_cookies, [
        "Page URL", "Cookie Names", "LocalStorage Keys", "SessionStorage Keys"
    ])
    for page in pages:
        ws_cookies.append([
            page.url,
            ", ".join(page.cookies or [])[:300],
            ", ".join(page.local_storage_keys or [])[:300],
            ", ".join(page.session_storage_keys or [])[:300],
        ])
    _auto_size_columns(ws_cookies)

    # ---- Sheet 9: Recommendations ----
    ws_recs = wb.create_sheet("Recommendations")
    _write_header_row(ws_recs, ["Priority", "Issue Title", "Recommendation", "Affected Vendor"])
    for i, issue in enumerate(issues_sorted, 1):
        ws_recs.append([
            f"{i}. {issue.severity.upper()}",
            issue.title,
            issue.recommendation or "See issue details.",
            issue.affected_vendor_key or "",
        ])
    _auto_size_columns(ws_recs)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    wb.save(output_path)
    logger.info(f"Excel workbook saved: {output_path}")
    return output_path
