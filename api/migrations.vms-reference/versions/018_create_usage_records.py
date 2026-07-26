"""billing: create usage_records table

Revision ID: 018
Revises: 017b
Create Date: 2026-04-12 19:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '018'
down_revision: Union[str, None] = '017b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'usage_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('metric_name', sa.String(50), nullable=False),
        sa.Column('value', sa.Numeric(15, 4), nullable=False),
        sa.Column('unit', sa.String(20), nullable=True),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('period_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Index('ix_usage_records_tenant_metric', 'tenant_id', 'metric_name'),
        sa.Index('ix_usage_records_period', 'period_start', 'period_end'),
    )


def downgrade() -> None:
    op.drop_table('usage_records')
