import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.database import Base


class Issue(Base):
    __tablename__ = "issues"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    audit_run_id = Column(UUID(as_uuid=True), ForeignKey("audit_runs.id"), nullable=False)
    page_visit_id = Column(UUID(as_uuid=True), ForeignKey("page_visits.id"), nullable=True)
    vendor_id = Column(UUID(as_uuid=True), ForeignKey("detected_vendors.id"), nullable=True)
    severity = Column(String, nullable=False)
    category = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    affected_url = Column(String, nullable=True)
    affected_vendor_key = Column(String, nullable=True)
    evidence_refs = Column(JSONB, nullable=False, default=list)
    likely_cause = Column(Text, nullable=True)
    recommendation = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    audit_run = relationship("AuditRun", back_populates="issues")
    page_visit = relationship("PageVisit", back_populates="issues")
    vendor = relationship("DetectedVendor", back_populates="issues")

    def __repr__(self):
        return f"<Issue id={self.id} severity={self.severity} title={self.title[:50]}>"
