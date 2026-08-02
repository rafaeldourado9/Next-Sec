"""Ativação de edge por licença + idempotência de evento (ADR-018).

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-01 10:00:00.000000

Duas mudanças independentes, na mesma migration porque nascem da mesma decisão
(ADR-018) e uma sem a outra não entrega nada:

1. `license_keys` deixa de ser só um registro comercial e passa a ser a
   credencial de bootstrap do agente — precisa saber em que máquina foi
   ativada (`hardware_fingerprint`, vínculo 1:1 que impede uma licença virar N
   instalações), qual agent ela provisionou, e carregar os limites operacionais
   que a VPS impõe àquele cliente (ver ADR-018 §4/§5).

2. `vms_events.client_event_id` — UUID gerado no edge, chave de idempotência do
   ingest em lote. Sem ele, uma resposta perdida por timeout obriga o edge a
   escolher entre perder o evento ou duplicá-lo. Único por tenant (não global):
   o ID vem do cliente, então dois tenants podem colidir sem que isso seja erro.

Defaults dos limites: escolhidos para caber no orçamento de storage calculado
na ADR-018 §4 (~150 GB estáveis para 1000 tenants). Licenças existentes herdam
os mesmos valores via server_default.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ─── 1. license_keys como credencial de ativação ────────────────────────
    op.add_column(
        "license_keys",
        sa.Column("hardware_fingerprint", sa.String(64), nullable=True),
    )
    op.add_column(
        "license_keys",
        sa.Column("activated_hostname", sa.String(255), nullable=True),
    )
    op.add_column(
        "license_keys",
        sa.Column("agent_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.add_column(
        "license_keys",
        sa.Column("agent_version", sa.String(32), nullable=True),
    )
    op.add_column(
        "license_keys",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ─── 2. Limites operacionais por licença (ADR-018 §4/§5) ────────────────
    op.add_column(
        "license_keys",
        sa.Column("events_per_minute", sa.Integer(), nullable=False, server_default="120"),
    )
    op.add_column(
        "license_keys",
        sa.Column("clip_seconds", sa.Integer(), nullable=False, server_default="15"),
    )
    op.add_column(
        "license_keys",
        sa.Column("clip_max_height", sa.Integer(), nullable=False, server_default="480"),
    )
    op.add_column(
        "license_keys",
        sa.Column("clip_retention_days", sa.Integer(), nullable=False, server_default="30"),
    )
    op.add_column(
        "license_keys",
        sa.Column("storage_quota_mb", sa.Integer(), nullable=False, server_default="5120"),
    )

    # Fingerprint único: a mesma máquina não pode aparecer sob duas licenças, e
    # duas máquinas não podem compartilhar uma. Parcial (WHERE NOT NULL) porque
    # licença ainda não ativada tem fingerprint nulo — e NULL não colide em
    # unique index no Postgres, mas o índice parcial deixa a intenção explícita.
    op.create_index(
        "uq_license_keys_fingerprint",
        "license_keys",
        ["hardware_fingerprint"],
        unique=True,
        postgresql_where=sa.text("hardware_fingerprint IS NOT NULL"),
    )

    # ─── 3. Idempotência do ingest em lote ──────────────────────────────────
    op.add_column(
        "vms_events",
        sa.Column("client_event_id", sa.String(64), nullable=True),
    )
    op.create_index(
        "uq_vms_events_tenant_client_event",
        "vms_events",
        ["tenant_id", "client_event_id"],
        unique=True,
        postgresql_where=sa.text("client_event_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_vms_events_tenant_client_event", table_name="vms_events")
    op.drop_column("vms_events", "client_event_id")

    op.drop_index("uq_license_keys_fingerprint", table_name="license_keys")
    for column in (
        "storage_quota_mb",
        "clip_retention_days",
        "clip_max_height",
        "clip_seconds",
        "events_per_minute",
        "last_seen_at",
        "agent_version",
        "agent_id",
        "activated_hostname",
        "hardware_fingerprint",
    ):
        op.drop_column("license_keys", column)
