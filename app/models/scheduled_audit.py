import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base


class ScheduledAudit(Base):
    __tablename__ = "scheduled_audits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url = Column(String, nullable=False)
    mode = Column(String, nullable=False, default="quick_scan")
    max_pages = Column(Integer, nullable=False, default=50)
    frequency = Column(String, nullable=False)  # "daily" | "weekly" | "monthly"
    label = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    next_run_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    auth_cookies = Column(JSONB, nullable=True)

    def __repr__(self):
        return f"<ScheduledAudit id={self.id} url={self.url} frequency={self.frequency}>"
