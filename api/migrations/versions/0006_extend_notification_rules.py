"""Estende notification_rules para suportar destino=contato + canal WhatsApp.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-26 00:05:00.000000

Ver ADR-009. destination_url/webhook_secret viram nullable porque uma regra
com destination_type='contact' não usa webhook. Banco ainda vazio neste
ponto do desenvolvimento — não precisa do padrão de 3 fases (ver
.genesis/contracts/migrations.md).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "notification_rules",
        sa.Column("destination_type", sa.String(20), nullable=False, server_default="webhook"),
    )
    op.add_column(
        "notification_rules",
        sa.Column("contact_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("contacts.id", ondelete="CASCADE"), nullable=True),
    )
    op.add_column(
        "notification_rules",
        sa.Column("channel", sa.String(20), nullable=False, server_default="whatsapp"),
    )
    op.add_column(
        "notification_rules",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.alter_column("notification_rules", "destination_url", nullable=True)
    op.alter_column("notification_rules", "webhook_secret", nullable=True)

    op.create_check_constraint(
        "chk_notification_rule_destination",
        "notification_rules",
        "(destination_type = 'webhook' AND destination_url IS NOT NULL AND contact_id IS NULL) "
        "OR (destination_type = 'contact' AND contact_id IS NOT NULL)",
    )
    op.create_index("idx_notification_rules_contact", "notification_rules", ["contact_id"])


def downgrade() -> None:
    op.drop_index("idx_notification_rules_contact", table_name="notification_rules")
    op.drop_constraint("chk_notification_rule_destination", "notification_rules", type_="check")
    op.alter_column("notification_rules", "webhook_secret", nullable=False)
    op.alter_column("notification_rules", "destination_url", nullable=False)
    op.drop_column("notification_rules", "updated_at")
    op.drop_column("notification_rules", "channel")
    op.drop_column("notification_rules", "contact_id")
    op.drop_column("notification_rules", "destination_type")
