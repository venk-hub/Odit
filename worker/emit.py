"""
Thin helper for writing AuditEvent rows from the worker.
Calls db.flush() so events are visible within the current transaction;
callers are responsible for committing when appropriate.
"""
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("odit.worker.emit")


def emit(db, audit_run_id, event_type: str, message: str, detail: Optional[dict] = None) -> None:
    """Write an AuditEvent row. Safe to call anywhere in the worker."""
    try:
        from app.models.event import AuditEvent
        ev = AuditEvent(
            audit_run_id=audit_run_id,
            created_at=datetime.utcnow(),
            event_type=event_type,
            message=message[:500],
            detail=detail,
        )
        db.add(ev)
        db.flush()
    except Exception as e:
        logger.debug(f"emit_event failed (non-fatal): {e}")
