"""billing: create billing_plans table

Revision ID: 016
Revises: 015
Create Date: 2026-04-12 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '016'
down_revision: Union[str, None] = '015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'billing_plans',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('slug', sa.String(50), nullable=False, unique=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('price_monthly', sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('max_cameras', sa.Integer(), nullable=True),
        sa.Column('storage_limit_gb', sa.Integer(), nullable=True),
        sa.Column('max_events_per_month', sa.Integer(), nullable=True),
        sa.Column('max_retention_days', sa.Integer(), nullable=False, server_default='7'),
        sa.Column('analytics_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('features', postgresql.JSONB(), nullable=True, server_default='{}'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_billing_plans_slug', 'billing_plans', ['slug'])

    # Seed inicial: 3 planos padrão
    op.execute("""
        INSERT INTO billing_plans (name, slug, description, price_monthly, max_cameras, storage_limit_gb, max_events_per_month, max_retention_days, analytics_enabled, features, is_active)
        VALUES
            ('Básico', 'basic', 'Para pequenos negócios', 99.00, 10, 100, 10000, 7, false, '{"priority": 1}', true),
            ('Profissional', 'professional', 'Para médias empresas', 299.00, 50, 500, 50000, 30, true, '{"priority": 2}', true),
            ('Enterprise', 'enterprise', 'Para grandes operações', 999.00, null, null, null, 90, true, '{"priority": 3, "support": "24/7"}', true)
    """)


def downgrade() -> None:
    op.drop_table('billing_plans')
