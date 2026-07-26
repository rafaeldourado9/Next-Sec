"""vms_events: add image_path column

Revision ID: 026
Revises: 025
Create Date: 2026-05-03 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '026'
down_revision: Union[str, None] = '025'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'vms_events',
        sa.Column('image_path', sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('vms_events', 'image_path')
