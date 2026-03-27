from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List
from datetime import datetime
import uuid

from app.database import get_db
from app.models import AuditRun
from app.models.event import AuditEvent

router = APIRouter(prefix="/api/audits", tags=["events"])


@router.get("/{audit_id}/events")
async def get_audit_events(
    audit_id: str,
    since: Optional[str] = Query(None, description="ISO timestamp — only return events after this time"),
    limit: int = Query(200, le=500),
    db: AsyncSession = Depends(get_db),
):
    try:
        run_id = uuid.UUID(audit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid audit ID")

    # Verify audit exists
    result = await db.execute(select(AuditRun).where(AuditRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Audit not found")

    stmt = select(AuditEvent).where(AuditEvent.audit_run_id == run_id)

    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            stmt = stmt.where(AuditEvent.created_at > since_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid 'since' timestamp")

    stmt = stmt.order_by(AuditEvent.created_at.asc()).limit(limit)
    result = await db.execute(stmt)
    events = result.scalars().all()

    return {
        "events": [
            {
                "id": str(ev.id),
                "created_at": ev.created_at.isoformat(),
                "event_type": ev.event_type,
                "message": ev.message,
                "detail": ev.detail,
            }
            for ev in events
        ]
    }
