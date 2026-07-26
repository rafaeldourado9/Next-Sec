"""lgpd: create retention_policies table

Revision ID: 019
Revises: 018
Create Date: 2026-04-12 20:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '019'
down_revision: Union[str, None] = '018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'retention_policies',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('data_type', sa.String(50), nullable=False),  # video, alpr, face, audit, analytics
        sa.Column('retention_days', sa.Integer(), nullable=False),
        sa.Column('anonymize_instead_of_delete', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('auto_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('tenant_id', 'data_type', name='uq_retention_policy'),
    )

    # Seed inicial: políticas padrão por tipo (CAST explícito evita ambiguidade no UNION)
    op.execute("""
        INSERT INTO retention_policies (tenant_id, data_type, retention_days, anonymize_instead_of_delete, auto_enabled)
        SELECT t.id::uuid, v.data_type, v.retention_days, v.anonymize, v.auto_enabled
        FROM tenants t
        CROSS JOIN (VALUES
            ('video'::varchar,     30,   true,  true),
            ('alpr'::varchar,      90,   true,  true),
            ('face'::varchar,      30,   true,  true),
            ('audit'::varchar,     1825, false, true),
            ('analytics'::varchar, 365,  true,  true)
        ) AS v(data_type, retention_days, anonymize, auto_enabled)
    """)


def downgrade() -> None:
    op.drop_table('retention_policies')
