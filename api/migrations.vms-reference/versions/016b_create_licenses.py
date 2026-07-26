"""billing: replace billing_plans with licenses model

Revision ID: 016b
Revises: 015
Create Date: 2026-04-12 18:00:00.000000

Modelo: Licença por câmera (não plano por tenant)
- Cada câmera precisa de uma licença ativa
- Tipos: CAMERA_ONLY, CAMERA_STORAGE, CAMERA_ANALYTICS
- Licenças têm validade e recursos associados
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '016b'
down_revision: Union[str, None] = '015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tabela de licenças por câmera
    op.create_table(
        'licenses',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('camera_id', postgresql.UUID(as_uuid=True), nullable=True),  # NULL = licença avulsa
        sa.Column('license_type', sa.String(30), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('storage_limit_gb', sa.Integer(), nullable=True),
        sa.Column('analytics_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('activated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Index('ix_licenses_tenant', 'tenant_id'),
        sa.Index('ix_licenses_camera', 'camera_id'),
        sa.Index('ix_licenses_type', 'license_type'),
    )


def downgrade() -> None:
    op.drop_table('licenses')
