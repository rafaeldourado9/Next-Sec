"""007_camera_geo_and_ia — adiciona latitude, longitude, address e ia_enabled a cameras

Revision ID: 007
Revises: 006
Create Date: 2026-04-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: str = "006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("cameras", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("cameras", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column("cameras", sa.Column("address", sa.String(500), nullable=True))
    op.add_column(
        "cameras",
        sa.Column(
            "ia_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("cameras", "ia_enabled")
    op.drop_column("cameras", "address")
    op.drop_column("cameras", "longitude")
    op.drop_column("cameras", "latitude")
