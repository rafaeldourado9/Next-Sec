"""audit: create audit_log table with partitioning

Revision ID: 012
Revises: 011
Create Date: 2026-04-12 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '012'
down_revision: Union[str, None] = '011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tabela particionada por mês para performance com anos de dados
    # Em tabelas particionadas no Postgres, a PK/uniques devem incluir as colunas
    # de particionamento — por isso usamos PK composta (id, occurred_at).
    op.create_table(
        'audit_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('user_email', sa.String(255), nullable=True),
        sa.Column('user_role', sa.String(50), nullable=True),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('resource_type', sa.String(50), nullable=True),
        sa.Column('resource_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('resource_name', sa.String(255), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),  # IPv6 max = 45 chars
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('request_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('payload', postgresql.JSONB(), nullable=True, server_default='{}'),
        sa.Column('result', sa.String(20), nullable=True, server_default='success'),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id', 'occurred_at', name='pk_audit_log'),
        postgresql_partition_by='RANGE (occurred_at)',
    )

    # Índices para consultas frequentes
    op.create_index('ix_audit_log_tenant_occurred', 'audit_log', ['tenant_id', 'occurred_at'])
    op.create_index('ix_audit_log_user_occurred', 'audit_log', ['user_id', 'occurred_at'], postgresql_where=sa.text('user_id IS NOT NULL'))
    op.create_index('ix_audit_log_action_occurred', 'audit_log', ['action', 'occurred_at'])
    op.create_index('ix_audit_log_resource', 'audit_log', ['resource_type', 'resource_id'])

    # Partição inicial (primeiro mês de operação)
    # Em produção, criar partições futuras antecipadamente via cron job
    op.execute("""
        CREATE TABLE audit_log_2026_04 PARTITION OF audit_log
        FOR VALUES FROM ('2026-04-01') TO ('2026-05-01')
    """)


def downgrade() -> None:
    op.execute("DROP TABLE audit_log CASCADE")
