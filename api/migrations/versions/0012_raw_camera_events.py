"""Cria raw_camera_events — ledger imutável do payload bruto de webhooks de câmera.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-28 00:10:00.000000

NOTA (Next Sec): achado durante teste real com câmera Intelbras ALPR — o
normalizer (events/normalizers/intelbras.py, formato ITSCAM) descarta o
objeto `Picture` inteiro do payload antes de salvar em `vms_events.payload`,
pra não guardar o JPEG embutido (grande demais pro Postgres). Só que isso
joga fora TAMBÉM o `Picture.Plate.Confidence`/`PlateNumber` originais —
sem eles, não dá pra auditar por que uma leitura veio com confiança 100%
mesmo com a placa claramente truncada (ex: "C23"), nem reprocessar depois
que o bug de mapeamento for corrigido. Esta tabela é o payload bruto
completo, nunca mutado (só ganha `vms_event_id` depois que o evento
processado é criado) -- um ledger de auditoria/replay, não a fonte usada
pela UI (que continua sendo `vms_events`).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "raw_camera_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("vms_event_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("manufacturer", sa.String(50), nullable=False),
        sa.Column("source_ip", sa.String(64), nullable=True),
        sa.Column("body", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["vms_event_id"], ["vms_events.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_raw_camera_events_tenant_id", "raw_camera_events", ["tenant_id"])
    op.create_index("ix_raw_camera_events_camera_id", "raw_camera_events", ["camera_id"])
    op.create_index("ix_raw_camera_events_vms_event_id", "raw_camera_events", ["vms_event_id"])
    op.create_index("ix_raw_camera_events_tenant_received", "raw_camera_events", ["tenant_id", "received_at"])


def downgrade() -> None:
    op.drop_index("ix_raw_camera_events_tenant_received", table_name="raw_camera_events")
    op.drop_index("ix_raw_camera_events_vms_event_id", table_name="raw_camera_events")
    op.drop_index("ix_raw_camera_events_camera_id", table_name="raw_camera_events")
    op.drop_index("ix_raw_camera_events_tenant_id", table_name="raw_camera_events")
    op.drop_table("raw_camera_events")
