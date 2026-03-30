from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
import uuid
import os
import logging

logger = logging.getLogger("odit.web")

from app.database import get_db
from app.models import AuditRun, AuditConfig, Issue, DetectedVendor, PageVisit, Artifact, AuditComparison, AuditStatus
from app.models.page import NetworkRequest, ConsoleEvent
from app.models.setting import AppSetting

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AuditRun).order_by(desc(AuditRun.created_at)).limit(50)
    )
    runs = result.scalars().all()

    audits = []
    for run in runs:
        issue_counts = await db.execute(
            select(Issue.severity, func.count(Issue.id))
            .where(Issue.audit_run_id == run.id)
            .group_by(Issue.severity)
        )
        counts = {row[0]: row[1] for row in issue_counts}
        audits.append({"run": run, "issue_counts": counts})

    return templates.TemplateResponse("new_audit.html", {"request": request, "audits": audits})


@router.get("/audits/new", response_class=HTMLResponse)
async def new_audit_form(request: Request):
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/", status_code=302)


@router.get("/audits/{audit_id}", response_class=HTMLResponse)
async def audit_detail(request: Request, audit_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uid = uuid.UUID(audit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid audit ID")

    result = await db.execute(select(AuditRun).where(AuditRun.id == uid))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Audit not found")

    # Load key report artifacts for quick-download buttons in header
    key_artifacts = []
    if run.status.value == "completed":
        art_result = await db.execute(
            select(Artifact)
            .where(Artifact.audit_run_id == uid)
            .where(Artifact.artifact_type.in_(["excel", "report_html", "report_md"]))
            .order_by(Artifact.created_at)
        )
        key_artifacts = art_result.scalars().all()

    return templates.TemplateResponse(
        "audit_detail.html",
        {"request": request, "run": run, "audit_id": audit_id, "key_artifacts": key_artifacts}
    )


@router.get("/audits/{audit_id}/pages", response_class=HTMLResponse)
async def audit_pages(request: Request, audit_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uid = uuid.UUID(audit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid audit ID")

    result = await db.execute(select(AuditRun).where(AuditRun.id == uid))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Audit not found")

    pages_result = await db.execute(
        select(PageVisit)
        .where(PageVisit.audit_run_id == uid)
        .order_by(desc(PageVisit.crawled_at))
    )
    pages = pages_result.scalars().all()

    page_data = []
    for pv in pages:
        vc_result = await db.execute(
            select(func.count(DetectedVendor.id)).where(DetectedVendor.page_visit_id == pv.id)
        )
        vendor_count = vc_result.scalar()
        page_data.append({"visit": pv, "vendor_count": vendor_count})

    return templates.TemplateResponse(
        "partials/pages_table.html",
        {"request": request, "pages": page_data, "run": run, "audit_id": audit_id}
    )


@router.get("/audits/{audit_id}/pages/{page_id}", response_class=HTMLResponse)
async def page_detail(request: Request, audit_id: str, page_id: str, db: AsyncSession = Depends(get_db)):
    try:
        audit_uid = uuid.UUID(audit_id)
        page_uid = uuid.UUID(page_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID")

    result = await db.execute(select(AuditRun).where(AuditRun.id == audit_uid))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Audit not found")

    pv_result = await db.execute(
        select(PageVisit).where(PageVisit.id == page_uid).where(PageVisit.audit_run_id == audit_uid)
    )
    page = pv_result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    reqs_result = await db.execute(
        select(NetworkRequest)
        .where(NetworkRequest.page_visit_id == page_uid)
        .order_by(NetworkRequest.captured_at)
    )
    network_requests = reqs_result.scalars().all()

    console_result = await db.execute(
        select(ConsoleEvent)
        .where(ConsoleEvent.page_visit_id == page_uid)
        .order_by(ConsoleEvent.captured_at)
    )
    console_events = console_result.scalars().all()

    vendors_result = await db.execute(
        select(DetectedVendor)
        .where(DetectedVendor.page_visit_id == page_uid)
        .order_by(DetectedVendor.category)
    )
    vendors = vendors_result.scalars().all()

    issues_result = await db.execute(
        select(Issue).where(Issue.page_visit_id == page_uid)
    )
    issues = issues_result.scalars().all()

    return templates.TemplateResponse(
        "page_detail.html",
        {
            "request": request,
            "run": run,
            "page": page,
            "audit_id": audit_id,
            "network_requests": network_requests,
            "console_events": console_events,
            "vendors": vendors,
            "issues": issues,
        }
    )


@router.get("/audits/{audit_id}/issues", response_class=HTMLResponse)
async def audit_issues(
    request: Request,
    audit_id: str,
    severity: str = None,
    category: str = None,
    db: AsyncSession = Depends(get_db),
):
    try:
        uid = uuid.UUID(audit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid audit ID")

    result = await db.execute(select(AuditRun).where(AuditRun.id == uid))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Audit not found")

    query = select(Issue).where(Issue.audit_run_id == uid)
    if severity:
        query = query.where(Issue.severity == severity)
    if category:
        query = query.where(Issue.category == category)

    issues_result = await db.execute(query)
    issues = issues_result.scalars().all()
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    issues = sorted(issues, key=lambda i: severity_order.get(i.severity, 99))

    return templates.TemplateResponse(
        "partials/issues_table.html",
        {
            "request": request,
            "issues": issues,
            "run": run,
            "audit_id": audit_id,
            "filter_severity": severity,
            "filter_category": category,
        }
    )


@router.get("/audits/{audit_id}/vendors", response_class=HTMLResponse)
async def audit_vendors(request: Request, audit_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uid = uuid.UUID(audit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid audit ID")

    result = await db.execute(select(AuditRun).where(AuditRun.id == uid))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Audit not found")

    vendors_result = await db.execute(
        select(DetectedVendor)
        .where(DetectedVendor.audit_run_id == uid)
        .where(DetectedVendor.page_visit_id == None)
        .order_by(DetectedVendor.category, DetectedVendor.vendor_name)
    )
    vendors = vendors_result.scalars().all()

    return templates.TemplateResponse(
        "partials/vendors_table.html",
        {"request": request, "vendors": vendors, "run": run, "audit_id": audit_id}
    )


@router.get("/audits/{audit_id}/exports", response_class=HTMLResponse)
async def audit_exports(request: Request, audit_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uid = uuid.UUID(audit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid audit ID")

    result = await db.execute(select(AuditRun).where(AuditRun.id == uid))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Audit not found")

    artifacts_result = await db.execute(
        select(Artifact)
        .where(Artifact.audit_run_id == uid)
        .order_by(Artifact.created_at)
    )
    artifacts = artifacts_result.scalars().all()

    return templates.TemplateResponse(
        "partials/exports_panel.html",
        {"request": request, "artifacts": artifacts, "run": run, "audit_id": audit_id}
    )


@router.get("/audits/{audit_id}/comparison", response_class=HTMLResponse)
async def audit_comparison(request: Request, audit_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uid = uuid.UUID(audit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid audit ID")

    result = await db.execute(select(AuditRun).where(AuditRun.id == uid))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Audit not found")

    comparison_result = await db.execute(
        select(AuditComparison)
        .where(
            (AuditComparison.base_audit_id == uid) | (AuditComparison.compare_audit_id == uid)
        )
        .order_by(AuditComparison.created_at.desc())
    )
    comparison = comparison_result.scalars().first()

    completed_result = await db.execute(
        select(AuditRun)
        .where(AuditRun.status == AuditStatus.completed)
        .where(AuditRun.id != uid)
        .order_by(desc(AuditRun.created_at))
        .limit(20)
    )
    other_runs = completed_result.scalars().all()

    return templates.TemplateResponse(
        "audit_comparison.html",
        {
            "request": request,
            "run": run,
            "audit_id": audit_id,
            "comparison": comparison,
            "other_runs": other_runs,
        }
    )


@router.get("/audits/{audit_id}/issue/{issue_id}", response_class=HTMLResponse)
async def issue_detail(
    request: Request,
    audit_id: str,
    issue_id: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        audit_uid = uuid.UUID(audit_id)
        issue_uid = uuid.UUID(issue_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID")

    result = await db.execute(select(AuditRun).where(AuditRun.id == audit_uid))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Audit not found")

    issue_result = await db.execute(
        select(Issue)
        .where(Issue.id == issue_uid)
        .where(Issue.audit_run_id == audit_uid)
    )
    issue = issue_result.scalar_one_or_none()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    page_visit = None
    if issue.page_visit_id:
        pv_result = await db.execute(
            select(PageVisit).where(PageVisit.id == issue.page_visit_id)
        )
        page_visit = pv_result.scalar_one_or_none()

    return templates.TemplateResponse(
        "issue_detail.html",
        {
            "request": request,
            "run": run,
            "issue": issue,
            "page_visit": page_visit,
            "audit_id": audit_id,
        }
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: AsyncSession = Depends(get_db)):
    import os
    env_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

    if env_key:
        key_set = True
        key_masked = f"sk-ant-...{env_key[-4:]}"
        key_source = "env"
    else:
        result = await db.execute(
            select(AppSetting).where(AppSetting.key == "anthropic_api_key")
        )
        setting = result.scalar_one_or_none()
        if setting and setting.value:
            key_set = True
            key_masked = f"sk-ant-...{setting.value[-4:]}"
            key_source = "database"
        else:
            key_set = False
            key_masked = None
            key_source = "none"

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "key_set": key_set,
            "key_masked": key_masked,
            "key_source": key_source,
        },
    )


@router.get("/partials/audit-progress/{audit_id}", response_class=HTMLResponse)
async def partial_audit_progress(
    request: Request, audit_id: str, db: AsyncSession = Depends(get_db)
):
    try:
        uid = uuid.UUID(audit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid audit ID")

    result = await db.execute(select(AuditRun).where(AuditRun.id == uid))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Audit not found")

    issue_counts_result = await db.execute(
        select(Issue.severity, func.count(Issue.id))
        .where(Issue.audit_run_id == uid)
        .group_by(Issue.severity)
    )
    issue_counts = {row[0]: row[1] for row in issue_counts_result}

    # Use audit-level (deduplicated) count if available, otherwise count distinct
    # page-level detections so the number is live during crawling.
    audit_level_result = await db.execute(
        select(func.count(DetectedVendor.id))
        .where(DetectedVendor.audit_run_id == uid)
        .where(DetectedVendor.page_visit_id == None)
    )
    audit_level_count = audit_level_result.scalar()

    if audit_level_count:
        vendor_count = audit_level_count
    else:
        # Fall back to distinct vendor keys seen at page level
        page_level_result = await db.execute(
            select(func.count(DetectedVendor.vendor_key.distinct()))
            .where(DetectedVendor.audit_run_id == uid)
            .where(DetectedVendor.page_visit_id != None)
        )
        vendor_count = page_level_result.scalar() or 0

    return templates.TemplateResponse(
        "partials/audit_progress.html",
        {
            "request": request,
            "run": run,
            "audit_id": audit_id,
            "issue_counts": issue_counts,
            "vendor_count": vendor_count,
        }
    )


@router.get("/partials/audit-summary/{audit_id}", response_class=HTMLResponse)
async def partial_audit_summary(
    request: Request, audit_id: str, db: AsyncSession = Depends(get_db)
):
    try:
        uid = uuid.UUID(audit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid audit ID")

    result = await db.execute(select(AuditRun).where(AuditRun.id == uid))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Audit not found")

    # Issue counts (for severity cards)
    issue_counts_result = await db.execute(
        select(Issue.severity, func.count(Issue.id))
        .where(Issue.audit_run_id == uid)
        .group_by(Issue.severity)
    )
    issue_counts = {row[0]: row[1] for row in issue_counts_result}

    # Top 5 issues (for the issues list)
    top_issues_result = await db.execute(
        select(Issue)
        .where(Issue.audit_run_id == uid)
        .order_by(Issue.severity)
        .limit(5)
    )
    top_issues = top_issues_result.scalars().all()

    # All issues (needed for executive metrics)
    all_issues_result = await db.execute(
        select(Issue).where(Issue.audit_run_id == uid)
    )
    all_issues = all_issues_result.scalars().all()

    # Audit-level vendors (page_visit_id IS NULL)
    vendors_result = await db.execute(
        select(DetectedVendor)
        .where(DetectedVendor.audit_run_id == uid)
        .where(DetectedVendor.page_visit_id == None)
    )
    vendors = vendors_result.scalars().all()

    # Page-level vendors (for performance stats vendor_id → key mapping)
    page_vendors_result = await db.execute(
        select(DetectedVendor)
        .where(DetectedVendor.audit_run_id == uid)
        .where(DetectedVendor.page_visit_id != None)
    )
    page_level_vendors = page_vendors_result.scalars().all()

    # Pages (for cookie register + tag attribution)
    pages_result = await db.execute(
        select(PageVisit).where(PageVisit.audit_run_id == uid)
    )
    pages = pages_result.scalars().all()

    # Network requests (for performance stats + tag attribution)
    requests_result = await db.execute(
        select(NetworkRequest).where(NetworkRequest.audit_run_id == uid)
    )
    all_requests = requests_result.scalars().all()

    # Audit config (for executive metrics consent_behavior)
    config = None
    if run.config_id:
        config_result = await db.execute(
            select(AuditConfig).where(AuditConfig.id == run.config_id)
        )
        config = config_result.scalar_one_or_none()

    # AI narrative summary
    ai_summary = None
    try:
        ai_artifact_result = await db.execute(
            select(Artifact)
            .where(Artifact.audit_run_id == uid)
            .where(Artifact.artifact_type == "report_md")
        )
        ai_artifacts = ai_artifact_result.scalars().all()
        for artifact in ai_artifacts:
            if artifact.file_path and "ai_summary" in artifact.file_path:
                if os.path.exists(artifact.file_path):
                    with open(artifact.file_path, "r") as f:
                        content = f.read()
                    lines = content.splitlines()
                    body_lines = [l for l in lines if not l.startswith("# ")]
                    md_text = "\n".join(body_lines).strip()
                    try:
                        from markdown_it import MarkdownIt
                        import re as _re
                        # Pre-process: convert • bullet lines into markdown list items
                        processed_lines = []
                        for line in md_text.splitlines():
                            stripped = line.strip()
                            if stripped.startswith("•"):
                                # Convert "• some text" → "- some text"
                                processed_lines.append("- " + stripped[1:].strip())
                            elif stripped.startswith("·"):
                                processed_lines.append("- " + stripped[1:].strip())
                            else:
                                processed_lines.append(line)
                        processed_md = "\n".join(processed_lines)
                        raw_html = MarkdownIt().render(processed_md)
                        # Post-process: split dense <p> paragraphs containing inline • bullets
                        def split_bullet_para(m):
                            inner = m.group(1)
                            if "•" not in inner and "·" not in inner:
                                return m.group(0)
                            parts = _re.split(r"\s*[•·]\s*", inner)
                            parts = [p.strip() for p in parts if p.strip()]
                            if len(parts) <= 1:
                                return m.group(0)
                            items = "".join(f"<li>{p}</li>" for p in parts)
                            return f"<ul>{items}</ul>"
                        ai_summary = _re.sub(r"<p>(.*?)</p>", split_bullet_para, raw_html, flags=_re.DOTALL)
                    except Exception:
                        ai_summary = md_text
                break
    except Exception as e:
        logger.warning(f"Could not load AI summary for {audit_id}: {e}")

    # Compute derived metrics (pure Python — no DB calls)
    cookie_register = []
    attributions = {}
    perf_stats = []
    executive = None
    try:
        from app.lib.report_metrics import (
            build_cookie_register, build_tag_attribution,
            build_performance_stats, compute_executive_metrics,
        )
        cookie_register = build_cookie_register(pages)
        attributions = build_tag_attribution(vendors, pages, all_requests)
        perf_stats = build_performance_stats(vendors, all_requests, page_level_vendors)
        executive = compute_executive_metrics(vendors, all_issues, config, pages)
    except Exception as e:
        logger.warning(f"Could not compute summary metrics for {audit_id}: {e}")

    return templates.TemplateResponse(
        "partials/audit_summary.html",
        {
            "request": request,
            "run": run,
            "audit_id": audit_id,
            "issue_counts": issue_counts,
            "top_issues": top_issues,
            "vendors": vendors,
            "ai_summary": ai_summary,
            "cookie_register": cookie_register,
            "attributions": attributions,
            "perf_stats": perf_stats,
            "executive": executive,
        }
    )
