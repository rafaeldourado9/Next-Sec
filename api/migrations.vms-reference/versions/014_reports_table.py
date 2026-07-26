"""reports: create reports table

Revision ID: 014
Revises: 013
Create Date: 2026-04-12 16:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '014'
down_revision: Union[str, None] = '013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'reports',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('report_type', sa.String(50), nullable=False),
        sa.Column('parameters', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('file_path', sa.String(1000), nullable=True),
        sa.Column('sha256_hash', sa.String(64), nullable=True),
        sa.Column('scheduled_for', sa.DateTime(timezone=True), nullable=True),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_reports_tenant_created', 'reports', ['tenant_id', 'created_at'])
    op.create_index('ix_reports_status', 'reports', ['status'])


def downgrade() -> None:
    op.drop_table('reports')
