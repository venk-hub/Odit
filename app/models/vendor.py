import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.database import Base


class DetectedVendor(Base):
    __tablename__ = "detected_vendors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    audit_run_id = Column(UUID(as_uuid=True), ForeignKey("audit_runs.id"), nullable=False)
    page_visit_id = Column(UUID(as_uuid=True), ForeignKey("page_visits.id"), nullable=True)
    vendor_key = Column(String, nullable=False)
    vendor_name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    detection_method = Column(String, nullable=False)
    evidence = Column(JSONB, nullable=False, default=dict)
    page_count = Column(Integer, nullable=False, default=1)
    detected_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    audit_run = relationship("AuditRun", back_populates="detected_vendors")
    page_visit = relationship("PageVisit", back_populates="detected_vendors")
    issues = relationship("Issue", back_populates="vendor")

    def __repr__(self):
        return f"<DetectedVendor id={self.id} vendor_key={self.vendor_key} category={self.category}>"
