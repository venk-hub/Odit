"""Add audit_events table for real-time activity feed

Revision ID: 006
Revises: 005
Create Date: 2026-03-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("audit_run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("detail", JSONB, nullable=True),
    )
    op.create_index("ix_audit_events_run_id", "audit_events", ["audit_run_id"])
    op.create_index("ix_audit_events_run_created", "audit_events", ["audit_run_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_run_created", "audit_events")
    op.drop_index("ix_audit_events_run_id", "audit_events")
    op.drop_table("audit_events")
