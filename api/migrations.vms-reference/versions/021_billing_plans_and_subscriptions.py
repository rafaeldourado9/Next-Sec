"""billing: add billing_plans, tenant_subscriptions, tenant.onboarding_complete

Revision ID: 021
Revises: 020
Create Date: 2026-04-13 20:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '021'
down_revision: Union[str, None] = '020'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. billing_plans
    op.create_table(
        'billing_plans',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('slug', sa.String(50), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('price_monthly', sa.Numeric(10, 2), nullable=False, server_default=sa.text("0")),
        sa.Column('max_cameras', sa.Integer(), nullable=True),
        sa.Column('max_storage_gb', sa.Integer(), nullable=True),
        sa.Column('max_ai_cameras', sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column('features', postgresql.JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint('slug', name='uq_billing_plans_slug'),
    )

    # 2. tenant_subscriptions
    op.create_table(
        'tenant_subscriptions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('plan_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('billing_plans.id'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default=sa.text("'active'")),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('custom_limits', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Index('ix_tenant_subs_tenant', 'tenant_id'),
    )

    # 3. tenant.onboarding_complete
    op.add_column('tenants', sa.Column('onboarding_complete', sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column('tenants', 'onboarding_complete')
    op.drop_table('tenant_subscriptions')
    op.drop_table('billing_plans')
