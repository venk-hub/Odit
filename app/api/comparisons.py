from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
import uuid

from app.database import get_db
from app.models import AuditRun, AuditComparison, Issue, DetectedVendor, AuditStatus

router = APIRouter(prefix="/api/audits", tags=["comparisons"])


class CompareRequest(BaseModel):
    compare_audit_id: str


@router.post("/{audit_id}/compare")
async def create_comparison(
    audit_id: str,
    payload: CompareRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        base_uid = uuid.UUID(audit_id)
        compare_uid = uuid.UUID(payload.compare_audit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid audit ID")

    base_result = await db.execute(select(AuditRun).where(AuditRun.id == base_uid))
    base_run = base_result.scalar_one_or_none()
    if not base_run:
        raise HTTPException(status_code=404, detail="Base audit not found")

    compare_result = await db.execute(select(AuditRun).where(AuditRun.id == compare_uid))
    compare_run = compare_result.scalar_one_or_none()
    if not compare_run:
        raise HTTPException(status_code=404, detail="Compare audit not found")

    if base_run.status != AuditStatus.completed or compare_run.status != AuditStatus.completed:
        raise HTTPException(status_code=400, detail="Both audits must be completed")

    # Fetch issues for both audits
    base_issues_result = await db.execute(
        select(Issue).where(Issue.audit_run_id == base_uid)
    )
    base_issues = {i.title: i for i in base_issues_result.scalars().all()}

    compare_issues_result = await db.execute(
        select(Issue).where(Issue.audit_run_id == compare_uid)
    )
    compare_issues = {i.title: i for i in compare_issues_result.scalars().all()}

    new_issue_titles = set(compare_issues.keys()) - set(base_issues.keys())
    resolved_issue_titles = set(base_issues.keys()) - set(compare_issues.keys())

    new_issues = [
        {"title": t, "severity": compare_issues[t].severity, "category": compare_issues[t].category}
        for t in new_issue_titles
    ]
    resolved_issues = [
        {"title": t, "severity": base_issues[t].severity, "category": base_issues[t].category}
        for t in resolved_issue_titles
    ]

    # Vendor changes
    base_vendors_result = await db.execute(
        select(DetectedVendor)
        .where(DetectedVendor.audit_run_id == base_uid)
        .where(DetectedVendor.page_visit_id == None)
    )
    base_vendor_keys = {v.vendor_key for v in base_vendors_result.scalars().all()}

    compare_vendors_result = await db.execute(
        select(DetectedVendor)
        .where(DetectedVendor.audit_run_id == compare_uid)
        .where(DetectedVendor.page_visit_id == None)
    )
    compare_vendor_keys = {v.vendor_key for v in compare_vendors_result.scalars().all()}

    vendor_changes = {
        "added": list(compare_vendor_keys - base_vendor_keys),
        "removed": list(base_vendor_keys - compare_vendor_keys),
        "unchanged": list(base_vendor_keys & compare_vendor_keys),
    }

    page_count_change = compare_run.pages_crawled - base_run.pages_crawled

    summary_parts = [
        f"Comparing audit {str(base_uid)[:8]} (base) vs {str(compare_uid)[:8]} (compare).",
        f"New issues: {len(new_issues)}, Resolved issues: {len(resolved_issues)}.",
        f"Vendors added: {len(vendor_changes['added'])}, removed: {len(vendor_changes['removed'])}.",
        f"Page count change: {page_count_change:+d}.",
    ]
    summary = " ".join(summary_parts)

    # Remove existing comparison if any
    existing = await db.execute(
        select(AuditComparison)
        .where(AuditComparison.base_audit_id == base_uid)
        .where(AuditComparison.compare_audit_id == compare_uid)
    )
    existing_cmp = existing.scalar_one_or_none()
    if existing_cmp:
        await db.delete(existing_cmp)
        await db.flush()

    comparison = AuditComparison(
        base_audit_id=base_uid,
        compare_audit_id=compare_uid,
        new_issues=new_issues,
        resolved_issues=resolved_issues,
        vendor_changes=vendor_changes,
        page_count_change=page_count_change,
        summary=summary,
    )
    db.add(comparison)
    await db.commit()
    await db.refresh(comparison)

    return {
        "id": str(comparison.id),
        "summary": comparison.summary,
        "new_issues": comparison.new_issues,
        "resolved_issues": comparison.resolved_issues,
        "vendor_changes": comparison.vendor_changes,
        "page_count_change": comparison.page_count_change,
    }


@router.get("/{audit_id}/comparison")
async def get_comparison(audit_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uid = uuid.UUID(audit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid audit ID")

    result = await db.execute(
        select(AuditComparison)
        .where(
            (AuditComparison.base_audit_id == uid) | (AuditComparison.compare_audit_id == uid)
        )
        .order_by(AuditComparison.created_at.desc())
    )
    comparison = result.scalars().first()

    if not comparison:
        raise HTTPException(status_code=404, detail="No comparison found for this audit")

    return {
        "id": str(comparison.id),
        "base_audit_id": str(comparison.base_audit_id),
        "compare_audit_id": str(comparison.compare_audit_id),
        "summary": comparison.summary,
        "new_issues": comparison.new_issues,
        "resolved_issues": comparison.resolved_issues,
        "vendor_changes": comparison.vendor_changes,
        "page_count_change": comparison.page_count_change,
        "created_at": comparison.created_at.isoformat(),
    }
