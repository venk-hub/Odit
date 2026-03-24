import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, Boolean, Float
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.database import Base


class PageVisit(Base):
    __tablename__ = "page_visits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    audit_run_id = Column(UUID(as_uuid=True), ForeignKey("audit_runs.id"), nullable=False)
    url = Column(String, nullable=False)
    final_url = Column(String, nullable=True)
    status_code = Column(Integer, nullable=True)
    page_title = Column(String, nullable=True)
    meta_description = Column(Text, nullable=True)
    canonical_url = Column(String, nullable=True)
    page_group = Column(String, nullable=True)
    load_time_ms = Column(Float, nullable=True)
    screenshot_path = Column(String, nullable=True)
    har_path = Column(String, nullable=True)
    console_error_count = Column(Integer, nullable=False, default=0)
    failed_request_count = Column(Integer, nullable=False, default=0)
    cookies = Column(JSONB, nullable=False, default=list)
    local_storage_keys = Column(JSONB, nullable=False, default=list)
    session_storage_keys = Column(JSONB, nullable=False, default=list)
    script_srcs = Column(JSONB, nullable=False, default=list)
    redirect_chain = Column(JSONB, nullable=False, default=list)
    crawled_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    audit_run = relationship("AuditRun", back_populates="page_visits")
    network_requests = relationship("NetworkRequest", back_populates="page_visit", cascade="all, delete-orphan")
    console_events = relationship("ConsoleEvent", back_populates="page_visit", cascade="all, delete-orphan")
    detected_vendors = relationship("DetectedVendor", back_populates="page_visit")
    issues = relationship("Issue", back_populates="page_visit")

    def __repr__(self):
        return f"<PageVisit id={self.id} url={self.url} status_code={self.status_code}>"


class NetworkRequest(Base):
    __tablename__ = "network_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    page_visit_id = Column(UUID(as_uuid=True), ForeignKey("page_visits.id"), nullable=False)
    audit_run_id = Column(UUID(as_uuid=True), ForeignKey("audit_runs.id"), nullable=False)
    url = Column(String, nullable=False)
    method = Column(String, nullable=False, default="GET")
    status_code = Column(Integer, nullable=True)
    resource_type = Column(String, nullable=True)
    request_headers = Column(JSONB, nullable=False, default=dict)
    response_headers = Column(JSONB, nullable=False, default=dict)
    timing_ms = Column(Float, nullable=True)
    failed = Column(Boolean, nullable=False, default=False)
    failure_reason = Column(String, nullable=True)
    is_tracking_related = Column(Boolean, nullable=False, default=False)
    vendor_id = Column(UUID(as_uuid=True), ForeignKey("detected_vendors.id"), nullable=True)
    captured_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    page_visit = relationship("PageVisit", back_populates="network_requests")
    audit_run = relationship("AuditRun", back_populates="network_requests")

    def __repr__(self):
        return f"<NetworkRequest id={self.id} url={self.url} status_code={self.status_code} failed={self.failed}>"


class ConsoleEvent(Base):
    __tablename__ = "console_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    page_visit_id = Column(UUID(as_uuid=True), ForeignKey("page_visits.id"), nullable=False)
    audit_run_id = Column(UUID(as_uuid=True), ForeignKey("audit_runs.id"), nullable=False)
    level = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    source_url = Column(String, nullable=True)
    line_number = Column(Integer, nullable=True)
    column_number = Column(Integer, nullable=True)
    captured_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    page_visit = relationship("PageVisit", back_populates="console_events")
    audit_run = relationship("AuditRun", back_populates="console_events")

    def __repr__(self):
        return f"<ConsoleEvent id={self.id} level={self.level} message={self.message[:50]}>"
