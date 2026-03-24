import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.database import Base


class AuditComparison(Base):
    __tablename__ = "audit_comparisons"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    base_audit_id = Column(UUID(as_uuid=True), ForeignKey("audit_runs.id"), nullable=False)
    compare_audit_id = Column(UUID(as_uuid=True), ForeignKey("audit_runs.id"), nullable=False)
    new_issues = Column(JSONB, nullable=False, default=list)
    resolved_issues = Column(JSONB, nullable=False, default=list)
    vendor_changes = Column(JSONB, nullable=False, default=dict)
    page_count_change = Column(Integer, nullable=False, default=0)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    base_audit = relationship("AuditRun", foreign_keys=[base_audit_id])
    compare_audit = relationship("AuditRun", foreign_keys=[compare_audit_id])

    def __repr__(self):
        return f"<AuditComparison id={self.id} base={self.base_audit_id} compare={self.compare_audit_id}>"
