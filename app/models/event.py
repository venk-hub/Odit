import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    audit_run_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    event_type = Column(String(64), nullable=False)
    message = Column(String(500), nullable=False)
    detail = Column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_audit_events_run_created", "audit_run_id", "created_at"),
    )

    def __repr__(self):
        return f"<AuditEvent {self.event_type}: {self.message[:60]}>"
