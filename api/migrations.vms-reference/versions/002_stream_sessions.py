"""Adicionar tabela stream_sessions.

Revision ID: 002
Revises: 001
Create Date: 2026-03-30 12:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: str = "001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Cria tabela stream_sessions."""
    op.create_table(
        "stream_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "camera_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("cameras.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mediamtx_path", sa.String(500), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_stream_sessions_tenant_id", "stream_sessions", ["tenant_id"])
    op.create_index("ix_stream_sessions_camera_id", "stream_sessions", ["camera_id"])
    op.create_index(
        "ix_stream_sessions_tenant_camera",
        "stream_sessions",
        ["tenant_id", "camera_id"],
    )


def downgrade() -> None:
    """Remove tabela stream_sessions."""
    op.drop_table("stream_sessions")
