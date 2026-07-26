"""vod: create vod_streams table

Revision ID: 010
Revises: 009
Create Date: 2026-04-12 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '010'
down_revision: Union[str, None] = '009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'vod_streams',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('camera_id', sa.String(), nullable=False),
        sa.Column('segments', postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('playlist_path', sa.Text(), nullable=True, server_default=''),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    
    # Índices para consultas frequentes
    op.create_index('ix_vod_streams_tenant_id', 'vod_streams', ['tenant_id'])
    op.create_index('ix_vod_streams_camera_id', 'vod_streams', ['camera_id'])
    op.create_index('ix_vod_streams_status', 'vod_streams', ['status'])


def downgrade() -> None:
    op.drop_table('vod_streams')
