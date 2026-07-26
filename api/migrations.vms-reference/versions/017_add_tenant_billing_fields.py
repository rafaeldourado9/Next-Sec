"""billing: add billing fields to tenants

Revision ID: 017
Revises: 016
Create Date: 2026-04-12 18:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '017'
down_revision: Union[str, None] = '016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tenants', sa.Column('billing_plan_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('tenants', sa.Column('subscription_status', sa.String(20), nullable=False, server_default='active'))
    op.add_column('tenants', sa.Column('subscription_started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('tenants', sa.Column('subscription_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('tenants', sa.Column('current_usage_cameras', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('tenants', sa.Column('current_usage_storage_bytes', sa.BigInteger(), nullable=False, server_default='0'))
    op.add_column('tenants', sa.Column('current_monthly_events', sa.Integer(), nullable=False, server_default='0'))

    op.create_foreign_key(
        'fk_tenants_billing_plan',
        'tenants', 'billing_plans',
        ['billing_plan_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint('fk_tenants_billing_plan', 'tenants', type_='foreignkey')
    op.drop_column('tenants', 'current_monthly_events')
    op.drop_column('tenants', 'current_usage_storage_bytes')
    op.drop_column('tenants', 'current_usage_cameras')
    op.drop_column('tenants', 'subscription_expires_at')
    op.drop_column('tenants', 'subscription_started_at')
    op.drop_column('tenants', 'subscription_status')
    op.drop_column('tenants', 'billing_plan_id')
