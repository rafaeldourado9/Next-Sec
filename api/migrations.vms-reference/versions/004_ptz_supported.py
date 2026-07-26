"""004_ptz_supported — flag de suporte PTZ na câmera

Revision ID: 004
Revises: 003
Create Date: 2026-04-10
"""

from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column(
            "ptz_supported",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("cameras", "ptz_supported")
