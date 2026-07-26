"""lgpd: cleanup old billing tables and columns from incorrect sprint 13

Revision ID: 017b
Revises: 017
Create Date: 2026-04-12 20:15:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '017b'
down_revision: Union[str, None] = '017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remover colunas adicionadas erroneamente em 017 (idempotente)
    op.execute("ALTER TABLE tenants DROP CONSTRAINT IF EXISTS fk_tenants_billing_plan")
    cols_to_drop = [
        'billing_plan_id',
        'subscription_status',
        'subscription_started_at',
        'subscription_expires_at',
        'current_usage_cameras',
        'current_usage_storage_bytes',
        'current_monthly_events',
    ]
    for col in cols_to_drop:
        op.execute(f"ALTER TABLE tenants DROP COLUMN IF EXISTS {col}")

    # Remover tabelas criadas erroneamente em 016 e 018 (idempotente)
    op.execute("DROP TABLE IF EXISTS usage_records")
    op.execute("DROP TABLE IF EXISTS billing_plans")


def downgrade() -> None:
    # Se precisar reverter, recriar tabelas e colunas
    pass
