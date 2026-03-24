from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
import uuid

from app.database import get_db
from app.models import AuditRun, PageVisit, DetectedVendor, NetworkRequest

router = APIRouter(prefix="/api/audits", tags=["pages"])


@router.get("/{audit_id}/pages")
async def list_pages(
    audit_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
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

    offset = (page - 1) * per_page
    pages_result = await db.execute(
        select(PageVisit)
        .where(PageVisit.audit_run_id == uid)
        .order_by(desc(PageVisit.crawled_at))
        .offset(offset)
        .limit(per_page)
    )
    pages = pages_result.scalars().all()

    total_result = await db.execute(
        select(func.count(PageVisit.id)).where(PageVisit.audit_run_id == uid)
    )
    total = total_result.scalar()

    items = []
    for pv in pages:
        vendor_count_result = await db.execute(
            select(func.count(DetectedVendor.id))
            .where(DetectedVendor.page_visit_id == pv.id)
        )
        vendor_count = vendor_count_result.scalar()

        items.append({
            "id": str(pv.id),
            "url": pv.url,
            "final_url": pv.final_url,
            "status_code": pv.status_code,
            "page_title": pv.page_title,
            "page_group": pv.page_group,
            "load_time_ms": pv.load_time_ms,
            "console_error_count": pv.console_error_count,
            "failed_request_count": pv.failed_request_count,
            "screenshot_path": pv.screenshot_path,
            "vendor_count": vendor_count,
            "crawled_at": pv.crawled_at.isoformat() if pv.crawled_at else None,
            "error_message": pv.error_message,
        })

    return {"items": items, "total": total, "page": page, "per_page": per_page}
