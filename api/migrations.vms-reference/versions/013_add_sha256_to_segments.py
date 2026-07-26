"""recordings: add sha256_hash, integrity_verified_at, custody_chain

Revision ID: 013
Revises: 012
Create Date: 2026-04-12 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '013'
down_revision: Union[str, None] = '012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'recording_segments',
        sa.Column('sha256_hash', sa.String(64), nullable=True),
    )
    op.add_column(
        'recording_segments',
        sa.Column('integrity_verified_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'recording_segments',
        sa.Column('custody_chain', postgresql.JSONB(), nullable=True, server_default='[]'),
    )


def downgrade() -> None:
    op.drop_column('recording_segments', 'custody_chain')
    op.drop_column('recording_segments', 'integrity_verified_at')
    op.drop_column('recording_segments', 'sha256_hash')
