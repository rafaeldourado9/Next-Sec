"""add analytics tables

Revision ID: 008
Revises: 007
Create Date: 2026-04-11 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '008'
down_revision: Union[str, None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Plugin installations table
    op.create_table(
        'plugin_installations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('plugin_id', sa.String(50), nullable=False),
        sa.Column('plugin_name', sa.String(100), nullable=False),
        sa.Column('version', sa.String(20), nullable=False, server_default='1.0.0'),
        sa.Column('edge_agent_id', sa.String(100), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='installed'),
        sa.Column('settings', postgresql.JSON, nullable=False, server_default='{}'),
        sa.Column('model_path', sa.String(500), nullable=True),
        sa.Column('fps_target', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index('idx_plugin_installations_tenant', 'plugin_installations', ['tenant_id'])
    op.create_index('idx_plugin_installations_plugin_id', 'plugin_installations', ['plugin_id'])
    op.create_index('idx_plugin_installations_edge_agent', 'plugin_installations', ['edge_agent_id'])
    op.create_index('idx_plugin_installations_status', 'plugin_installations', ['status'])

    # Analytics events table
    op.create_table(
        'analytics_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('plugin_installation_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('plugin_installations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('camera_id', sa.String(100), nullable=False),
        sa.Column('camera_name', sa.String(200), nullable=True),
        sa.Column('plugin_id', sa.String(50), nullable=False),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('severity', sa.String(20), nullable=False, server_default='info'),
        sa.Column('confidence', sa.Float, nullable=True),
        sa.Column('payload', postgresql.JSON, nullable=False, server_default='{}'),
        sa.Column('snapshot_path', sa.String(500), nullable=True),
        sa.Column('occurred_at', sa.DateTime, nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index('idx_analytics_events_tenant', 'analytics_events', ['tenant_id'])
    op.create_index('idx_analytics_events_camera', 'analytics_events', ['camera_id'])
    op.create_index('idx_analytics_events_plugin', 'analytics_events', ['plugin_id'])
    op.create_index('idx_analytics_events_event_type', 'analytics_events', ['event_type'])
    op.create_index('idx_analytics_events_severity', 'analytics_events', ['severity'])
    op.create_index('idx_analytics_events_occurred', 'analytics_events', [sa.text('occurred_at DESC')])


def downgrade() -> None:
    op.drop_table('analytics_events')
    op.drop_index('idx_plugin_installations_status', table_name='plugin_installations')
    op.drop_index('idx_plugin_installations_edge_agent', table_name='plugin_installations')
    op.drop_index('idx_plugin_installations_plugin_id', table_name='plugin_installations')
    op.drop_index('idx_plugin_installations_tenant', table_name='plugin_installations')
    op.drop_table('plugin_installations')
