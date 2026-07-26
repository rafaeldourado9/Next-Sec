"""Horário de ativação da zona (roi_schedules) — múltiplos turnos/dia.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-26 00:03:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "roi_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("roi_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("analytics_rois.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day_of_week", sa.SmallInteger(), nullable=True,
                  comment="0-6, NULL = todo dia"),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False,
                  comment="Pode ser < start_time (janela vira a meia-noite, ex: 20:30-06:00)"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("day_of_week BETWEEN 0 AND 6", name="chk_roi_schedules_day_of_week"),
    )
    op.create_index("idx_roi_schedules_roi", "roi_schedules", ["roi_id"],
                     postgresql_where=sa.text("is_active = true"))


def downgrade() -> None:
    op.drop_table("roi_schedules")
