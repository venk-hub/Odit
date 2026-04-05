from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, HttpUrl
from typing import Optional, List
from datetime import datetime
import os
import uuid

from app.database import get_db
from app.models import AuditRun, AuditConfig, AuditStatus, AuditMode, Issue, DetectedVendor, PageVisit

router = APIRouter(prefix="/api/audits", tags=["audits"])


class AuditCreateRequest(BaseModel):
    base_url: str
    mode: str = "quick_scan"
    max_pages: int = 50
    max_depth: int = 3
    device_type: str = "desktop"
    consent_behavior: str = "no_interaction"
    expected_vendors: List[str] = []
    include_patterns: List[str] = []
    exclude_patterns: List[str] = []
    seed_urls: List[str] = []
    journey_instructions: List[str] = []
    allowed_domains: List[str] = []
    comparison_audit_id: Optional[str] = None
    auth_cookies: Optional[list] = None
    auth_storage_state: Optional[dict] = None


@router.post("")
async def create_audit(payload: AuditCreateRequest, db: AsyncSession = Depends(get_db)):
    from urllib.parse import urlparse
    parsed = urlparse(payload.base_url)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid base_url")

    allowed_domains = payload.allowed_domains or [parsed.netloc]

    config = AuditConfig(
        base_url=payload.base_url,
        mode=payload.mode,
        max_pages=payload.max_pages,
        max_depth=payload.max_depth,
        allowed_domains=allowed_domains,
        device_type=payload.device_type,
        consent_behavior=payload.consent_behavior,
        expected_vendors=payload.expected_vendors,
        include_patterns=payload.include_patterns,
        exclude_patterns=payload.exclude_patterns,
        seed_urls=payload.seed_urls,
        journey_instructions=payload.journey_instructions,
        auth_cookies=payload.auth_cookies or None,
        auth_storage_state=payload.auth_storage_state or None,
    )
    db.add(config)
    await db.flush()

    comparison_audit_id = None
    if payload.comparison_audit_id:
        try:
            comparison_audit_id = uuid.UUID(payload.comparison_audit_id)
        except ValueError:
            pass

    run = AuditRun(
        base_url=payload.base_url,
        mode=payload.mode,
        status=AuditStatus.pending,
        config_id=config.id,
        comparison_audit_id=comparison_audit_id,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    return {
        "id": str(run.id),
        "base_url": run.base_url,
        "mode": run.mode,
        "status": run.status,
        "created_at": run.created_at.isoformat(),
        "config_id": str(run.config_id),
    }


@router.get("")
async def list_audits(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * per_page
    result = await db.execute(
        select(AuditRun)
        .order_by(desc(AuditRun.created_at))
        .offset(offset)
        .limit(per_page)
    )
    runs = result.scalars().all()

    total_result = await db.execute(select(func.count(AuditRun.id)))
    total = total_result.scalar()

    items = []
    for run in runs:
        issue_counts = await db.execute(
            select(Issue.severity, func.count(Issue.id))
            .where(Issue.audit_run_id == run.id)
            .group_by(Issue.severity)
        )
        counts = {row[0]: row[1] for row in issue_counts}

        items.append({
            "id": str(run.id),
            "base_url": run.base_url,
            "mode": run.mode,
            "status": run.status,
            "created_at": run.created_at.isoformat(),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "pages_crawled": run.pages_crawled,
            "pages_discovered": run.pages_discovered,
            "issue_counts": counts,
        })

    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.get("/{audit_id}")
async def get_audit(audit_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uid = uuid.UUID(audit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid audit ID")

    result = await db.execute(
        select(AuditRun)
        .options(selectinload(AuditRun.config))
        .where(AuditRun.id == uid)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Audit not found")

    issue_counts = await db.execute(
        select(Issue.severity, func.count(Issue.id))
        .where(Issue.audit_run_id == run.id)
        .group_by(Issue.severity)
    )
    counts = {row[0]: row[1] for row in issue_counts}

    vendor_count_result = await db.execute(
        select(func.count(DetectedVendor.id))
        .where(DetectedVendor.audit_run_id == run.id)
        .where(DetectedVendor.page_visit_id == None)
    )
    vendor_count = vendor_count_result.scalar()

    config = run.config
    return {
        "id": str(run.id),
        "base_url": run.base_url,
        "mode": run.mode,
        "status": run.status,
        "created_at": run.created_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "error_message": run.error_message,
        "pages_discovered": run.pages_discovered,
        "pages_crawled": run.pages_crawled,
        "pages_failed": run.pages_failed,
        "issue_counts": counts,
        "vendor_count": vendor_count,
        "config": {
            "max_pages": config.max_pages,
            "max_depth": config.max_depth,
            "device_type": config.device_type,
            "consent_behavior": config.consent_behavior,
            "expected_vendors": config.expected_vendors,
            "include_patterns": config.include_patterns,
            "exclude_patterns": config.exclude_patterns,
        } if config else None,
    }


@router.get("/{audit_id}/progress")
async def get_audit_progress(audit_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uid = uuid.UUID(audit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid audit ID")

    result = await db.execute(select(AuditRun).where(AuditRun.id == uid))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Audit not found")

    issue_counts = await db.execute(
        select(Issue.severity, func.count(Issue.id))
        .where(Issue.audit_run_id == run.id)
        .group_by(Issue.severity)
    )
    counts = {row[0]: row[1] for row in issue_counts}

    vendor_count_result = await db.execute(
        select(func.count(DetectedVendor.id))
        .where(DetectedVendor.audit_run_id == run.id)
        .where(DetectedVendor.page_visit_id == None)
    )
    vendor_count = vendor_count_result.scalar()

    return {
        "status": run.status,
        "pages_discovered": run.pages_discovered,
        "pages_crawled": run.pages_crawled,
        "pages_failed": run.pages_failed,
        "vendor_count": vendor_count,
        "issue_counts": counts,
        "total_issues": sum(counts.values()),
        "error_message": run.error_message,
    }


@router.delete("/{audit_id}")
async def delete_audit(audit_id: str, db: AsyncSession = Depends(get_db)):
    import shutil, os
    try:
        uid = uuid.UUID(audit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid audit ID")

    result = await db.execute(select(AuditRun).where(AuditRun.id == uid))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Audit not found")

    # Delete file artifacts
    data_dir = os.environ.get("DATA_DIR", "/data")
    audit_dir = os.path.join(data_dir, "audits", str(uid))
    if os.path.isdir(audit_dir):
        shutil.rmtree(audit_dir, ignore_errors=True)

    # Delete DB record — cascades to all child tables
    await db.delete(run)
    await db.commit()
    return {"id": str(uid), "deleted": True}


@router.delete("/{audit_id}/cancel")
async def cancel_audit(audit_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uid = uuid.UUID(audit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid audit ID")

    result = await db.execute(select(AuditRun).where(AuditRun.id == uid))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Audit not found")

    if run.status not in (AuditStatus.pending, AuditStatus.running):
        raise HTTPException(status_code=400, detail=f"Cannot cancel audit with status {run.status}")

    run.status = AuditStatus.cancelled
    run.completed_at = datetime.utcnow()
    await db.commit()
    return {"id": str(run.id), "status": run.status}


@router.get("/{audit_id}/live-screenshot")
async def live_screenshot(audit_id: str):
    """Return the most recently written screenshot for a running audit."""
    try:
        uuid.UUID(audit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid audit ID")

    data_dir = os.environ.get("DATA_DIR", "/data")
    screenshots_dir = os.path.join(data_dir, "audits", audit_id, "screenshots")

    if not os.path.isdir(screenshots_dir):
        raise HTTPException(status_code=404, detail="No screenshots yet")

    pngs = [
        os.path.join(screenshots_dir, f)
        for f in os.listdir(screenshots_dir)
        if f.endswith(".png")
    ]
    if not pngs:
        raise HTTPException(status_code=404, detail="No screenshots yet")

    latest = max(pngs, key=os.path.getmtime)
    return FileResponse(latest, media_type="image/png", headers={"Cache-Control": "no-store"})
