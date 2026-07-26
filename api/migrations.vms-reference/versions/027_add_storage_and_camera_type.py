"""recordings: add storage_key, storage_backend, deleted_at; cameras: add camera_type

Revision ID: 027
Revises: 026
Create Date: 2026-05-31 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "027"
down_revision: Union[str, None] = "026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # RecordingSegment: storage fields + soft-delete
    op.add_column(
        "recording_segments",
        sa.Column("storage_key", sa.String(1000), nullable=True),
    )
    op.add_column(
        "recording_segments",
        sa.Column("storage_backend", sa.String(50), nullable=False, server_default="minio"),
    )
    op.add_column(
        "recording_segments",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Camera: camera_type
    op.add_column(
        "cameras",
        sa.Column("camera_type", sa.String(50), nullable=False, server_default="internal"),
    )


def downgrade() -> None:
    op.drop_column("cameras", "camera_type")
    op.drop_column("recording_segments", "deleted_at")
    op.drop_column("recording_segments", "storage_backend")
    op.drop_column("recording_segments", "storage_key")
