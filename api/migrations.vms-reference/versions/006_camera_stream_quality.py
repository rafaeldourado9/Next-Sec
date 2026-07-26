"""006_camera_stream_quality — adiciona coluna stream_quality à tabela cameras

Revision ID: 006
Revises: 005
Create Date: 2026-04-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: str = "005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column(
            "stream_quality",
            sa.String(20),
            nullable=False,
            server_default="high",
        ),
    )


def downgrade() -> None:
    op.drop_column("cameras", "stream_quality")
