from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid

from app.database import get_db
from app.models import AuditRun, DetectedVendor

router = APIRouter(prefix="/api/audits", tags=["vendors"])


@router.get("/{audit_id}/vendors")
async def list_vendors(audit_id: str, db: AsyncSession = Depends(get_db)):
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

    return {
        "items": [
            {
                "id": str(v.id),
                "vendor_key": v.vendor_key,
                "vendor_name": v.vendor_name,
                "category": v.category,
                "detection_method": v.detection_method,
                "evidence": v.evidence,
                "page_count": v.page_count,
                "detected_at": v.detected_at.isoformat(),
            }
            for v in vendors
        ]
    }
