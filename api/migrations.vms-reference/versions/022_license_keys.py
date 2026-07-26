"""billing: license_keys + analytics_pricing (two deployment models)

White Label (Managed):   R$ 15.000/ano + storage R$50/cam/mês + analytics mensal
White Label (Self-Hosted): R$ 20.000/ano + storage por conta do cliente + analytics por conta do cliente

Formato da license key: XXXX-XXXXX-XXXXX-XXXXX-XXXXX (4-5-5-5-5)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '022'
down_revision: Union[str, None] = '021'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. license_keys
    op.create_table(
        'license_keys',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('license_key', sa.String(29), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('deployment_model', sa.String(20), nullable=False, server_default=sa.text("'managed'")),
        sa.Column('status', sa.String(20), nullable=False, server_default=sa.text("'active'")),
        sa.Column('max_cameras', sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column('price_annual', sa.Numeric(10, 2), nullable=False, server_default=sa.text("0")),
        sa.Column('hardware_id', sa.String(64), nullable=True),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint('license_key', name='uq_license_keys_key'),
        sa.Index('ix_license_keys_tenant', 'tenant_id'),
    )

    # 2. analytics_pricing
    op.create_table(
        'analytics_pricing',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('plugin_name', sa.String(50), nullable=False),
        sa.Column('tier', sa.String(20), nullable=False, server_default=sa.text("'light'")),
        sa.Column('price_per_camera_per_day', sa.Numeric(10, 4), nullable=False, server_default=sa.text("6.90")),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint('plugin_name', name='uq_analytics_pricing_plugin'),
    )

    # 3. tenant: onboarding_complete + license_key_id (idempotente — 021 já pode ter adicionado onboarding_complete)
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS onboarding_complete BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS license_key_id UUID NULL")


def downgrade() -> None:
    op.drop_column('tenants', 'license_key_id')
    op.drop_column('tenants', 'onboarding_complete')
    op.drop_table('analytics_pricing')
    op.drop_table('license_keys')
