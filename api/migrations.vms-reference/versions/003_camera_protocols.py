"""003_camera_protocols — suporte a rtsp_pull / rtmp_push / onvif

Revision ID: 003
Revises: 002
Create Date: 2026-03-31
"""

from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # stream_protocol com default retrocompatível (todas as câmeras existentes são rtsp_pull)
    op.add_column(
        "cameras",
        sa.Column(
            "stream_protocol",
            sa.String(50),
            nullable=False,
            server_default="rtsp_pull",
        ),
    )

    # rtsp_url passa a ser nullable (rtmp_push não tem rtsp_url própria)
    op.alter_column("cameras", "rtsp_url", nullable=True)

    op.add_column("cameras", sa.Column("rtmp_stream_key", sa.String(100), nullable=True))
    op.create_unique_constraint("uq_cameras_rtmp_stream_key", "cameras", ["rtmp_stream_key"])

    op.add_column("cameras", sa.Column("onvif_url", sa.String(2000), nullable=True))
    op.add_column("cameras", sa.Column("onvif_username", sa.String(255), nullable=True))
    op.add_column("cameras", sa.Column("onvif_password", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_constraint("uq_cameras_rtmp_stream_key", "cameras", type_="unique")
    op.drop_column("cameras", "onvif_password")
    op.drop_column("cameras", "onvif_username")
    op.drop_column("cameras", "onvif_url")
    op.drop_column("cameras", "rtmp_stream_key")
    op.alter_column("cameras", "rtsp_url", nullable=False)
    op.drop_column("cameras", "stream_protocol")
