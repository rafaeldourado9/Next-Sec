"""Adiciona cameras.recording_enabled + tabela recording_windows.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-27 13:00:00.000000

NOTA (Next Sec): gravação contínua era explicitamente fora do escopo do MVP
(mediamtx.yml pathDefaults.record: no). Esta migration reativa o suporte,
opt-in por câmera (recording_enabled default false — incidente anterior
documentado em cameras/mediamtx.py mostrou que ligar gravação globalmente
derrubava o muxer HLS ao vivo em câmeras WiFi instáveis).

`recording_windows` NÃO é o índice de segmentos físicos — o MediaMTX já
gerencia os arquivos fMP4 no disco e os apaga sozinho via recordDeleteAfter
(mapeado de cameras.retention_days). Esta tabela é só um índice leve de
"quais intervalos de tempo têm gravação" por câmera, pra sombrear a timeline
no frontend — 1 linha por sessão contígua (estendida a cada segmento
completo via webhook on_record_segment_complete), não 1 linha por arquivo.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column("recording_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )

    op.create_table(
        "recording_windows",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True,
                  comment="null = janela ainda aberta (última gravação em andamento)"),
        sa.Column("segment_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "idx_recording_windows_camera_range", "recording_windows",
        ["camera_id", "started_at", "ended_at"],
    )
    op.create_index(
        "idx_recording_windows_open", "recording_windows", ["camera_id"],
        postgresql_where=sa.text("ended_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_recording_windows_open", table_name="recording_windows")
    op.drop_index("idx_recording_windows_camera_range", table_name="recording_windows")
    op.drop_table("recording_windows")
    op.drop_column("cameras", "recording_enabled")
