"""event_clips ganha tenant_id e size_bytes — cota de storage por cliente (ADR-018 §4).

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-01 14:00:00.000000

Sem estas duas colunas não há como responder "quanto este cliente já ocupa?"
sem varrer `event_clips` inteira com JOIN em `vms_events` a cada upload —
justamente o tipo de custo por evento que a ADR-018 quer tirar do caminho.
`tenant_id` é denormalizado de propósito (a fonte continua sendo
`vms_events.tenant_id`): o clipe nunca muda de dono, então não há risco de
divergência, e a cota vira um SUM sobre índice.

`size_bytes` também é o que permite a retenção por licença
(`clip_retention_days`) reportar quanto espaço de fato liberou.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "event_clips",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.add_column(
        "event_clips",
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
    )

    # Backfill: clipes existentes herdam o tenant do evento que os originou.
    op.execute(
        """
        UPDATE event_clips AS ec
        SET tenant_id = e.tenant_id
        FROM vms_events AS e
        WHERE e.id = ec.vms_event_id AND ec.tenant_id IS NULL
        """
    )

    op.create_index(
        "ix_event_clips_tenant_created", "event_clips", ["tenant_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_event_clips_tenant_created", table_name="event_clips")
    op.drop_column("event_clips", "size_bytes")
    op.drop_column("event_clips", "tenant_id")
