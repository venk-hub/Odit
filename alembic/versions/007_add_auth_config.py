"""Add auth_cookies and auth_storage_state to audit_configs

Revision ID: 007
Revises: 006
Create Date: 2026-03-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("audit_configs", sa.Column("auth_cookies", JSONB(), nullable=True))
    op.add_column("audit_configs", sa.Column("auth_storage_state", JSONB(), nullable=True))


def downgrade():
    op.drop_column("audit_configs", "auth_storage_state")
    op.drop_column("audit_configs", "auth_cookies")
