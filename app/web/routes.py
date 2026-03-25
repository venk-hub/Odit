from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
import uuid
import os

from app.database import get_db
from app.models import AuditRun, Issue, DetectedVendor, PageVisit, Artifact, AuditComparison, AuditStatus
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

    return templates.TemplateResponse("dashboard.html", {"request": request, "audits": audits})


@router.get("/audits/new", response_class=HTMLResponse)
async def new_audit_form(request: Request, db: AsyncSession = Depends(get_db)):
    completed_result = await db.execute(
        select(AuditRun)
        .where(AuditRun.status == AuditStatus.completed)
        .order_by(desc(AuditRun.created_at))
        .limit(50)
    )
    completed_runs = completed_result.scalars().all()

    return templates.TemplateResponse(
        "new_audit.html",
        {"request": request, "completed_runs": completed_runs}
    )


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

    return templates.TemplateResponse(
        "audit_detail.html",
        {"request": request, "run": run, "audit_id": audit_id}
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

    vendor_count_result = await db.execute(
        select(func.count(DetectedVendor.id))
        .where(DetectedVendor.audit_run_id == uid)
        .where(DetectedVendor.page_visit_id == None)
    )
    vendor_count = vendor_count_result.scalar()

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

    issue_counts_result = await db.execute(
        select(Issue.severity, func.count(Issue.id))
        .where(Issue.audit_run_id == uid)
        .group_by(Issue.severity)
    )
    issue_counts = {row[0]: row[1] for row in issue_counts_result}

    top_issues_result = await db.execute(
        select(Issue)
        .where(Issue.audit_run_id == uid)
        .order_by(Issue.severity)
        .limit(5)
    )
    top_issues = top_issues_result.scalars().all()

    vendors_result = await db.execute(
        select(DetectedVendor)
        .where(DetectedVendor.audit_run_id == uid)
        .where(DetectedVendor.page_visit_id == None)
    )
    vendors = vendors_result.scalars().all()

    return templates.TemplateResponse(
        "partials/audit_summary.html",
        {
            "request": request,
            "run": run,
            "audit_id": audit_id,
            "issue_counts": issue_counts,
            "top_issues": top_issues,
            "vendors": vendors,
        }
    )
