"""Add remediation_steps to issues

Revision ID: 004
Revises: 003
Create Date: 2026-03-25
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("issues", sa.Column("remediation_steps", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("issues", "remediation_steps")
