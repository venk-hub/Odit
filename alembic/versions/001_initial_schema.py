"""Initial schema

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # audit_configs
    op.create_table(
        "audit_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("base_url", sa.String(), nullable=False),
        sa.Column("mode", sa.Enum("quick_scan", "full_crawl", "journey_audit", "regression_compare", name="auditmode"), nullable=False),
        sa.Column("max_pages", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("max_depth", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("allowed_domains", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("device_type", sa.Enum("desktop", "mobile", "both", name="devicetype"), nullable=False),
        sa.Column("consent_behavior", sa.Enum("no_interaction", "accept_consent", name="consentbehavior"), nullable=False),
        sa.Column("expected_vendors", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("include_patterns", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("exclude_patterns", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("seed_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # audit_runs
    op.create_table(
        "audit_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("base_url", sa.String(), nullable=False),
        sa.Column("mode", sa.Enum("quick_scan", "full_crawl", "journey_audit", "regression_compare", name="auditmode"), nullable=False),
        sa.Column("status", sa.Enum("pending", "running", "completed", "failed", "cancelled", name="auditstatus"), nullable=False),
        sa.Column("config_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("pages_discovered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_crawled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("comparison_audit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["config_id"], ["audit_configs.id"]),
        sa.ForeignKeyConstraint(["comparison_audit_id"], ["audit_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_runs_status", "audit_runs", ["status"])
    op.create_index("ix_audit_runs_created_at", "audit_runs", ["created_at"])

    # page_visits
    op.create_table(
        "page_visits",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("audit_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("final_url", sa.String(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("page_title", sa.String(), nullable=True),
        sa.Column("meta_description", sa.Text(), nullable=True),
        sa.Column("canonical_url", sa.String(), nullable=True),
        sa.Column("page_group", sa.String(), nullable=True),
        sa.Column("load_time_ms", sa.Float(), nullable=True),
        sa.Column("screenshot_path", sa.String(), nullable=True),
        sa.Column("har_path", sa.String(), nullable=True),
        sa.Column("console_error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cookies", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("local_storage_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("session_storage_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("script_srcs", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("redirect_chain", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("crawled_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["audit_run_id"], ["audit_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_page_visits_audit_run_id", "page_visits", ["audit_run_id"])

    # detected_vendors (created before network_requests due to FK)
    op.create_table(
        "detected_vendors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("audit_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_visit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("vendor_key", sa.String(), nullable=False),
        sa.Column("vendor_name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("detection_method", sa.String(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["audit_run_id"], ["audit_runs.id"]),
        sa.ForeignKeyConstraint(["page_visit_id"], ["page_visits.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_detected_vendors_audit_run_id", "detected_vendors", ["audit_run_id"])

    # network_requests
    op.create_table(
        "network_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_visit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("audit_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=False, server_default="GET"),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("resource_type", sa.String(), nullable=True),
        sa.Column("request_headers", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("response_headers", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("timing_ms", sa.Float(), nullable=True),
        sa.Column("failed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("failure_reason", sa.String(), nullable=True),
        sa.Column("is_tracking_related", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["page_visit_id"], ["page_visits.id"]),
        sa.ForeignKeyConstraint(["audit_run_id"], ["audit_runs.id"]),
        sa.ForeignKeyConstraint(["vendor_id"], ["detected_vendors.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_network_requests_audit_run_id", "network_requests", ["audit_run_id"])
    op.create_index("ix_network_requests_page_visit_id", "network_requests", ["page_visit_id"])

    # console_events
    op.create_table(
        "console_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_visit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("audit_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("level", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("line_number", sa.Integer(), nullable=True),
        sa.Column("column_number", sa.Integer(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["page_visit_id"], ["page_visits.id"]),
        sa.ForeignKeyConstraint(["audit_run_id"], ["audit_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_console_events_audit_run_id", "console_events", ["audit_run_id"])

    # issues
    op.create_table(
        "issues",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("audit_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_visit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("affected_url", sa.String(), nullable=True),
        sa.Column("affected_vendor_key", sa.String(), nullable=True),
        sa.Column("evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("likely_cause", sa.Text(), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["audit_run_id"], ["audit_runs.id"]),
        sa.ForeignKeyConstraint(["page_visit_id"], ["page_visits.id"]),
        sa.ForeignKeyConstraint(["vendor_id"], ["detected_vendors.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_issues_audit_run_id", "issues", ["audit_run_id"])
    op.create_index("ix_issues_severity", "issues", ["severity"])

    # artifacts
    op.create_table(
        "artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("audit_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_type", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["audit_run_id"], ["audit_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # audit_comparisons
    op.create_table(
        "audit_comparisons",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("base_audit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("compare_audit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("new_issues", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("resolved_issues", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("vendor_changes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("page_count_change", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["base_audit_id"], ["audit_runs.id"]),
        sa.ForeignKeyConstraint(["compare_audit_id"], ["audit_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("audit_comparisons")
    op.drop_table("artifacts")
    op.drop_index("ix_issues_severity", table_name="issues")
    op.drop_index("ix_issues_audit_run_id", table_name="issues")
    op.drop_table("issues")
    op.drop_index("ix_console_events_audit_run_id", table_name="console_events")
    op.drop_table("console_events")
    op.drop_index("ix_network_requests_page_visit_id", table_name="network_requests")
    op.drop_index("ix_network_requests_audit_run_id", table_name="network_requests")
    op.drop_table("network_requests")
    op.drop_index("ix_detected_vendors_audit_run_id", table_name="detected_vendors")
    op.drop_table("detected_vendors")
    op.drop_index("ix_page_visits_audit_run_id", table_name="page_visits")
    op.drop_table("page_visits")
    op.drop_index("ix_audit_runs_created_at", table_name="audit_runs")
    op.drop_index("ix_audit_runs_status", table_name="audit_runs")
    op.drop_table("audit_runs")
    op.drop_table("audit_configs")
    op.execute("DROP TYPE IF EXISTS auditmode")
    op.execute("DROP TYPE IF EXISTS auditstatus")
    op.execute("DROP TYPE IF EXISTS devicetype")
    op.execute("DROP TYPE IF EXISTS consentbehavior")
