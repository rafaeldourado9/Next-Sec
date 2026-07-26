"""cameras: add ISAPI integration fields

Revision ID: 015
Revises: 014
Create Date: 2026-04-12 17:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '015'
down_revision: Union[str, None] = '014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cameras', sa.Column('isapi_enabled', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('cameras', sa.Column('isapi_base_url', sa.String(2000), nullable=True))
    op.add_column('cameras', sa.Column('isapi_username', sa.String(255), nullable=True))
    op.add_column('cameras', sa.Column('isapi_password', sa.String(500), nullable=True))
    op.add_column('cameras', sa.Column('serial_number', sa.String(100), nullable=True))
    op.add_column('cameras', sa.Column('firmware_version', sa.String(50), nullable=True))
    op.add_column('cameras', sa.Column('model_name', sa.String(200), nullable=True))
    op.add_column('cameras', sa.Column('isapi_capabilities', postgresql.JSONB(), nullable=True, server_default='{}'))


def downgrade() -> None:
    op.drop_column('cameras', 'isapi_capabilities')
    op.drop_column('cameras', 'model_name')
    op.drop_column('cameras', 'firmware_version')
    op.drop_column('cameras', 'serial_number')
    op.drop_column('cameras', 'isapi_password')
    op.drop_column('cameras', 'isapi_username')
    op.drop_column('cameras', 'isapi_base_url')
    op.drop_column('cameras', 'isapi_enabled')
