"""Add journey_instructions to audit_configs

Revision ID: 002
Revises: 001
Create Date: 2026-03-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_configs",
        sa.Column("journey_instructions", JSONB, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("audit_configs", "journey_instructions")
