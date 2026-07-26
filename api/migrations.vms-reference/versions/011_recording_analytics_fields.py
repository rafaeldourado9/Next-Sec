"""recordings: add analytics batch processing fields

Revision ID: 011
Revises: 010
Create Date: 2026-04-12 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '011'
down_revision: Union[str, None] = '010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'recording_segments',
        sa.Column('analytics_processed', sa.Boolean(), nullable=True, server_default='false'),
    )
    op.add_column(
        'recording_segments',
        sa.Column('analytics_plugins_processed', postgresql.JSONB(), nullable=True, server_default='[]'),
    )
    op.add_column(
        'recording_segments',
        sa.Column('analytics_processed_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('recording_segments', 'analytics_processed_at')
    op.drop_column('recording_segments', 'analytics_plugins_processed')
    op.drop_column('recording_segments', 'analytics_processed')
