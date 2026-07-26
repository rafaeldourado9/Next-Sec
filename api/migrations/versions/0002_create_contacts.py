"""Contatos (telefones) cadastrados pelo cliente final para receber alertas.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-26 00:01:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "contacts",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=True,
                  comment="NULL = recebe alertas de todas as câmeras do tenant"),
        sa.Column("phone_number", sa.String(20), nullable=False, comment="E.164, ex: +5511999999999"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_contacts_tenant", "contacts", ["tenant_id"],
                     postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("idx_contacts_camera", "contacts", ["camera_id"],
                     postgresql_where=sa.text("deleted_at IS NULL"))


def downgrade() -> None:
    op.drop_table("contacts")
