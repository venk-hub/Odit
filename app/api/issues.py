from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
import uuid

from app.database import get_db
from app.models import AuditRun, Issue

router = APIRouter(prefix="/api/audits", tags=["issues"])

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@router.get("/{audit_id}/issues")
async def list_issues(
    audit_id: str,
    severity: str = Query(None),
    category: str = Query(None),
    vendor_key: str = Query(None),
    search: str = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
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

    conditions = [Issue.audit_run_id == uid]
    if severity:
        conditions.append(Issue.severity == severity)
    if category:
        conditions.append(Issue.category == category)
    if vendor_key:
        conditions.append(Issue.affected_vendor_key == vendor_key)
    if search:
        conditions.append(
            Issue.title.ilike(f"%{search}%") | Issue.description.ilike(f"%{search}%")
        )

    offset = (page - 1) * per_page
    issues_result = await db.execute(
        select(Issue)
        .where(and_(*conditions))
        .offset(offset)
        .limit(per_page)
    )
    issues = issues_result.scalars().all()

    total_result = await db.execute(
        select(func.count(Issue.id)).where(and_(*conditions))
    )
    total = total_result.scalar()

    items = [
        {
            "id": str(issue.id),
            "severity": issue.severity,
            "category": issue.category,
            "title": issue.title,
            "description": issue.description,
            "affected_url": issue.affected_url,
            "affected_vendor_key": issue.affected_vendor_key,
            "likely_cause": issue.likely_cause,
            "recommendation": issue.recommendation,
            "evidence_refs": issue.evidence_refs,
            "page_visit_id": str(issue.page_visit_id) if issue.page_visit_id else None,
            "created_at": issue.created_at.isoformat(),
        }
        for issue in sorted(issues, key=lambda i: SEVERITY_ORDER.get(i.severity, 99))
    ]

    return {"items": items, "total": total, "page": page, "per_page": per_page}
