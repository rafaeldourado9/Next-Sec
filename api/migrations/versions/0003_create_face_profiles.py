"""Watchlist de reconhecimento facial (face_profiles).

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-26 00:02:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "face_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("embedding", postgresql.JSONB(), nullable=True,
                  comment="Vetor de embedding facial — formato depende da lib escolhida no genesis-backend"),
        sa.Column("reference_image_path", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True,
                  comment="Soft delete — LGPD, direito ao apagamento"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_face_profiles_tenant", "face_profiles", ["tenant_id"],
                     postgresql_where=sa.text("deleted_at IS NULL"))


def downgrade() -> None:
    op.drop_table("face_profiles")
