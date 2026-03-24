import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.database import Base
import enum


class AuditMode(str, enum.Enum):
    quick_scan = "quick_scan"
    full_crawl = "full_crawl"
    journey_audit = "journey_audit"
    regression_compare = "regression_compare"


class AuditStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class DeviceType(str, enum.Enum):
    desktop = "desktop"
    mobile = "mobile"
    both = "both"


class ConsentBehavior(str, enum.Enum):
    no_interaction = "no_interaction"
    accept_consent = "accept_consent"


class AuditConfig(Base):
    __tablename__ = "audit_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    base_url = Column(String, nullable=False)
    mode = Column(SAEnum(AuditMode), nullable=False, default=AuditMode.quick_scan)
    max_pages = Column(Integer, nullable=False, default=50)
    max_depth = Column(Integer, nullable=False, default=3)
    allowed_domains = Column(JSONB, nullable=False, default=list)
    device_type = Column(SAEnum(DeviceType), nullable=False, default=DeviceType.desktop)
    consent_behavior = Column(SAEnum(ConsentBehavior), nullable=False, default=ConsentBehavior.no_interaction)
    expected_vendors = Column(JSONB, nullable=False, default=list)
    include_patterns = Column(JSONB, nullable=False, default=list)
    exclude_patterns = Column(JSONB, nullable=False, default=list)
    seed_urls = Column(JSONB, nullable=False, default=list)
    journey_instructions = Column(JSONB, nullable=False, default=list)  # NL steps for journey mode
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    audit_runs = relationship("AuditRun", back_populates="config")

    def __repr__(self):
        return f"<AuditConfig id={self.id} base_url={self.base_url} mode={self.mode}>"


class AuditRun(Base):
    __tablename__ = "audit_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    base_url = Column(String, nullable=False)
    mode = Column(SAEnum(AuditMode), nullable=False)
    status = Column(SAEnum(AuditStatus), nullable=False, default=AuditStatus.pending)
    config_id = Column(UUID(as_uuid=True), ForeignKey("audit_configs.id"), nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    error_message = Column(Text, nullable=True)
    pages_discovered = Column(Integer, nullable=False, default=0)
    pages_crawled = Column(Integer, nullable=False, default=0)
    pages_failed = Column(Integer, nullable=False, default=0)
    comparison_audit_id = Column(UUID(as_uuid=True), ForeignKey("audit_runs.id"), nullable=True)

    config = relationship("AuditConfig", back_populates="audit_runs")
    page_visits = relationship("PageVisit", back_populates="audit_run", cascade="all, delete-orphan")
    network_requests = relationship("NetworkRequest", back_populates="audit_run", cascade="all, delete-orphan")
    console_events = relationship("ConsoleEvent", back_populates="audit_run", cascade="all, delete-orphan")
    detected_vendors = relationship("DetectedVendor", back_populates="audit_run", cascade="all, delete-orphan")
    issues = relationship("Issue", back_populates="audit_run", cascade="all, delete-orphan")
    artifacts = relationship("Artifact", back_populates="audit_run", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<AuditRun id={self.id} base_url={self.base_url} status={self.status}>"
