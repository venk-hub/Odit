"""Add scheduled_audits table

Revision ID: 008
Revises: 007
Create Date: 2026-04-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'scheduled_audits',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column('url', sa.String(), nullable=False),
        sa.Column('mode', sa.String(), nullable=False, server_default='quick_scan'),
        sa.Column('max_pages', sa.Integer(), nullable=False, server_default='50'),
        sa.Column('frequency', sa.String(), nullable=False),
        sa.Column('label', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('next_run_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('auth_cookies', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade():
    op.drop_table('scheduled_audits')
