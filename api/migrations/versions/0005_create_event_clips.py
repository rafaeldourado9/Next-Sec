"""Clipe de 5-10s do evento, rastreado no storage provider (event_clips).

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-26 00:04:00.000000

NOTA: FK aponta para `vms_events`, não `analytics_events`. O pipeline real
(PluginService.ingest_event, chamado por POST /plugins/events — o endpoint
que o serviço `analytics/` de fato usa via VMSClient.ingest_event) grava em
VmsEventModel/vms_events. `analytics_events` (AnalyticsEvent) é populada por
um endpoint diferente (POST /analytics/events) que o pipeline real de
intrusion/face_recognition não usa — ver .genesis/architecture/reuse-plan.md.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "event_clips",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("vms_event_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("vms_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("storage_provider", sa.String(50), nullable=False, server_default="local"),
        sa.Column("storage_ref", sa.String(500), nullable=True,
                  comment="key do objeto no MinIO (ou file id de um provider externo futuro)"),
        sa.Column("storage_url", sa.String(2000), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("error_message", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('pending', 'staged', 'uploaded', 'failed')",
            name="chk_event_clips_status",
        ),
        sa.UniqueConstraint("vms_event_id", name="uq_event_clips_event"),
    )
    op.create_index("idx_event_clips_status", "event_clips", ["status"],
                     postgresql_where=sa.text("status != 'uploaded'"))


def downgrade() -> None:
    op.drop_table("event_clips")
