"""Add post_data, cookies_detail, data_layer for richer evidence capture

Revision ID: 005
Revises: 004
Create Date: 2026-03-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("network_requests", sa.Column("post_data", sa.Text, nullable=True))
    op.add_column("page_visits", sa.Column("cookies_detail", JSONB, nullable=True))
    op.add_column("page_visits", sa.Column("data_layer", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("network_requests", "post_data")
    op.drop_column("page_visits", "cookies_detail")
    op.drop_column("page_visits", "data_layer")
