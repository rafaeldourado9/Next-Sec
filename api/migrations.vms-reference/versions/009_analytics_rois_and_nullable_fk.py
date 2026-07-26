"""analytics: ROIs table + nullable plugin_installation_id

Revision ID: 009
Revises: 008
Create Date: 2026-04-11 20:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '009'
down_revision: Union[str, None] = '008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Tornar plugin_installation_id nullable e mudar ondelete para SET NULL
    op.drop_constraint(
        'analytics_events_plugin_installation_id_fkey',
        'analytics_events',
        type_='foreignkey',
    )
    op.alter_column('analytics_events', 'plugin_installation_id', nullable=True)
    op.create_foreign_key(
        'analytics_events_plugin_installation_id_fkey',
        'analytics_events',
        'plugin_installations',
        ['plugin_installation_id'],
        ['id'],
        ondelete='SET NULL',
    )

    # 2. Criar tabela de ROIs
    op.create_table(
        'analytics_rois',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('camera_id', sa.String(100), nullable=False),
        sa.Column('plugin_id', sa.String(50), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('polygon', postgresql.JSON, nullable=False, server_default='[]'),
        sa.Column('config', postgresql.JSON, nullable=False, server_default='{}'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index('idx_analytics_rois_tenant', 'analytics_rois', ['tenant_id'])
    op.create_index('idx_analytics_rois_camera', 'analytics_rois', ['camera_id'])
    op.create_index('idx_analytics_rois_plugin', 'analytics_rois', ['plugin_id'])


def downgrade() -> None:
    op.drop_index('idx_analytics_rois_plugin', table_name='analytics_rois')
    op.drop_index('idx_analytics_rois_camera', table_name='analytics_rois')
    op.drop_index('idx_analytics_rois_tenant', table_name='analytics_rois')
    op.drop_table('analytics_rois')

    op.drop_constraint(
        'analytics_events_plugin_installation_id_fkey',
        'analytics_events',
        type_='foreignkey',
    )
    op.alter_column('analytics_events', 'plugin_installation_id', nullable=False)
    op.create_foreign_key(
        'analytics_events_plugin_installation_id_fkey',
        'analytics_events',
        'plugin_installations',
        ['plugin_installation_id'],
        ['id'],
        ondelete='CASCADE',
    )
